"""Cache atomicity, freshness, authorization and disk restart behavior."""
import json
from pathlib import Path
import sys
import time
from types import ModuleType

import pytest

from ckanext.dashboard_view import service
from ckanext.dashboard_view.security import SourceError


@pytest.fixture
def cache(monkeypatch, tmp_path):
    values = dict(service.DEFAULTS, cache_dir=str(tmp_path))
    monkeypatch.setattr(service, 'setting', values.__getitem__)
    monkeypatch.setattr(service, 'redis_key', lambda kind, key: '%s:%s' % (kind, key))
    return values


def seed(key, checked_at=None, generation='a' * 32):
    directory = service.source_dir(key)
    old = directory / generation
    old.mkdir(exist_ok=True)
    (old / 'table.duckdb').write_bytes(b'test')
    service.atomic_json(old / 'profile.json', {'rows': 2, 'fields': [{'key': 'value', 'type': 'number'}]})
    service.atomic_json(directory / 'current.json', {
        'generation': generation, 'checked_at': checked_at or time.time(),
        'updated_at': '2026-09-09T12:00:00Z', 'sha256': 'same', 'validators': {'etag': 'one'},
    })
    return old


def test_interrupted_publication_keeps_previous_generation(cache):
    key = 'c' * 64
    seed(key)
    pending = service.source_dir(key) / ('.building-' + 'd' * 32)
    pending.mkdir()
    (pending / 'table.duckdb').write_bytes(b'incomplete')
    manifest, profile, path = service.current_generation(key)
    assert manifest['generation'] == 'a' * 32
    assert profile['rows'] == 2
    assert path.name == 'a' * 32


def test_lost_disk_generation_is_not_ready(cache):
    key = 'c' * 64
    path = seed(key)
    (path / 'table.duckdb').unlink()
    assert service.current_generation(key) is None


def test_resource_change_invalidates_cache_identity(cache):
    source = {'kind': 'file'}
    original = {'id': 'r1', 'url': 'https://example.com/data.csv', 'last_modified': 'first'}
    updated = dict(original, last_modified='second')
    assert service.source_key(original, source) != service.source_key(updated, source)


def test_unchanged_remote_revalidation_retains_generation(cache, monkeypatch):
    resource = {'id': 'r1', 'url': 'https://example.com/data.csv'}
    source = {'kind': 'file'}
    key = service.source_key(resource, source)
    seed(key, checked_at=1)
    monkeypatch.setattr(service, 'authorize_resource', lambda *args: (resource, {}))
    monkeypatch.setattr(service, 'materialize', lambda *args: ({'unchanged': True, 'etag': 'one'}, 'csv'))
    result = service.build('r1', source, 'editor', service.resource_stamp(resource), key)
    assert result['generation'] == 'a' * 32
    manifest, _, _ = service.current_generation(key)
    assert manifest['checked_at'] > time.time() - 5
    assert manifest['updated_at'] == '2026-09-09T12:00:00Z'


def test_permission_revocation_during_fetch_does_not_publish(cache, monkeypatch):
    resource = {'id': 'r1', 'url': 'https://example.com/data.csv'}
    source = {'kind': 'file'}
    key = service.source_key(resource, source)
    seed(key)
    checks = []
    def authorize(*args):
        checks.append(args)
        if len(checks) > 1:
            raise PermissionError('revoked')
        return resource, {}
    monkeypatch.setattr(service, 'authorize_resource', authorize)
    monkeypatch.setattr(service, 'materialize', lambda *args: ({'sha256': 'new'}, 'csv'))
    with pytest.raises(PermissionError, match='revoked'):
        service.build('r1', source, 'editor', service.resource_stamp(resource), key)
    assert service.current_generation(key)[0]['generation'] == 'a' * 32
    assert not list(service.source_dir(key).glob('.building-*'))


def test_local_file_is_streamed_and_bounded(cache, tmp_path):
    source, output = tmp_path / 'source.csv', tmp_path / 'output.csv'
    source.write_bytes(b'a,b\n1,2\n')
    cache['max_file_bytes'] = 4
    with pytest.raises(SourceError, match='size limit'):
        service._copy_file(source, output)
    assert not output.exists()


def test_cache_identifiers_cannot_escape_directory(cache):
    for key in ('../../etc', '/tmp/file', 'a' * 63, 'Z' * 64):
        with pytest.raises(ValueError):
            service.source_dir(key)
    with pytest.raises(ValueError):
        service.export_path('../../etc/passwd')


class Redis:
    def __init__(self):
        self.data = {}
    def get(self, key):
        return self.data.get(key)
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True
    def setex(self, key, ttl, value):
        self.data[key] = value
    def delete(self, key):
        self.data.pop(key, None)
    def eval(self, script, number, lock, state, claim, ttl, data):
        if self.get(lock) == claim:
            self.setex(state, ttl, data)
            self.delete(lock)
            return 1
        return 0


@pytest.fixture
def queue(cache, monkeypatch):
    ckan = ModuleType('ckan')
    lib = ModuleType('ckan.lib')
    jobs = ModuleType('ckan.lib.jobs')
    calls = []
    # Match CKAN's actual signature so unsupported RQ kwargs cannot sneak in.
    def enqueue(fn, args=None, kwargs=None, title=None, queue='default', rq_kwargs=None):
        calls.append({'fn': fn, 'kwargs': kwargs, 'queue': queue, 'rq_kwargs': rq_kwargs})
    jobs.enqueue = enqueue
    lib.jobs = jobs
    ckan.lib = lib
    for name, module in [('ckan', ckan), ('ckan.lib', lib), ('ckan.lib.jobs', jobs)]:
        monkeypatch.setitem(sys.modules, name, module)
    redis = Redis()
    monkeypatch.setattr(service, 'redis_connection', lambda: redis)
    return calls, redis


def test_concurrent_preparations_enqueue_once_with_ckan_rq_contract(queue):
    calls, redis = queue
    one = service._enqueue('build', 'source-key', {'resource_id': 'r1', 'actor': 'owner'})
    two = service._enqueue('build', 'source-key', {'resource_id': 'r1', 'actor': 'owner'})
    assert one == two
    assert len(calls) == 1
    assert calls[0]['queue'] == 'dashboard-build'
    assert calls[0]['rq_kwargs']['timeout'] == 900
    assert 'claim' in calls[0]['kwargs']


def test_old_claim_cannot_publish_over_new_job(queue):
    _, redis = queue
    redis.set('lock:key', 'new-claim')
    redis.set('state:key', json.dumps({'status': 'pending'}))
    service.finish_work('key', 'old-claim', {'status': 'ready'})
    assert redis.get('lock:key') == 'new-claim'
    assert json.loads(redis.get('state:key'))['status'] == 'pending'


def test_failed_queue_is_retryable_and_releases_claim(queue, monkeypatch):
    calls, redis = queue
    import ckan.lib.jobs
    def unavailable(*args, **kwargs):
        raise ConnectionError('Redis backend is unavailable')
    monkeypatch.setattr(ckan.lib.jobs, 'enqueue', unavailable)
    result = service._enqueue('query', 'key', {'resource_id': 'r1'})
    assert result['code'] == 'queue_unavailable'
    assert redis.get('lock:key') is None
    assert 'Redis' not in result['message']


def test_worker_timeout_becomes_actionable_error_instead_of_infinite_pending(queue, monkeypatch):
    _, redis = queue
    import ckan.lib.jobs
    class FailedJob:
        def get_status(self):
            return 'failed'
    monkeypatch.setattr(ckan.lib.jobs, 'job_from_id', lambda job_id: FailedJob(), raising=False)
    redis.set('lock:key', 'claim')
    redis.set('state:key', json.dumps({'status': 'pending', 'job_id': 'claim', 'queued_at': time.time() - 30}))
    state = service._load_state('key')
    assert state['status'] == 'error'
    assert state['code'] == 'job_interrupted'
    assert redis.get('lock:key') is None


def test_datastore_snapshot_ignores_previous_file_delimiter_and_encoding(cache, monkeypatch):
    resource = {'id': 'r1', 'url': 'datastore', 'datastore_active': True}
    source = {'kind': 'datastore', 'delimiter': ';', 'encoding': 'cp1252'}
    key = service.source_key(resource, source)
    monkeypatch.setattr(service, 'authorize_resource', lambda *args: (resource, {}))
    def materialize(resource, source, output, actor, validators):
        output.write_text('city,value\nÑuble,2\n', encoding='utf-8')
        return {'sha256': 'new-data', 'unchanged': False}, 'csv'
    monkeypatch.setattr(service, 'materialize', materialize)
    service.build('r1', source, 'owner', service.resource_stamp(resource), key)
    manifest, profile, path = service.current_generation(key)
    assert profile['rows'] == 1
    assert len(profile['fields']) == 2
    from ckanext.dashboard_view.engine import query_table
    result = query_table(str(path / 'table.duckdb'), {'widgets': [{'id': 'w1', 'type': 'table'}]})
    assert result['results']['w1']['rows'][0]['city'] == 'Ñuble'


def test_stale_profile_remains_available_while_revalidating(queue):
    from ckanext.dashboard_view.schema import normalize_source
    calls, _ = queue
    resource = {'id': 'r1', 'url': 'https://example.com/data.csv'}
    source = normalize_source({'kind': 'file'})
    key = service.source_key(resource, source)
    seed(key, checked_at=1)
    result, _ = service.prepare(resource, source, 'owner')
    assert result['status'] == 'ready'
    assert result['refreshing'] is True
    assert result['updated_at'] == '2026-09-09T12:00:00Z'
    assert len(calls) == 1


def test_withdrawn_source_stays_blocked_after_redis_error_expires(queue):
    from ckanext.dashboard_view.schema import normalize_source
    calls, redis = queue
    resource = {'id': 'r1', 'url': 'https://example.com/data.csv'}
    source = normalize_source({'kind': 'file'})
    key = service.source_key(resource, source)
    seed(key)
    service.invalidate_generation(key, 'source_unavailable')
    # There is deliberately no Redis error: an expired transient message cannot
    # make previously withheld source data readable again.
    result, _ = service.prepare(resource, source, 'owner')
    assert result['status'] == 'pending'
    assert 'fields' not in result
    assert len(calls) == 1


def test_corrupt_cache_rebuilds_instead_of_accepting_304(cache, monkeypatch):
    resource = {'id': 'r1', 'url': 'https://example.com/data.csv'}
    source = {'kind': 'file'}
    key = service.source_key(resource, source)
    seed(key)
    service.invalidate_generation(key, 'cache_corrupt')
    monkeypatch.setattr(service, 'authorize_resource', lambda *args: (resource, {}))
    validators_seen = []
    def materialize(resource, source, output, actor, validators):
        validators_seen.append(validators)
        output.write_text('a,b\n1,2\n', encoding='utf-8')
        return {'sha256': 'same', 'unchanged': False}, 'csv'
    monkeypatch.setattr(service, 'materialize', materialize)
    service.build('r1', source, 'owner', service.resource_stamp(resource), key)
    assert validators_seen == [None]
    manifest, profile, path = service.current_generation(key)
    assert manifest['generation'] != 'a' * 32
    assert 'blocked' not in manifest
    assert profile['rows'] == 1


def test_cloud_uploader_receives_plain_filename_and_keeps_signed_url_server_side(monkeypatch):
    uploader_module = ModuleType('ckan.lib.uploader')
    seen = []
    class CloudUploader:
        def get_url_from_filename(self, resource_id, filename):
            seen.append((resource_id, filename))
            return 'https://storage.example.com/file.csv?sig=test-only'
        def get_path(self, resource_id):
            raise AssertionError('Signer should handle this uploader')
    uploader_module.get_resource_uploader = lambda resource: CloudUploader()
    monkeypatch.setitem(sys.modules, 'ckan.lib.uploader', uploader_module)
    location = service._upload_location({'id': 'r1', 'url': 'https://storage.example.com/French%20data.csv?old=signature'})
    assert seen == [('r1', 'French data.csv')]
    assert location == 'https://storage.example.com/file.csv?sig=test-only'


def test_standard_uploader_uses_local_storage_path(monkeypatch):
    uploader_module = ModuleType('ckan.lib.uploader')
    class LocalUploader:
        def get_path(self, resource_id):
            return '/private/storage/file.csv'
    uploader_module.get_resource_uploader = lambda resource: LocalUploader()
    monkeypatch.setitem(sys.modules, 'ckan.lib.uploader', uploader_module)
    assert service._upload_location({'id': 'r1', 'url': 'file.csv'}) == '/private/storage/file.csv'
