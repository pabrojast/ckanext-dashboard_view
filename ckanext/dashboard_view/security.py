"""Authorization and bounded, DNS-pinned resource downloads.

Only CKAN's stored resource URL is ever accepted. Credentials never leave CKAN.
"""
import hashlib
import http.client
import ipaddress
import socket
import re
import ssl
import time
from urllib.parse import urljoin, urlsplit


class SourceError(ValueError):
    """An actionable error safe to return to a dashboard user."""
    def __init__(self, message, code="invalid_data"):
        super().__init__(message)
        self.code = code


def context_for(actor=None):
    import ckan.model as model
    # Workers can hold ORM identities across a long import. Refresh clean
    # sessions so later access checks see revoked roles and changed privacy.
    # Never discard another CKAN action's pending edits during form rendering.
    if not (model.Session.new or model.Session.dirty or model.Session.deleted):
        model.Session.expire_all()
    return {'model': model, 'session': model.Session, 'user': actor or ''}


def authorize_resource(resource_id, actor=None, edit=False):
    import ckan.plugins.toolkit as tk
    context = context_for(actor)
    resource = tk.get_action('resource_show')(dict(context), {'id': resource_id})
    package = tk.get_action('package_show')(dict(context), {'id': resource['package_id']})
    # A fresh context prevents CKAN's cached auth result from one action being
    # treated as the result of a different action.
    from ckan.authz import auth_functions_list
    download_auth = ('datashare_resource_download'
                     if 'datashare_resource_download' in auth_functions_list() else 'resource_show')
    tk.check_access(download_auth, dict(context), {'id': resource_id})
    if edit:
        tk.check_access('resource_update', dict(context), {'id': resource_id})
    linked_cs_source(resource, actor)
    return resource, package


def linked_cs_source(resource, actor=None):
    """Recheck approval for known same-site CS exports even on a cache hit."""
    import ckan.plugins.toolkit as tk
    if resource.get('url_type') == 'upload' or not resource.get('url'):
        return None
    site_url = tk.config.get('ckan.site_url', '')
    site = urlsplit(site_url)
    parsed = urlsplit(urljoin(site_url.rstrip('/') + '/', resource['url']))
    if (parsed.scheme, parsed.netloc) != (site.scheme, site.netloc):
        return None
    match = re.fullmatch(re.escape(site.path.rstrip('/')) +
                         r'(?:/[a-z]{2}(?:_[A-Z]{2})?)?/citizen-science/data/([a-zA-Z0-9-]+)\.csv', parsed.path)
    if not match or parsed.query or parsed.fragment:
        return None
    try:
        action = tk.get_action('csunesco_data_source_show')
    except KeyError:
        raise SourceError('This citizen science source is no longer available.', 'source_unavailable') from None
    source = action(context_for(actor), {'id': match.group(1)})
    if source.get('status') != 'approved':
        raise SourceError('This citizen science source is not approved for publication.', 'source_unavailable')
    return source


def may_edit(resource_id, actor=None):
    try:
        authorize_resource(resource_id, actor, edit=True)
        return True
    except Exception:
        return False


def saved_view(view_id, resource_id=None, actor=None):
    import ckan.plugins.toolkit as tk
    view = tk.get_action('resource_view_show')(context_for(actor), {'id': view_id})
    if view.get('view_type') != 'dashboard_view' or (
        resource_id and view.get('resource_id') != resource_id
    ):
        raise tk.ObjectNotFound('Dashboard not found')
    authorize_resource(view['resource_id'], actor)
    return view


def public_destination(url):
    """Validate every resolved address; return an address to pin the socket to."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise SourceError('The resource must use an HTTP or HTTPS URL.')
        if parsed.username or parsed.password or parsed.fragment:
            raise SourceError('Resource URLs cannot contain credentials or fragments.')
        if any(ord(char) < 32 or ord(char) == 127 for char in url):
            raise SourceError('The resource URL contains invalid characters.')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port not in (80, 443):
            raise SourceError('Resource URLs must use standard HTTP or HTTPS ports.')
        hostname = parsed.hostname.encode('idna').decode('ascii')
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        ips = sorted({row[4][0] for row in addresses})
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise SourceError('The resource URL must resolve to a public internet address.')
        return parsed, hostname, port, ips[0]
    except (ValueError, OSError, UnicodeError) as exc:
        if isinstance(exc, SourceError):
            raise
        raise SourceError('The resource URL could not be resolved safely.') from None


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, port, address, timeout):
        super().__init__(hostname, port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def download(url, output, max_bytes, validators=None, timeout=120):
    """Stream at most max_bytes, recheck redirects and keep Host/TLS verification.

    Return metadata; a 304 does not create an output file. No proxy environment,
    cookie jar, authorization header or user-controlled request header is used.
    """
    deadline = time.monotonic() + timeout
    validators = validators or {}
    initial = urlsplit(url)
    for redirect in range(6):
        parsed, hostname, port, address = public_destination(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError('The source took too long to download. Try refreshing it later.', 'source_temporarily_unavailable')
        conn = (_PinnedHTTPS(hostname, port, address, min(20, remaining))
                if parsed.scheme == 'https' else
                http.client.HTTPConnection(address, port, timeout=min(20, remaining)))
        headers = {'Host': hostname, 'User-Agent': 'CKAN-Dashboard/1.0', 'Accept-Encoding': 'identity'}
        same_origin = (parsed.scheme, parsed.netloc) == (initial.scheme, initial.netloc)
        if same_origin:
            for field, header in (('etag', 'If-None-Match'), ('last_modified', 'If-Modified-Since')):
                value = validators.get(field)
                if value and '\r' not in value and '\n' not in value:
                    headers[header] = value
        try:
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            conn.request('GET', target, headers=headers)
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location or redirect == 5:
                    raise SourceError('The source redirects too many times or has an invalid redirect.')
                next_url = urljoin(url, location)
                if parsed.scheme == 'https' and urlsplit(next_url).scheme != 'https':
                    raise SourceError('An HTTPS source cannot redirect to an insecure connection.')
                url = next_url
                continue
            meta = {key: response.getheader(header) for key, header in (
                ('etag', 'ETag'), ('last_modified', 'Last-Modified'))}
            if response.status == 304:
                if not validators:
                    raise SourceError('The source returned an invalid cache response.')
                return dict(meta, unchanged=True)
            if response.status != 200:
                raise SourceError('The source could not be downloaded (HTTP %s).' % response.status,
                                  'source_temporarily_unavailable' if response.status >= 500 or response.status == 429 else 'source_unavailable')
            encoding = response.getheader('Content-Encoding', 'identity').lower()
            if encoding not in ('', 'identity'):
                raise SourceError('The server must provide an uncompressed file download.')
            length = response.getheader('Content-Length')
            if length and int(length) > max_bytes:
                raise SourceError('The source exceeds the configured file size limit.')
            digest, size = hashlib.sha256(), 0
            with open(output, 'wb') as handle:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SourceError('The source took too long to download.', 'source_temporarily_unavailable')
                    if conn.sock:
                        conn.sock.settimeout(min(20, remaining))
                    # read1 returns after a socket read, allowing the overall
                    # deadline to stop slow trickle downloads.
                    chunk = getattr(response, 'read1', response.read)(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise SourceError('The source exceeds the configured file size limit.')
                    handle.write(chunk)
                    digest.update(chunk)
            if length is not None and size != int(length):
                raise SourceError('The source download was incomplete. Please try refreshing it.', 'source_temporarily_unavailable')
            return dict(meta, sha256=digest.hexdigest(), bytes=size, unchanged=False)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if isinstance(exc, SourceError):
                raise
            raise SourceError('The source could not be downloaded. Check its URL and try again.', 'source_temporarily_unavailable') from None
        finally:
            conn.close()
    raise SourceError('The source redirects too many times.')
