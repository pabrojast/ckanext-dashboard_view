"""Authorization and download boundaries that do not require a CKAN server."""
import socket
from types import ModuleType
import sys

import pytest

from ckanext.dashboard_view import security


def dns(addresses):
    return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '',
             (address, 443, 0, 0) if ':' in address else (address, 443)) for address in addresses]


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'http://localhost/a.csv', 'http://127.0.0.1/a.csv',
    'http://169.254.169.254/latest/meta-data', 'http://10.0.0.2/a.csv',
    'https://[::1]/a.csv', 'https://[::ffff:127.0.0.1]/a.csv',
    'https://user:pass@example.com/a.csv', 'https://example.com:8443/a.csv',
    'https://example.com/a.csv#secret', 'https://example.com/\r\nX: bad',
])
def test_non_public_urls_are_rejected(monkeypatch, url):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['127.0.0.1']))
    with pytest.raises(security.SourceError):
        security.public_destination(url)


def test_mixed_dns_answer_rejected(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['8.8.8.8', '10.1.2.3']))
    with pytest.raises(security.SourceError, match='public internet'):
        security.public_destination('https://example.com/a.csv')


def test_dns_resolution_is_pinned(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['8.8.8.8']))
    _, host, port, address = security.public_destination('https://example.com/a.csv')
    calls = []
    sock = object()
    monkeypatch.setattr(socket, 'create_connection', lambda dest, timeout: calls.append(dest) or sock)
    class Context:
        verify_mode = security.ssl.CERT_REQUIRED
        check_hostname = True
        def wrap_socket(self, connection, server_hostname):
            calls.append(server_hostname)
            return connection
    monkeypatch.setattr(security.ssl, 'create_default_context', Context)
    connection = security._PinnedHTTPS(host, port, address, 10)
    connection.connect()
    assert calls == [('8.8.8.8', 443), 'example.com']


class Response:
    def __init__(self, status, chunks=(), headers=None):
        self.status = status
        self.chunks = iter(chunks)
        self.headers = headers or {}
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read(self, limit):
        return next(self.chunks, b'')


def fake_http(monkeypatch, responses):
    seen = []
    sequence = iter(responses)
    class Connection:
        sock = None
        def __init__(self, host, port, address, timeout):
            seen.append((host, address))
        def request(self, method, target, headers):
            seen.append(headers)
        def getresponse(self):
            return next(sequence)
        def close(self):
            pass
    monkeypatch.setattr(security, '_PinnedHTTPS', Connection)
    return seen


def test_redirect_is_revalidated_and_never_receives_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *a, **k: dns(['127.0.0.1' if host == 'internal.example' else '8.8.8.8']))
    seen = fake_http(monkeypatch, [Response(302, headers={'Location': 'https://internal.example/admin'})])
    with pytest.raises(security.SourceError, match='public internet'):
        security.download('https://example.com/a.csv', tmp_path / 'file', 1024)
    assert seen[0] == ('example.com', '8.8.8.8')
    assert 'Cookie' not in seen[1] and 'Authorization' not in seen[1]
    assert len(seen) == 2


def test_chunked_response_size_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['8.8.8.8']))
    fake_http(monkeypatch, [Response(200, [b'a,b\n', b'123,456\n'])])
    with pytest.raises(security.SourceError, match='size limit'):
        security.download('https://example.com/a.csv', tmp_path / 'file', 6)
    assert (tmp_path / 'file').stat().st_size <= 6


def test_304_does_not_write_source(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['8.8.8.8']))
    seen = fake_http(monkeypatch, [Response(304, headers={'ETag': 'v1'})])
    result = security.download('https://example.com/a.csv', tmp_path / 'file', 100, {'etag': 'v1'})
    assert result['unchanged']
    assert seen[1]['If-None-Match'] == 'v1'
    assert not (tmp_path / 'file').exists()


@pytest.fixture
def toolkit(monkeypatch):
    ckan = ModuleType('ckan')
    plugins = ModuleType('ckan.plugins')
    tk = ModuleType('ckan.plugins.toolkit')
    class NotAuthorized(Exception):
        pass
    tk.NotAuthorized = NotAuthorized
    tk.ObjectNotFound = type('ObjectNotFound', (Exception,), {})
    plugins.toolkit = tk
    ckan.plugins = plugins
    authz = ModuleType('ckan.authz')
    authz.auth_functions_list = lambda: ['resource_show', 'datashare_resource_download']
    ckan.authz = authz
    tk._test_authz = authz
    monkeypatch.setitem(sys.modules, 'ckan.authz', authz)
    for name, module in [('ckan', ckan), ('ckan.plugins', plugins), ('ckan.plugins.toolkit', tk)]:
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(security, 'context_for', lambda actor: {'user': actor})
    tk.get_action = lambda name: lambda context, data: ({'id': 'r1', 'package_id': 'p1'} if name == 'resource_show' else {'id': 'p1'})
    return tk


def test_download_denial_never_falls_back_to_preview_permission(toolkit):
    calls = []
    def check(name, context, data):
        calls.append(name)
        raise toolkit.NotAuthorized()
    toolkit.check_access = check
    with pytest.raises(toolkit.NotAuthorized):
        security.authorize_resource('r1', 'reader')
    assert calls == ['datashare_resource_download']


def test_missing_datashare_auth_falls_back_to_ckan(toolkit):
    calls = []
    def check(name, context, data):
        calls.append((name, context['user']))
        if name == 'datashare_resource_download':
            raise ValueError('Authorization function not found: datashare_resource_download')
    toolkit.check_access = check
    toolkit._test_authz.auth_functions_list = lambda: ['resource_show']
    security.authorize_resource('r1', 'editor', edit=True)
    assert calls == [('resource_show', 'editor'), ('resource_update', 'editor')]


def test_unexpected_auth_failure_is_closed(toolkit):
    toolkit.check_access = lambda *args: (_ for _ in ()).throw(ValueError('Malformed access policy'))
    with pytest.raises(ValueError, match='Malformed'):
        security.authorize_resource('r1', 'reader')


def test_truncated_http_response_never_publishes_partial_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['8.8.8.8']))
    fake_http(monkeypatch, [Response(200, [b'a,b\n1,2\n'], headers={'Content-Length': '100'})])
    with pytest.raises(security.SourceError, match='incomplete') as error:
        security.download('https://example.com/a.csv', tmp_path / 'file', 1024)
    assert error.value.code == 'source_temporarily_unavailable'


@pytest.mark.parametrize('status,code', [(401, 'source_unavailable'), (403, 'source_unavailable'),
                                         (404, 'source_unavailable'), (503, 'source_temporarily_unavailable')])
def test_download_distinguishes_withdrawn_source_from_temporary_failure(monkeypatch, tmp_path, status, code):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns(['8.8.8.8']))
    fake_http(monkeypatch, [Response(status)])
    with pytest.raises(security.SourceError) as error:
        security.download('https://example.com/a.csv', tmp_path / 'file', 1024)
    assert error.value.code == code


def test_cs_source_approval_is_checked_on_every_resource_authorization(toolkit):
    toolkit.config = {'ckan.site_url': 'https://data.example.com'}
    toolkit.check_access = lambda *args: True
    approval = {'status': 'approved', 'form_id': 42}
    calls = []
    def action(name):
        def invoke(context, data):
            calls.append(name)
            if name == 'resource_show':
                return {'id': 'r1', 'package_id': 'p1', 'url': 'https://data.example.com/citizen-science/data/source1.csv'}
            if name == 'package_show':
                return {'id': 'p1'}
            return approval
        return invoke
    toolkit.get_action = action
    security.authorize_resource('r1', 'reader')
    approval['status'] = 'rejected'
    with pytest.raises(security.SourceError, match='not approved'):
        security.authorize_resource('r1', 'reader')
    assert calls.count('csunesco_data_source_show') == 2
