"""Read-authorized dashboard pages and asynchronous JSON endpoints."""
import json
import logging
import traceback
from pathlib import Path

from flask import Blueprint, Response, g, jsonify, make_response, request, send_file, send_from_directory
import ckan.plugins.toolkit as tk

from . import service
from .helpers import bootstrap
from .schema import normalize_config, normalize_source
from .security import SourceError, authorize_resource, saved_view

log = logging.getLogger(__name__)
blueprint = Blueprint('dashboard_view', __name__)


def _actor():
    return getattr(g, 'user', None) or ''


def _response(data, status=None):
    status = status or (202 if data.get('status') == 'pending' else 400 if data.get('status') == 'error' else 200)
    response = jsonify(data)
    response.status_code = status
    return response


@blueprint.after_request
def private_response(response):
    if request.endpoint == 'dashboard_view.assets':
        return response
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers.add('Vary', 'Cookie')
    response.headers.add('Vary', 'Authorization')
    if request.endpoint == 'dashboard_view.embed':
        response.headers.pop('X-Frame-Options', None)
        ancestors = tk.config.get('ckanext.dashboard_view.frame_ancestors', '*')
        response.headers['Content-Security-Policy'] = 'frame-ancestors ' + ancestors
    return response


def _body():
    if request.content_length and request.content_length > 262144:
        raise SourceError('The dashboard request is too large.')
    if not request.is_json:
        raise SourceError('Send a JSON object for this request.')
    # Bound even chunked requests without Content-Length.
    payload = request.stream.read(262145)
    if len(payload) > 262144:
        raise SourceError('The dashboard request is too large.')
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError):
        raise SourceError('The dashboard request contains invalid JSON.') from None
    if not isinstance(data, dict):
        raise SourceError('Send a JSON object for this request.')
    return data


def _csrf(data, operation):
    """Only anonymous saved-dashboard reads can omit a session CSRF token.

    The endpoint functions are exempt from Flask-WTF's unconditional POST gate;
    this narrower check is performed for every request, including plugin sites
    which globally exempt extensions. API-token authentication already protects
    against cookie-based CSRF and follows CKAN's own policy.
    """
    if getattr(g, 'login_via_auth_header', False):
        return
    saved_read = (operation != 'refresh' and bool(data.get('view_id'))
                  and 'config' not in data and 'source' not in data)
    if saved_read and not _actor():
        return
    from flask_wtf.csrf import validate_csrf
    from wtforms.validators import ValidationError
    try:
        validate_csrf(request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token'))
    except ValidationError:
        raise tk.NotAuthorized('The page has expired. Reload it before trying again.') from None


def _selection(resource_id, data, operation):
    actor = _actor()
    preview = 'config' in data or 'source' in data or not data.get('view_id')
    resource, package = authorize_resource(resource_id, actor, edit=preview or operation == 'refresh')
    view = saved_view(data['view_id'], resource_id, actor) if data.get('view_id') else None
    if 'config' in data:
        config = normalize_config(data['config'], allow_empty=True)
    elif view:
        config = normalize_config(view['dashboard_config'])
    else:
        config = normalize_config({}, allow_empty=True)
    if 'source' in data:
        config['source'] = normalize_source(data['source'])
    elif not view and 'config' not in data and resource.get('datastore_active'):
        config['source'] = normalize_source({'kind': 'datastore'})
    return resource, config


def _api(resource_id, operation):
    try:
        data = _body()
        _csrf(data, operation)
        resource, config = _selection(resource_id, data, operation)
        if operation in ('profile', 'refresh'):
            result, _ = service.prepare(resource, config['source'], _actor(), force=operation == 'refresh')
            # A completed build's Redis marker intentionally omits column data;
            # return the profile from the atomically published generation.
            if result.get('status') == 'ready' and 'fields' not in result:
                result, _ = service.prepare(resource, config['source'], _actor())
            return _response(result)
        filters = data.get('filters') or []
        pages = data.get('pages') or {}
        bounds = data.get('bounds')
        if not isinstance(filters, list) or len(filters) > 24:
            raise SourceError('Use at most 24 dashboard filter conditions.')
        if not isinstance(pages, dict) or len(pages) > 24:
            raise SourceError('Invalid table pagination.')
        if bounds is not None and not isinstance(bounds, dict):
            raise SourceError('Invalid map bounds.')
        result = service.run_query(resource, config['source'], config, _actor(),
                                   filters=filters, bounds=bounds, pages=pages, export=operation == 'export')
        if operation == 'export' and result.get('status') == 'ready':
            # Reauthorize immediately before handing a cached file to Flask.
            authorize_resource(resource_id, _actor())
            path = service.export_path(result.get('export_key'))
            response = send_file(path, mimetype='text/csv',
                                 as_attachment=True, download_name='dashboard-%s.csv' % resource_id,
                                 conditional=False, max_age=0)
            response.headers['X-Dashboard-Generation'] = result['generation']
            return response
        return _response(result)
    except tk.NotAuthorized:
        return _response({'status': 'error', 'code': 'access_denied',
                          'message': 'You cannot access this dashboard, or your session expired. Reload the page.'}, 403)
    except tk.ObjectNotFound:
        return _response({'status': 'error', 'code': 'not_found', 'message': 'Dashboard or resource not found.'}, 404)
    except SourceError as exc:
        return _response({'status': 'error', 'code': exc.code, 'message': str(exc)[:500]}, 400)
    except (ValueError, TypeError, KeyError) as exc:
        message = str(exc)[:500] if isinstance(exc, ValueError) else 'The dashboard request is incomplete or invalid.'
        return _response({'status': 'error', 'code': 'invalid_request', 'message': message}, 400)
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        location = '%s:%s' % (Path(frames[-1].filename).name, frames[-1].lineno) if frames else 'unknown'
        log.error('Dashboard request failed (%s at %s)', type(exc).__name__, location)
        return _response({'status': 'error', 'code': 'service_unavailable',
                          'message': 'Dashboard processing is temporarily unavailable. Please try again.'}, 503)


@blueprint.route('/dashboard-api/resource/<resource_id>/profile', methods=['POST'])
def profile(resource_id):
    return _api(resource_id, 'profile')


@blueprint.route('/dashboard-api/resource/<resource_id>/query', methods=['POST'])
def query(resource_id):
    return _api(resource_id, 'query')


@blueprint.route('/dashboard-api/resource/<resource_id>/refresh', methods=['POST'])
def refresh(resource_id):
    return _api(resource_id, 'refresh')


@blueprint.route('/dashboard-api/resource/<resource_id>/export', methods=['POST'])
def export(resource_id):
    return _api(resource_id, 'export')


def _render(view_id, embed=False):
    try:
        view_data = saved_view(view_id, actor=_actor())
        resource, package = authorize_resource(view_data['resource_id'], _actor())
        data = bootstrap(resource, view_data, _actor(), package=package)
        return tk.render('dashboard_view/embed.html' if embed else 'dashboard_view/page.html',
                         extra_vars={'dashboard_view_bootstrap': data, 'dashboard_title': view_data['title'],
                                     'resource': resource, 'pkg': package, 'resource_view': view_data})
    except tk.NotAuthorized:
        return tk.abort(403, tk._('You do not have permission to view this dashboard.'))
    except tk.ObjectNotFound:
        return tk.abort(404, tk._('Dashboard not found.'))


@blueprint.route('/dashboard/<uuid:view_id>')
def view(view_id):
    return _render(str(view_id))


@blueprint.route('/dashboard/<uuid:view_id>/embed')
def embed(view_id):
    return _render(str(view_id), embed=True)


@blueprint.route('/dashboard-static/<path:name>')
def assets(name):
    return send_from_directory(Path(__file__).parent / 'public' / 'dashboard', name, max_age=3600)


# Exemption is restricted to these JSON actions; _csrf performs the appropriate
# per-request validation. Native CKAN save/update forms retain core protection.
try:
    from ckan.config.middleware.flask_app import csrf
    for endpoint in (profile, query, refresh, export):
        csrf.exempt(endpoint)
except ImportError:  # CKAN distributions without Flask-WTF must add it.
    pass
