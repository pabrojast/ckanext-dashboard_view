"""Flask boundary tests use real CSRF signatures and the real config schema."""
import importlib
import json
import sys
from types import ModuleType

import pytest
from flask import Flask, g, request
from flask_wtf.csrf import generate_csrf


@pytest.fixture
def web(monkeypatch):
    ckan = ModuleType('ckan')
    plugins = ModuleType('ckan.plugins')
    tk = ModuleType('ckan.plugins.toolkit')
    tk.NotAuthorized = type('NotAuthorized', (Exception,), {})
    tk.ObjectNotFound = type('ObjectNotFound', (Exception,), {})
    tk.config = {}
    tk._ = lambda value: value
    plugins.toolkit = tk
    ckan.plugins = plugins
    for name, module in [('ckan', ckan), ('ckan.plugins', plugins), ('ckan.plugins.toolkit', tk)]:
        monkeypatch.setitem(sys.modules, name, module)
    module = importlib.import_module('ckanext.dashboard_view.blueprint')
    monkeypatch.setattr(module, 'tk', tk)
    app = Flask(__name__)
    app.secret_key = 'test-only-secret'
    app.register_blueprint(module.blueprint)
    @app.before_request
    def actor():
        g.user = request.headers.get('X-Test-Actor', '')
        g.login_via_auth_header = request.headers.get('X-Test-API') == 'yes'
    @app.get('/token')
    def token():
        return generate_csrf()
    calls = []
    def authorize(resource_id, actor=None, edit=False):
        calls.append(('auth', resource_id, actor, edit))
        if resource_id == 'private' and actor != 'owner':
            raise tk.NotAuthorized()
        if edit and actor != 'owner':
            raise tk.NotAuthorized()
        return {'id': resource_id, 'package_id': 'p1'}, {'id': 'p1'}
    configuration = {'schema_version': 1, 'widgets': [{'id': 'w1', 'type': 'kpi', 'aggregate': 'count'}]}
    def view(view_id, resource_id, actor):
        calls.append(('view', view_id, resource_id, actor))
        if view_id != 'v1':
            raise tk.ObjectNotFound()
        return {'id': 'v1', 'resource_id': resource_id, 'dashboard_config': configuration}
    def prepare(resource, source, actor, force=False):
        calls.append(('prepare', resource['id'], actor, force))
        return {'status': 'ready', 'generation': 'generation1', 'rows': 10, 'fields': []}, 'key'
    def query(resource, source, config, actor, **kwargs):
        calls.append(('query', resource['id'], actor, kwargs))
        return {'status': 'ready', 'generation': 'generation1', 'rows': 10, 'results': {'w1': {'type': 'kpi', 'value': 10}}}
    monkeypatch.setattr(module, 'authorize_resource', authorize)
    monkeypatch.setattr(module, 'saved_view', view)
    monkeypatch.setattr(module.service, 'prepare', prepare)
    monkeypatch.setattr(module.service, 'run_query', query)
    return app.test_client(), module, calls, configuration


def test_anonymous_saved_query_is_allowed_without_csrf(web):
    client, _, calls, _ = web
    response = client.post('/dashboard-api/resource/r1/query', json={'view_id': 'v1'})
    assert response.status_code == 200
    assert response.json['results']['w1']['value'] == 10
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert calls[0] == ('auth', 'r1', '', False)


def test_private_cached_query_still_requires_access(web):
    client, _, calls, _ = web
    response = client.post('/dashboard-api/resource/private/query', json={'view_id': 'v1'})
    assert response.status_code == 403
    assert not any(call[0] == 'query' for call in calls)


def test_preview_requires_real_session_csrf(web):
    client, _, calls, config = web
    path = '/dashboard-api/resource/r1/query'
    response = client.post(path, headers={'X-Test-Actor': 'owner'}, json={'config': config})
    assert response.status_code == 403
    assert calls == []
    token = client.get('/token').get_data(as_text=True)
    response = client.post(path, headers={'X-Test-Actor': 'owner', 'X-CSRFToken': token}, json={'config': config})
    assert response.status_code == 200
    assert calls[0] == ('auth', 'r1', 'owner', True)


def test_source_with_view_id_is_preview_and_cannot_bypass_csrf(web):
    client, _, calls, _ = web
    response = client.post('/dashboard-api/resource/r1/profile',
                           json={'view_id': 'v1', 'source': {'kind': 'file'}})
    assert response.status_code == 403
    assert calls == []


def test_logged_in_saved_read_requires_csrf_or_api_auth(web):
    client, _, _, _ = web
    path = '/dashboard-api/resource/r1/query'
    response = client.post(path, headers={'X-Test-Actor': 'owner'}, json={'view_id': 'v1'})
    assert response.status_code == 403
    response = client.post(path, headers={'X-Test-Actor': 'owner', 'X-Test-API': 'yes'}, json={'view_id': 'v1'})
    assert response.status_code == 200


def test_refresh_requires_edit_permission_even_with_valid_csrf(web):
    client, _, calls, _ = web
    token = client.get('/token').get_data(as_text=True)
    response = client.post('/dashboard-api/resource/r1/refresh',
                           headers={'X-CSRFToken': token, 'X-Test-Actor': 'reader'}, json={'view_id': 'v1'})
    assert response.status_code == 403
    assert not any(call[0] == 'prepare' for call in calls)


def test_invalid_json_and_unbounded_body_fail_before_processing(web):
    client, _, calls, _ = web
    response = client.post('/dashboard-api/resource/r1/query', data='[1,2]', content_type='application/json')
    assert response.status_code == 400
    response = client.post('/dashboard-api/resource/r1/query', data='x' * 262145, content_type='application/json')
    assert response.status_code == 400
    assert not calls


def test_invalid_view_does_not_fall_back_to_arbitrary_config(web):
    client, _, calls, _ = web
    response = client.post('/dashboard-api/resource/r1/query', json={'view_id': 'missing'})
    assert response.status_code == 404
    assert not any(call[0] == 'query' for call in calls)
