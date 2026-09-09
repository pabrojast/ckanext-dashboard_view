"""Template contract shared by CKAN's resource view and standalone embed."""
from pathlib import Path


def dashboard_asset(name):
    import ckan.plugins.toolkit as tk
    if name not in ('dashboard.js', 'dashboard.css'):
        raise ValueError('Unknown dashboard asset')
    directory = Path(__file__).parent / 'public' / 'dashboard'
    path = directory / name
    stamp = str(int(path.stat().st_mtime)) if path.exists() else '1'
    return tk.url_for('dashboard_view.assets', name=name) + '?v=' + stamp


def bootstrap(resource, view, actor=None, mode='view', package=None):
    import ckan.plugins.toolkit as tk
    from .schema import normalize_config
    from .security import may_edit
    try:
        config = normalize_config(view.get('dashboard_config') or {}, allow_empty=True)
    except ValueError:
        config = normalize_config({}, allow_empty=True)
    if not view.get('dashboard_config') and resource.get('datastore_active'):
        config['source']['kind'] = 'datastore'
    view_id = view.get('id')
    try:
        language = tk.h.lang()
    except (AttributeError, RuntimeError):
        language = tk.config.get('ckan.locale_default', 'en')
    package = package or {'id': resource['package_id'], 'type': 'dataset'}
    return {
        'mode': mode, 'resource_id': resource['id'], 'view_id': view_id,
        'title': view.get('title') or tk._('Dashboard'), 'config': config,
        'lang': str(language or 'en'),
        'api_base': tk.url_for('dashboard_view.profile', resource_id=resource['id']).rsplit('/', 1)[0],
        'view_url': tk.url_for('dashboard_view.view', view_id=view_id, _external=True) if view_id else '',
        'embed_url': tk.url_for('dashboard_view.embed', view_id=view_id, _external=True) if view_id else '',
        'resource_url': tk.url_for(package.get('type', 'dataset') + '_resource.read',
                                  id=package.get('name') or package['id'], resource_id=resource['id']),
        'basemap_url': tk.config.get('ckanext.dashboard_view.basemap_url',
                                    'https://tiles.openfreemap.org/styles/positron'),
        'can_edit': may_edit(resource['id'], actor),
    }
