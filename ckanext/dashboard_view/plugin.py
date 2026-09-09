"""Manually created CKAN dashboards. No hooks create or mutate ResourceViews."""
import json
from urllib.parse import urlsplit

import ckan.plugins as plugins
import ckan.plugins.toolkit as tk

from .schema import normalize_config


def validate_dashboard_config(value):
    try:
        normalized = normalize_config(value)
    except ValueError as exc:
        raise tk.Invalid(str(exc))
    return json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))


class DashboardViewPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IResourceView, inherit=True)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IClick)
    if hasattr(plugins, 'IConfigDeclaration'):
        plugins.implements(plugins.IConfigDeclaration)

    def update_config(self, config):
        tk.add_template_directory(config, 'templates')
        tk.add_public_directory(config, 'public')
        # Intentionally never touch ckan.views.default_views.

    def declare_config_options(self, declaration, key):
        from pathlib import Path
        import yaml
        with open(Path(__file__).with_name('config_declaration.yaml'), encoding='utf-8') as stream:
            declaration.load_dict(yaml.safe_load(stream))

    def info(self):
        return {
            'name': 'dashboard_view', 'title': tk._('Dashboard'),
            'default_title': tk._('Dashboard'), 'icon': 'bar-chart',
            'always_available': False, 'iframed': False,
            'full_page_edit': True, 'preview_enabled': False, 'filterable': False,
            'schema': {'dashboard_config': [tk.get_validator('not_empty'), validate_dashboard_config]},
        }

    def can_view(self, data_dict):
        resource = data_dict.get('resource', {})
        if resource.get('datastore_active'):
            return True
        format_name = (resource.get('format') or '').lower().strip()
        extensions = ('.csv', '.tsv', '.txt', '.xlsx')
        return format_name in ('csv', 'tsv', 'txt', 'text', 'xlsx', 'text/csv',
                               'text/tab-separated-values', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') or urlsplit(resource.get('url') or '').path.lower().endswith(extensions)

    def form_template(self, context, data_dict):
        return 'dashboard_view/form.html'

    def view_template(self, context, data_dict):
        return 'dashboard_view/resource_view.html'

    def setup_template_variables(self, context, data_dict):
        from .helpers import bootstrap
        resource = data_dict['resource']
        view = data_dict.get('resource_view') or {}
        actor = context.get('user')
        common = bootstrap(resource, view, actor, package=data_dict.get('package'))
        return {'dashboard_view_bootstrap': common,
                'dashboard_editor_bootstrap': dict(common, mode='editor'),
                'dashboard_config_json': json.dumps(common['config'], ensure_ascii=False)}

    def get_blueprint(self):
        from .blueprint import blueprint
        return blueprint

    def get_helpers(self):
        from .helpers import dashboard_asset
        return {'dashboard_asset': dashboard_asset}

    def get_commands(self):
        from .cli import get_commands
        return get_commands()
