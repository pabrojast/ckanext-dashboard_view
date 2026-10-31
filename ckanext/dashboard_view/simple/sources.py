"""Reauthorize durable sources, materialize safe snapshots, reuse table engine."""
import csv
import json
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit
from ..security import authorize_resource, download, SourceError
from .. import service
from ..engine import prepare_table, query_table
from .schema import ENGINE_VERSION
from . import identity


def trusted_url(url):
    import ckan.plugins.toolkit as tk
    prefixes = str(tk.config.get('ckanext.dashboard_view.simple_public_prefixes', '')).split()
    parsed = urlsplit(url)
    # Configured namespaces must end in a slash: lexical siblings cannot pass.
    if parsed.query or parsed.fragment or parsed.username or parsed.password or not any(
            p.endswith('/') and url.startswith(p) for p in prefixes):
        raise SourceError('This source must first be registered in IHP.', 'source_unavailable')
    return url


def authorize(source, actor='', public=False):
    if source.get('resource_id'):
        resource, package = authorize_resource(source['resource_id'], '' if public else actor)
        if public and package.get('private'):
            raise SourceError('All sources must be public before publishing.')
        return resource
    trusted_url(source['catalog_url'])
    return {'id': source['catalog_url'], 'url': source['catalog_url'], 'format': source['kind']}


def authorize_all(config, actor='', public=False):
    if actor and not identity.active_user(actor):
        raise PermissionError('This IHP account is no longer active.')
    resources = [authorize(s, actor, public) for s in config['sources']]
    for source in config['sources']:
        if source.get('analysis_resource_id'):
            authorize({'resource_id': source['analysis_resource_id']}, actor, public)
    return resources


def snapshot(url, directory):
    """Conditional validators + content hash; missing validators always download."""
    key = service.digest(['snapshot', url])
    root = service._root() / 'simple-sources'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    previous = service.read_json(root / (key + '.json')) or {}
    path = root / previous.get('sha256', 'missing')
    if path.is_file() and time.time() - previous.get('_checked_at', 0) < 300:
        return path, previous['sha256']
    validators = previous if path.is_file() else {}
    temporary = Path(directory) / key
    meta = download(url, temporary, service.setting('max_file_bytes'), validators)
    if not meta.get('unchanged'):
        path = root / meta['sha256']
        temporary.replace(path)
        service.atomic_json(root / (key + '.json'), meta)
    else:
        meta = previous
    meta['_checked_at'] = time.time()
    service.atomic_json(root / (key + '.json'), meta)
    return path, meta['sha256']


def json_snapshot(url, directory):
    path, version = snapshot(url, directory)
    with open(path, encoding='utf-8') as stream:
        return json.load(stream), version


def geojson_csv(path, output):
    with open(path, encoding='utf-8') as stream:
        data = json.load(stream)
    features = data.get('features', [])
    if data.get('type') != 'FeatureCollection' or len(features) > service.setting('max_rows'):
        raise SourceError('Use a bounded GeoJSON FeatureCollection.')
    names = list(dict.fromkeys(k for f in features for k in (f.get('properties') or {})))
    if len(names) > 498:
        raise SourceError('Too many GeoJSON properties.')
    names = [n for n in names if n not in ('_longitude', '_latitude')] + ['_longitude', '_latitude']
    with open(output, 'w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader()
        for feature in features:
            row = {k: v if isinstance(v, (str, int, float, bool)) else None
                   for k, v in (feature.get('properties') or {}).items()}
            geom = feature.get('geometry') or {}
            if geom.get('type') == 'Point':
                row.update(zip(names[-2:], geom['coordinates'][:2]))
            writer.writerow(row)


def tabular(source, resource, actor, directory):
    generation_root = service._root() / 'simple-tables'
    latest_key = service.digest([ENGINE_VERSION, source, service.resource_stamp(resource), actor])
    latest_path = generation_root / ('latest-' + latest_key + '.json')
    previous = service.read_json(latest_path) or {}
    previous_db = generation_root / previous.get('generation', 'missing') / 'table.duckdb'
    if previous_db.is_file() and time.time() - previous.get('checked_at', 0) < 300:
        return previous_db, previous['version'], service.read_json(previous_db.parent / 'profile.json')
    raw = Path(directory) / (source['id'] + '.raw')
    interpretation = dict(source['source'])
    if resource.get('datastore_active') and source['kind'] == 'table':
        interpretation['kind'] = 'datastore'
    meta, format_hint = service.materialize(resource, interpretation, raw, actor)
    version = meta['sha256']
    if source['kind'] == 'geojson':
        converted = raw.with_suffix('.csv')
        geojson_csv(raw, converted)
        raw, format_hint = converted, 'csv'
    key = service.digest(['simple-table', version, source['source'], ENGINE_VERSION])
    target = service._root() / 'simple-tables' / key
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    db = target / 'table.duckdb'
    if not db.exists():
        import tempfile
        import os
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            profile = prepare_table(raw, Path(tmp) / 'table.duckdb', source['source'], format_hint)
            if source['kind'] == 'geojson':
                shutil.copyfile(Path(directory) / (source['id'] + '.raw'), Path(tmp) / 'geometry.json')
            service.atomic_json(Path(tmp) / 'profile.json', profile)
            try:
                os.rename(tmp, target)
            except OSError:
                if not db.exists():
                    raise
    service.atomic_json(latest_path, {'generation': key, 'version': version, 'checked_at': time.time()})
    return db, version, service.read_json(target / 'profile.json')


def query_blocks(source, blocks, db, state):
    filters = list(source['filters'])
    profile = service.read_json(Path(db).parent / 'profile.json') or {}
    date_field = source.get('date_field') or next((f['key'] for f in profile.get('fields', []) if f['type'] == 'date'), None)
    if date_field:
        for key, op in [('start', 'gte'), ('end', 'lte')]:
            if state.get(key):
                filters.append({'field': date_field, 'op': op, 'value': state[key] + ('T23:59:59.999999' if key == 'end' else '')})
    from .spatial import table_selection
    selection, scope = table_selection(source, db, state, profile)
    result = query_table(db, {'widgets': blocks}, filters=filters, **selection)
    for value in result['results'].values():
        value['spatial_scope'] = scope
    warnings = list(result.get('warnings', []))
    if (state.get('start') or state.get('end')) and not date_field:
        warnings.append('This source has no date column; the shared date range was not applied.')
    return result['results'], warnings
