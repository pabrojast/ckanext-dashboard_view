"""Authorized sources and asynchronous, immutable dashboard cache generations."""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid
from urllib.parse import unquote, urljoin, urlsplit

from .security import SourceError, authorize_resource, context_for, download, linked_cs_source

PREFIX = 'ckanext.dashboard_view.'
DEFAULTS = {
    'cache_dir': '/var/lib/ckan/dashboard-cache', 'refresh_seconds': 300,
    'max_file_bytes': 268435456, 'max_rows': 5000000, 'max_columns': 500,
    'max_xlsx_uncompressed_bytes': 1073741824, 'memory_limit': '1GB',
    'build_timeout': 900, 'query_timeout': 90, 'download_timeout': 120,
    'queue_build': 'dashboard-build', 'queue_query': 'dashboard-query',
    'max_export_bytes': 1073741824,
}


def setting(name):
    import ckan.plugins.toolkit as tk
    value = tk.config.get(PREFIX + name, DEFAULTS[name])
    return int(value) if isinstance(DEFAULTS[name], int) else value


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(compact(value).encode('utf-8')).hexdigest()


def redis_connection():
    from ckan.lib.redis import connect_to_redis
    return connect_to_redis()


def redis_key(kind, key):
    import ckan.plugins.toolkit as tk
    return 'ckan:dashboard:%s:%s:%s' % (digest(tk.config.get('ckan.site_id', 'default'))[:16], kind, key)


def _root():
    root = Path(setting('cache_dir'))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def resource_stamp(resource):
    return digest({key: resource.get(key) for key in (
        'id', 'url', 'url_type', 'format', 'last_modified', 'hash', 'size',
        'datastore_active', 'datastore_contains_all_records', 'state')})


def source_key(resource, source):
    return digest({'resource': resource_stamp(resource), 'source': source})


def source_dir(key):
    if not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('Invalid cache identifier')
    directory = _root() / key
    directory.mkdir(mode=0o700, exist_ok=True)
    os.utime(directory, None)
    return directory


def read_json(path):
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)
    except (FileNotFoundError, ValueError, OSError):
        return None


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name('.%s.%s.tmp' % (path.name, uuid.uuid4().hex))
    try:
        with open(temporary, 'x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def current_generation(key):
    directory = source_dir(key)
    manifest = read_json(directory / 'current.json')
    if not manifest or not re.fullmatch('[a-f0-9]{32}', manifest.get('generation', '')):
        return None
    path = directory / manifest['generation']
    if not (path / 'table.duckdb').is_file():
        return None
    profile = read_json(path / 'profile.json')
    if not profile:
        return None
    return manifest, profile, path


def invalidate_generation(key, code, generation=None):
    """A fatal source failure must remain closed after its Redis error expires."""
    directory = source_dir(key)
    manifest = read_json(directory / 'current.json')
    if not manifest or (generation and manifest.get('generation') != generation):
        return
    manifest['blocked'] = code
    manifest['checked_at'] = 0
    atomic_json(directory / 'current.json', manifest)


def _load_state(key):
    raw = redis_connection().get(redis_key('state', key))
    state = json.loads(raw) if raw else None
    if state and state.get('status') == 'pending' and state.get('queued_at', time.time()) < time.time() - 15:
        try:
            from ckan.lib.jobs import job_from_id
            job = job_from_id(state['job_id'])
            status = job.get_status()
            status = getattr(status, 'value', status)
            failed = status in ('failed', 'stopped', 'canceled', 'finished')
        except KeyError:
            failed = True
        except Exception:
            failed = False
        if failed:
            finish_work(key, state['job_id'], {
                'status': 'error', 'code': 'job_interrupted',
                'message': 'Processing was interrupted or exceeded its time limit. Please try refreshing the dashboard.'}, ttl=30)
            latest = redis_connection().get(redis_key('state', key))
            return json.loads(latest) if latest else None
    return state


def _enqueue(kind, key, kwargs, force=False):
    """A Redis claim handles concurrent HTTP requests without duplicate jobs."""
    from ckan.lib.jobs import enqueue
    from .jobs import build_source, execute_query
    redis = redis_connection()
    lock_key = redis_key('lock', key)
    state_key = redis_key('state', key)
    if not force:
        state = _load_state(key)
        if state:
            return state
    claim = uuid.uuid4().hex
    timeout = setting('build_timeout' if kind == 'build' else 'query_timeout')
    if not redis.set(lock_key, claim, nx=True, ex=timeout + 300):
        return _load_state(key) or {'status': 'pending', 'message': 'Waiting for dashboard processing.'}
    state = {'status': 'pending', 'message': (
        'Preparing your data. Large files may take a few minutes.' if kind == 'build'
        else 'Calculating the dashboard.'), 'job_id': claim, 'queued_at': time.time()}
    redis.setex(state_key, timeout + 300, compact(state))
    try:
        enqueue(build_source if kind == 'build' else execute_query,
                kwargs=dict(kwargs, work_key=key, claim=claim),
                queue=setting('queue_build' if kind == 'build' else 'queue_query'),
                title='Prepare dashboard data' if kind == 'build' else 'Query dashboard',
                rq_kwargs={'timeout': timeout, 'result_ttl': 0, 'failure_ttl': 300, 'job_id': claim})
    except Exception:
        finish_work(key, claim, {'status': 'error', 'code': 'queue_unavailable',
                    'message': 'Dashboard processing is unavailable. Please try again shortly.'}, ttl=15)
        return _load_state(key)
    return state


def finish_work(key, claim, state, ttl=None):
    # Checking ownership, publishing the result and releasing the claim must be
    # atomic: an expired worker must never overwrite a newer job's state.
    return redis_connection().eval(
        'if redis.call("get", KEYS[1]) == ARGV[1] then '
        'redis.call("setex", KEYS[2], ARGV[2], ARGV[3]); '
        'return redis.call("del", KEYS[1]) else return 0 end',
        2, redis_key('lock', key), redis_key('state', key), claim,
        ttl or setting('refresh_seconds'), compact(state))


def _profile_ready(cached, state=None):
    manifest, profile, _ = cached
    result = dict(profile, status='ready', generation=manifest['generation'],
                  updated_at=manifest['updated_at'])
    if state and state.get('status') in ('pending', 'error'):
        result['refreshing'] = state['status'] == 'pending'
        warning = ('The source is updating. Showing the last completed update.'
                   if result['refreshing'] else
                   'The source could not be refreshed. Showing the last completed update; try refreshing again.')
        result['warnings'] = list(profile.get('warnings', [])) + [warning]
    return result


def prepare(resource, source, actor=None, force=False):
    from .schema import normalize_source
    source = normalize_source(source)
    key = source_key(resource, source)
    work_key = 'build-' + key
    cached = current_generation(key)
    previous = _load_state(work_key)
    if cached and previous and previous.get('status') == 'error' and previous.get('code') not in ('source_temporarily_unavailable', 'queue_unavailable', 'job_interrupted'):
        if not force:
            return previous, key
    if cached and not force and not cached[0].get('blocked'):
        manifest, _, _ = cached
        if time.time() - manifest['checked_at'] < setting('refresh_seconds'):
            return _profile_ready(cached, previous), key
    # Build status is transient. A ready status without the disk generation is
    # ignored so an emptyDir restart or cache eviction always rebuilds.
    if previous and previous.get('status') == 'ready':
        redis_connection().delete(redis_key('state', work_key))
    state = _enqueue('build', work_key, {
        'resource_id': resource['id'], 'source': source, 'actor': actor or '',
        'expected_stamp': resource_stamp(resource), 'cache_key': key,
    }, force=force)
    # Revalidation must not strand a previously prepared dashboard behind a
    # long import. This only serves the same source interpretation and resource
    # stamp, and the HTTP and worker boundaries still recheck access every time.
    if cached and not cached[0].get('blocked'):
        if state.get('status') == 'error' and state.get('code') not in ('source_temporarily_unavailable', 'queue_unavailable', 'job_interrupted'):
            return state, key
        return _profile_ready(cached, state), key
    return state, key


def run_query(resource, source, config, actor=None, filters=None, bounds=None, pages=None, export=False):
    profile, key = prepare(resource, source, actor)
    if profile['status'] != 'ready':
        return profile
    cached = current_generation(key)
    if not cached:
        return {'status': 'pending', 'message': 'The cache is rebuilding. Please try again.'}
    if cached[0].get('blocked'):
        return {'status': 'error', 'code': 'source_unavailable',
                'message': 'The source must be revalidated before this dashboard can be displayed.'}
    generation = cached[0]['generation']
    # Per-actor keys keep revoked users' prior work isolated. Every read still
    # passes current CKAN and download authorization, including cached exports.
    kwargs = {'resource_id': resource['id'], 'actor': actor or '', 'cache_key': key,
              'generation': generation, 'config': config, 'filters': filters or [],
              'bounds': bounds, 'pages': pages or {}, 'export': bool(export),
              'expected_stamp': resource_stamp(resource)}
    work_key = 'query-' + digest(kwargs)
    state = _load_state(work_key)
    if state and state.get('status') == 'ready' and export:
        if not (_root() / 'exports' / (work_key + '.csv')).is_file():
            redis_connection().delete(redis_key('state', work_key))
            state = None
    result = state or _enqueue('query', work_key, kwargs)
    if result.get('status') == 'ready' and 'refreshing' in profile:
        result = dict(result, refreshing=profile['refreshing'])
        warnings = list(result.get('warnings', []))
        for warning in profile.get('warnings', []):
            if warning not in warnings:
                warnings.append(warning)
        result['warnings'] = warnings
    return result


def export_path(work_key):
    if not re.fullmatch('query-[a-f0-9]{64}', work_key or ''):
        raise SourceError('Invalid export identifier.')
    return _root() / 'exports' / (work_key + '.csv')


def _copy_file(path, output):
    maximum = setting('max_file_bytes')
    if os.path.getsize(path) > maximum:
        raise SourceError('The source exceeds the configured file size limit.')
    size, sha = 0, hashlib.sha256()
    with open(path, 'rb') as source, open(output, 'wb') as target:
        for chunk in iter(lambda: source.read(65536), b''):
            size += len(chunk)
            if size > maximum:
                raise SourceError('The source exceeds the configured file size limit.')
            sha.update(chunk)
            target.write(chunk)
    return {'sha256': sha.hexdigest(), 'bytes': size, 'unchanged': False}


def _datastore_snapshot(resource, output, actor):
    """Bounded, repeatable-read snapshot; no user SQL and no write credentials."""
    import ckan.plugins.toolkit as tk
    import sqlalchemy as sa
    from ckanext.datastore.backend.postgres import get_read_engine
    tk.check_access('datastore_search', context_for(actor), {'resource_id': resource['id']})
    if not resource.get('datastore_active'):
        raise SourceError('This resource has no active DataStore table.')
    database = get_read_engine()
    with database.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        with connection.begin():
            connection.execute(sa.text('SET TRANSACTION READ ONLY'))
            connection.execute(sa.text('SET LOCAL statement_timeout = %s' % (setting('build_timeout') * 1000)))
            table = sa.Table(resource['id'], sa.MetaData(), autoload_with=connection)
            columns = [col for col in table.columns if col.name not in ('_id', '_full_text')]
            if len(columns) > setting('max_columns'):
                raise SourceError('The DataStore table exceeds the configured column limit.')
            if not columns:
                raise SourceError('The DataStore table contains no data columns.')
            statement = sa.select(*columns)
            if '_id' in table.columns:
                statement = statement.order_by(table.c._id)
            result = connection.execution_options(stream_results=True).execute(statement)
            try:
                count = 0
                with open(output, 'w', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow([column.name for column in columns])
                    while True:
                        rows = result.fetchmany(2000)
                        if not rows:
                            break
                        count += len(rows)
                        if count > setting('max_rows'):
                            raise SourceError('The DataStore table exceeds the configured row limit.')
                        writer.writerows(rows)
                        stream.flush()
                        if stream.tell() > setting('max_file_bytes'):
                            raise SourceError('The DataStore snapshot exceeds the configured file size limit.')
            finally:
                result.close()
    sha = hashlib.sha256()
    with open(output, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            sha.update(chunk)
    return {'sha256': sha.hexdigest(), 'bytes': os.path.getsize(output), 'unchanged': False}


def _csunesco_export(url, output, actor):
    """Resolve this site's known public CS export without a self-HTTP request."""
    source = linked_cs_source({'url': url}, actor)
    if source is None:
        return None
    from ckanext.csunesco.logic import ofform
    try:
        content = ofform.fetch_csv(source['form_id'])
    except ofform.OfformError:
        raise SourceError('The citizen science source is temporarily unavailable.', 'source_temporarily_unavailable') from None
    content = content.encode('utf-8') if isinstance(content, str) else content
    if len(content) > setting('max_file_bytes'):
        raise SourceError('The source exceeds the configured file size limit.')
    with open(output, 'wb') as target:
        target.write(content)
    return {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content), 'unchanged': False}


def _upload_location(resource):
    """Use the installed uploader's own signed URL support before local paths."""
    from ckan.lib.uploader import get_resource_uploader
    uploader = get_resource_uploader(dict(resource))
    signer = getattr(uploader, 'get_url_from_filename', None)
    if callable(signer):
        filename = unquote(urlsplit(resource.get('url') or '').path.rsplit('/', 1)[-1]).rsplit('/', 1)[-1]
        if filename:
            signed_url = signer(resource['id'], filename)
            if signed_url:
                return signed_url
    location = uploader.get_path(resource['id'])
    if not location:
        raise SourceError('The uploaded file is unavailable from its storage provider.', 'source_unavailable')
    return location


def materialize(resource, source, output, actor, validators=None):
    import ckan.plugins.toolkit as tk
    if source.get('kind') == 'datastore':
        return _datastore_snapshot(resource, output, actor), 'csv'
    format_hint = (resource.get('format') or '').lower().strip()
    format_hint = {'text/csv': 'csv', 'text/tab-separated-values': 'tsv',
                   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx'}.get(format_hint, format_hint)
    if format_hint not in ('csv', 'tsv', 'xlsx'):
        extension = Path(urlsplit(resource.get('url') or '').path).suffix.lower().lstrip('.')
        format_hint = extension if extension in ('csv', 'tsv', 'xlsx') else 'csv'
    if resource.get('url_type') == 'upload':
        location = _upload_location(resource)
        if location and not str(location).startswith(('http://', 'https://')):
            if not os.path.isfile(location):
                raise SourceError('The uploaded file is unavailable. Please upload it again.')
            return _copy_file(location, output), format_hint
        url = str(location or '')
    else:
        if not resource.get('url'):
            raise SourceError('This resource has no file URL. Add a file before creating a dashboard.')
        url = urljoin(tk.config.get('ckan.site_url', '').rstrip('/') + '/', resource['url'])
        internal = _csunesco_export(url, output, actor)
        if internal:
            return internal, 'csv'
    return download(url, output, setting('max_file_bytes'), validators,
                    timeout=setting('download_timeout')), format_hint


def build(resource_id, source, actor, expected_stamp, cache_key):
    from .engine import prepare_table
    resource, _ = authorize_resource(resource_id, actor)
    if resource_stamp(resource) != expected_stamp:
        raise SourceError('The resource changed during preparation. Refresh the dashboard.')
    directory = source_dir(cache_key)
    previous = current_generation(cache_key)
    if previous and previous[0].get('blocked') == 'cache_corrupt':
        previous = None
    old_manifest = previous[0] if previous else {}
    stage = Path(tempfile.mkdtemp(prefix='.building-', dir=directory))
    try:
        source_file = stage / 'source'
        metadata, hint = materialize(resource, source, source_file, actor, old_manifest.get('validators'))
        resource_now, _ = authorize_resource(resource_id, actor)
        if resource_stamp(resource_now) != expected_stamp:
            raise SourceError('The resource changed during preparation. Refresh the dashboard.')
        now = time.time()
        if previous and (metadata.get('unchanged') or metadata.get('sha256') == old_manifest.get('sha256')):
            old_manifest.pop('blocked', None)
            old_manifest['checked_at'] = now
            old_manifest['validators'] = {key: metadata.get(key) or old_manifest.get('validators', {}).get(key)
                                          for key in ('etag', 'last_modified')}
            atomic_json(directory / 'current.json', old_manifest)
            return {'status': 'ready', 'generation': old_manifest['generation']}
        # DataStore snapshots are generated here as UTF-8 comma-delimited CSV;
        # file-specific parsing choices must not corrupt that server-owned format.
        engine_source = dict(source, delimiter=',', encoding='utf-8') if source.get('kind') == 'datastore' else source
        profile = prepare_table(str(source_file), str(stage / 'table.duckdb'), source=engine_source,
                                format_hint=hint, limits={
                                    'max_rows': setting('max_rows'), 'max_columns': setting('max_columns'),
                                    'max_bytes': setting('max_file_bytes'),
                                    'memory_limit': setting('memory_limit'), 'threads': 2,
                                    'max_xlsx_uncompressed_bytes': setting('max_xlsx_uncompressed_bytes')})
        # A final access check covers long imports and permission revocations.
        fresh, _ = authorize_resource(resource_id, actor)
        if resource_stamp(fresh) != expected_stamp:
            raise SourceError('The resource changed during preparation. Refresh the dashboard.')
        source_file.unlink(missing_ok=True)
        generation = uuid.uuid4().hex
        updated_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))
        profile.setdefault('warnings', [])
        profile.setdefault('sheets', [])
        atomic_json(stage / 'profile.json', profile)
        os.chmod(stage / 'table.duckdb', 0o600)
        os.replace(stage, directory / generation)
        manifest = {'generation': generation, 'checked_at': now, 'updated_at': updated_at,
                    'sha256': metadata.get('sha256'), 'resource_id': resource_id,
                    'validators': {key: metadata.get(key) for key in ('etag', 'last_modified')}}
        atomic_json(directory / 'current.json', manifest)
        cleanup(directory, generation)
        return {'status': 'ready', 'generation': generation}
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def cleanup(directory=None, keep=None):
    """Remove idle caches after one day; active generations outlive query jobs."""
    cutoff = time.time() - 86400
    if directory:
        candidates = list(Path(directory).iterdir())
        for path in candidates:
            if path.name in (keep, 'current.json'):
                continue
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except FileNotFoundError:
                pass
        return
    for path in list(_root().iterdir()):
        try:
            if path.name == 'exports':
                for export in path.iterdir():
                    if export.stat().st_mtime < cutoff:
                        export.unlink(missing_ok=True)
            elif path.is_dir() and re.fullmatch('[a-f0-9]{64}', path.name):
                if path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    manifest = read_json(path / 'current.json') or {}
                    cleanup(path, manifest.get('generation'))
        except FileNotFoundError:
            pass
