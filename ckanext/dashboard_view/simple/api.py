"""Same-origin CRUD, preview/query and export. Private by default."""
import csv
import io
from functools import wraps
from flask import Blueprint, jsonify, request, Response
from flask_wtf.csrf import generate_csrf
import ckan.plugins.toolkit as tk
from ..blueprint import _actor as _session_actor, _body, _csrf
from ..security import SourceError
from ..engine import _export_value
from . import store, access, sources, jobs, identity
from .schema import normalize, state

blueprint = Blueprint('simple_dashboard', __name__, url_prefix='/api/simple-dashboards')


def _actor():
    actor = _session_actor()
    return actor if identity.active_user(actor) else ''


def endpoint(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        if not tk.asbool(tk.config.get('ckanext.dashboard_view.simple_enabled', False)):
            return jsonify(error='Simple dashboards are not enabled.'), 404
        try:
            return fn(*args, **kwargs)
        except (tk.NotAuthorized, PermissionError):
            return jsonify(error='You do not have access to this dashboard or its data.'), 403
        except (tk.ObjectNotFound, LookupError):
            return jsonify(error='Dashboard or source not found.'), 404
        except (SourceError, ValueError, TypeError, KeyError) as exc:
            return jsonify(error=str(exc) if isinstance(exc, ValueError) else 'Invalid dashboard request.'), 400
    return call


@blueprint.after_request
def private(response):
    response.headers.update({'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Vary': 'Cookie, Authorization'})
    return response


def mutation():
    if not _actor():
        raise tk.NotAuthorized('Sign in to IHP to save dashboards.')
    data = _body()
    _csrf(data, 'refresh')
    return data


def revision_number(value):
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError('Choose a valid saved revision.')
    return value


def clean(item):
    return {k: v for k, v in item.items() if k != 'owner'}


@blueprint.route('/config')
@endpoint
def config():
    return jsonify(enabled=True, csrf_token=generate_csrf(), authenticated=bool(_actor()), refresh_seconds=300)


@blueprint.route('')
@endpoint
def listing():
    public = request.args.get('public') == '1'
    if not public and not _actor():
        raise tk.NotAuthorized('Sign in to view your dashboards.')
    items = []
    for row in store.listing(_actor(), public):
        try:
            item = access.read(row['id'], _actor(), row['published_revision'] if public else None)
            items.append({k: item[k] for k in ('id', 'title', 'revision', 'selected_revision', 'published_revision', 'updated_at')})
        except (tk.NotAuthorized, tk.ObjectNotFound, SourceError, PermissionError, LookupError):
            continue
    return jsonify(items=items)


@blueprint.route('', methods=['POST'])
@endpoint
def create():
    data = mutation()
    config = normalize(data.get('config'))
    sources.authorize_all(config, _actor())
    return jsonify(clean(store.save(config, _actor()))), 201


@blueprint.route('/<uuid:identifier>', methods=['GET', 'POST', 'DELETE'])
@endpoint
def dashboard(identifier):
    identifier = str(identifier)
    if request.method == 'GET':
        revision = request.args.get('revision', type=int)
        item = access.read(identifier, _actor(), revision)
        return jsonify(**clean(item), can_edit=access.owner(item, _actor()))
    data = mutation()
    access.edit(identifier, _actor())
    if request.method == 'DELETE':
        store.delete(identifier)
        return jsonify(deleted=True)
    config = normalize(data.get('config'))
    sources.authorize_all(config, _actor())
    return jsonify(clean(store.save(config, _actor(), identifier, revision_number(data.get('revision')))))


@blueprint.route('/<uuid:identifier>/publish', methods=['POST'])
@endpoint
def publish(identifier):
    data = mutation()
    access.edit(str(identifier), _actor())
    item = store.get(str(identifier), revision_number(data.get('revision')))
    publishing = data.get('publish') is True
    if publishing:
        sources.authorize_all(item['config'], public=True)
    store.visibility(str(identifier), item['selected_revision'], publishing)
    return jsonify(published=publishing, revision=item['selected_revision'])


@blueprint.route('/<uuid:identifier>/duplicate', methods=['POST'])
@endpoint
def duplicate(identifier):
    data = mutation()
    item = access.read(str(identifier), _actor(), revision_number(data.get('revision')))
    config = dict(item['config'], title=data.get('title') or item['config']['title'])
    return jsonify(clean(store.save(normalize(config), _actor()))), 201


@blueprint.route('/preview', methods=['POST'])
@endpoint
def preview():
    data = mutation()
    config = normalize(data.get('config'), allow_empty=True)
    result = jobs.query(config, _actor())
    return jsonify(result), 202 if result['status'] == 'pending' else 200


@blueprint.route('/<uuid:identifier>/query', methods=['POST'])
@endpoint
def query(identifier):
    data = _body()
    _csrf({'view_id': str(identifier)}, 'query')
    item = access.read(str(identifier), _actor(), revision_number(data.get('revision')))
    config = item['config']
    if 'state' in data:
        config = dict(config, state=state(data['state']))
    result = jobs.query(config, _actor())
    access.read(str(identifier), _actor(), item['selected_revision'])
    return jsonify(result), 202 if result['status'] == 'pending' else 200


@blueprint.route('/<uuid:identifier>/export', methods=['POST'])
@endpoint
def export(identifier):
    data = _body()
    _csrf({'view_id': str(identifier)}, 'query')
    item = access.read(str(identifier), _actor(), revision_number(data.get('revision')))
    config = item['config']
    if 'state' in data:
        config = dict(config, state=state(data['state']))
    result = jobs.query(config, _actor())
    if not result.get('results'):
        return jsonify(result), 202
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['block', 'row', 'column', 'value', 'unit', 'calculated_at', 'status'])
    for block in config['blocks']:
        value = result['results'].get(block['id'], {})
        if value.get('error'):
            continue
        if block['type'] == 'kpi':
            cells = [('', 'value', value.get('value'))]
        elif block['type'] == 'table':
            columns = [c if isinstance(c, str) else c['key'] for c in value.get('columns', [])]
            cells = [(index + 1, column, row.get(column) if isinstance(row, dict) else row[j])
                     for index, row in enumerate(value.get('rows', [])) for j, column in enumerate(columns)]
        else:
            cells = [(label, dataset.get('label', 'value'), dataset['data'][i])
                     for dataset in value.get('datasets', []) for i, label in enumerate(value.get('labels', []))]
        for row, column, cell in cells:
            writer.writerow([_export_value(x) for x in [block['title'], row, column, cell,
                            value.get('unit', ''), result.get('calculated_at'), result['status']]])
    access.read(str(identifier), _actor(), item['selected_revision'])
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="dashboard.csv"'})


try:
    from ckan.config.middleware.flask_app import csrf
    for function in (create, dashboard, publish, duplicate, preview, query, export):
        csrf.exempt(function)
except ImportError:
    pass
