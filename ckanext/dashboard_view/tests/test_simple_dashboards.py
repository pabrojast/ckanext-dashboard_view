"""Native dashboards: private drafts, published revisions, cache and calculations."""
import copy
import importlib
import json
import sys
from types import ModuleType

import pytest
import sqlalchemy as sa
from flask import Flask, g, request
from ckanext.dashboard_view.simple import store, schema, access, sources, jobs, calculations
from ckanext.dashboard_view import service

RESOURCE = '12345678-1234-1234-1234-123456789012'


def config(**patch):
    value = {'title': 'Water', 'sources': [{'id': 's', 'name': 'Data', 'kind': 'table', 'resource_id': RESOURCE}],
             'blocks': [{'id': 'b', 'source_id': 's', 'type': 'kpi', 'aggregate': 'avg', 'y_field': 'value'}]}
    value.update(patch)
    return schema.normalize(value)


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'dashboards.db'))
    store.init_db(engine)
    monkeypatch.setattr(store, 'engine', lambda: engine)
    monkeypatch.setattr(access, 'owner', lambda item, actor: actor == item['owner'] or actor == 'admin')
    monkeypatch.setattr(sources, 'authorize_all', lambda *args, **kw: [{'id': RESOURCE, 'url': 'https://example.org/a.csv'}])
    return engine


def test_private_default_and_explicit_published_revision(db):
    first = store.save(config(), 'reader')
    with pytest.raises(PermissionError):
        access.read(first['id'])
    store.visibility(first['id'], 1, True)
    second = store.save(config(title='Private draft'), 'reader', first['id'], 1)
    assert second['revision'] == 2
    assert access.read(first['id'])['config']['title'] == 'Water'
    with pytest.raises(PermissionError):
        access.read(first['id'], revision=2)
    assert access.read(first['id'], 'reader', 1)['config']['title'] == 'Water'
    store.visibility(first['id'], 2, True)
    assert access.read(first['id'], revision=1)['published']
    store.visibility(first['id'], 2, False)
    with pytest.raises(PermissionError):
        access.read(first['id'], revision=1)


def test_owner_sysadmin_and_optimistic_concurrency(db):
    item = store.save(config(), 'reader')
    with pytest.raises(PermissionError):
        access.edit(item['id'], 'someone')
    assert access.edit(item['id'], 'admin')
    store.save(config(title='Second'), 'reader', item['id'], 1)
    with pytest.raises(ValueError, match='changed'):
        store.save(config(title='Lost edit'), 'reader', item['id'], 1)
    assert store.get(item['id'], 1)['config']['title'] == 'Water'


def test_access_revocation_blocks_cached_public_revision(db, monkeypatch):
    item = store.save(config(), 'reader')
    store.visibility(item['id'], 1, True)
    store.put('cached', {'value': 123})
    def revoked(*args, **kwargs):
        raise PermissionError('source revoked')
    monkeypatch.setattr(sources, 'authorize_all', revoked)
    with pytest.raises(PermissionError):
        access.read(item['id'])


def test_results_survive_database_reopen(db, monkeypatch):
    store.put('key', {'results': {'b': {'value': 8}}})
    url = str(db.url)
    db.dispose()
    monkeypatch.setattr(store, 'engine', lambda: sa.create_engine(url))
    assert store.cached('key')[0]['results']['b']['value'] == 8


@pytest.mark.parametrize('patch', [
    {'blocks': [{'id': str(i), 'source_id': 's', 'type': 'kpi'} for i in range(7)]},
    {'sources': [{'id': 's', 'name': 'Local file', 'kind': 'table'}]},
    {'blocks': [{'id': 'b', 'source_id': 'missing', 'type': 'kpi'}]},
    {'blocks': [{'id': 'b', 'source_id': 's', 'type': 'scatter'}]},
    {'state': {'start': '2025-02-01', 'end': '2024-01-01'}},
    {'state': {'area': {'type': 'Point', 'coordinates': [181, 0]}}},
    {'state': {'area': {'type': 'Polygon', 'coordinates': None}}},
])
def test_schema_rejects_unsupported_or_unbounded_configuration(patch):
    with pytest.raises((ValueError, TypeError)):
        config(**patch)


def test_schema_discards_client_results_and_expressions():
    normalized = config(results={'b': 999}, sql='DROP TABLE data')
    assert 'results' not in normalized and 'sql' not in normalized


def test_missing_values_remain_gaps_and_kpi_uses_valid_count():
    points = [{'date': '2024-01', 'value': 4}, {'date': '2024-02', 'value': None}, {'date': '2024-03', 'value': 8}]
    block = config()['blocks'][0]
    assert calculations.result_from_points(block, points)['value'] == 6
    assert calculations.result_from_points(dict(block, type='line'), points)['datasets'][0]['data'] == [4, None, 8]


def test_content_change_only_recomputes_affected_block(db, monkeypatch, tmp_path):
    from ckanext.dashboard_view.engine import prepare_table
    raw = tmp_path / 'sample.csv'; raw.write_text('value,date\n1,2024-01-01\n3,2024-02-01\n')
    path = tmp_path / 'table.duckdb'; profile = prepare_table(raw, path)
    version = ['v1']; calls = []
    monkeypatch.setattr(sources, 'tabular', lambda *args: (path, version[0], profile))
    original = sources.query_blocks
    def counted(*args):
        calls.append(args[1][0]['id'])
        return original(*args)
    monkeypatch.setattr(sources, 'query_blocks', counted)
    cfg = config()
    first = calculations.calculate(cfg, 'reader', str(tmp_path))
    assert first['results']['b']['value'] == 2
    calculations.calculate(cfg, 'reader', str(tmp_path))
    assert calls == ['b']
    cfg['blocks'].append(dict(cfg['blocks'][0], id='c', aggregate='max'))
    calculations.calculate(cfg, 'reader', str(tmp_path))
    assert calls == ['b', 'c']
    version[0] = 'v2'
    calculations.calculate(cfg, 'reader', str(tmp_path))
    assert calls == ['b', 'c', 'b', 'c']


@pytest.fixture
def web(db, monkeypatch):
    ckan, plugins, tk = ModuleType('ckan'), ModuleType('ckan.plugins'), ModuleType('ckan.plugins.toolkit')
    tk.config = {'ckanext.dashboard_view.simple_enabled': True}
    tk.asbool = bool; tk._ = str
    tk.NotAuthorized = type('NotAuthorized', (Exception,), {})
    tk.ObjectNotFound = type('ObjectNotFound', (Exception,), {})
    ckan.plugins = plugins; plugins.toolkit = tk
    for name, value in [('ckan', ckan), ('ckan.plugins', plugins), ('ckan.plugins.toolkit', tk)]:
        monkeypatch.setitem(sys.modules, name, value)
    legacy = importlib.import_module('ckanext.dashboard_view.blueprint')
    monkeypatch.setattr(legacy, 'tk', tk)
    api = importlib.import_module('ckanext.dashboard_view.simple.api')
    monkeypatch.setattr(api, 'tk', tk)
    app = Flask(__name__); app.secret_key = 'test-only'
    app.register_blueprint(api.blueprint)
    @app.before_request
    def user():
        g.user = request.headers.get('X-Test-Actor', '')
    client = app.test_client()
    token = client.get('/api/simple-dashboards/config').json['csrf_token']
    return client, {'X-Test-Actor': 'reader', 'X-CSRFToken': token}


def test_api_login_csrf_and_read_only_source_creator(web):
    client, headers = web
    path = '/api/simple-dashboards'
    assert client.post(path, json={'config': config()}).status_code == 403
    assert client.post(path, json={'config': config()}, headers={'X-Test-Actor': 'reader'}).status_code == 403
    response = client.post(path, json={'config': config()}, headers=headers)
    assert response.status_code == 201
    assert response.json['published_revision'] is None
    assert client.get(path + '/' + response.json['id']).status_code == 403
    assert response.headers['Cache-Control'] == 'private, no-store'
    saved = client.post(path + '/' + response.json['id'], json={'config': config(title='Updated'), 'revision': 1}, headers=headers)
    assert saved.status_code == 200 and saved.json['revision'] == 2


def test_api_publish_duplicate_delete_and_no_other_owner_edit(web):
    client, headers = web
    base = '/api/simple-dashboards'
    item = client.post(base, json={'config': config()}, headers=headers).json
    path = base + '/' + item['id']
    assert client.post(path + '/publish', json={'revision': 1, 'publish': True}, headers=headers).status_code == 200
    assert client.get(path).status_code == 200
    other = dict(headers, **{'X-Test-Actor': 'other'})
    assert client.post(path, json={'config': config(), 'revision': 1}, headers=other).status_code == 403
    duplicate = client.post(path + '/duplicate', json={'revision': 1}, headers=other)
    assert duplicate.status_code == 201 and duplicate.json['published_revision'] is None
    assert client.delete(path, json={}, headers=headers).status_code == 200
    assert client.get(path).status_code == 404


def test_concurrent_requests_enqueue_once_and_reuse_persistent_result(db, monkeypatch):
    import fakeredis
    redis = fakeredis.FakeRedis()
    monkeypatch.setattr(service, 'redis_connection', lambda: redis)
    queue = ModuleType('ckan.lib.jobs'); queued = []
    queue.enqueue = lambda *args, **kwargs: queued.append(kwargs)
    monkeypatch.setitem(sys.modules, 'ckan.lib.jobs', queue)
    cfg = config()
    assert jobs.query(cfg, 'reader')['status'] == 'pending'
    assert jobs.query(cfg, 'reader')['status'] == 'pending'
    assert len(queued) == 1
    kwargs = queued[0]['kwargs']
    monkeypatch.setattr(calculations, 'calculate', lambda *args: {'results': {'b': {'value': 2}}})
    jobs.execute(**kwargs)
    assert jobs.query(cfg, 'reader')['results']['b']['value'] == 2
    assert len(queued) == 1


def test_only_transient_failure_retains_valid_values(db, monkeypatch):
    import fakeredis
    redis = fakeredis.FakeRedis(); monkeypatch.setattr(service, 'redis_connection', lambda: redis)
    from ckanext.dashboard_view.security import SourceError
    for transient in (True, False):
        store.put('key', {'results': {'b': {'value': 7}}})
        redis.set('simple-dashboard:lock:key', 'claim')
        def fail(*args):
            raise SourceError('Unavailable', 'source_temporarily_unavailable' if transient else 'source_unavailable')
        monkeypatch.setattr(calculations, 'calculate', fail)
        jobs.execute('key', config(), 'reader', 'claim')
        cached, _ = store.cached('key')
        assert bool(cached.get('results')) == transient
        assert cached['error'] == 'Unavailable'


def test_table_export_has_consistent_columns_and_escapes_formulas(web, monkeypatch):
    import csv
    import io
    client, headers = web
    cfg = config(blocks=[{'id':'b','source_id':'s','type':'table','title':'Table'}])
    item = client.post('/api/simple-dashboards', json={'config': cfg}, headers=headers).json
    monkeypatch.setattr(jobs, 'query', lambda *args: {'status':'ready','calculated_at':123,
        'results':{'b':{'type':'table','columns':[{'key':'name','label':'Name'},{'key':'value','label':'Value'}],
                        'rows':[{'name':'=CMD()', 'value':4}]}}})
    response = client.post('/api/simple-dashboards/'+item['id']+'/export', json={'revision':1}, headers=headers)
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.text)))
    assert all(len(row) == 7 for row in rows)
    assert rows[1][3].startswith("'") and rows[2][3] == '4'
