"""Load interfaces and parse CKAN templates without creating site data."""
from pathlib import Path

from flask import Flask
from jinja2 import Environment
from ckan.lib.jinja_extensions import _get_extensions
from ckanext.dashboard_view.plugin import DashboardViewPlugin

plugin = DashboardViewPlugin()
info = plugin.info()
assert info["name"] == "dashboard_view"
assert info.get("full_page_edit")
assert not info.get("always_available", False)
assert "dashboard_config" in info["schema"]
assert not hasattr(plugin, "after_create"), "Views must not be auto-created"
if hasattr(plugin, "get_actions"):
    assert "resource_view_list" not in plugin.get_actions()
blueprints = plugin.get_blueprint()
if not isinstance(blueprints, (list, tuple)):
    blueprints = [blueprints]
app = Flask(__name__)
for blueprint in blueprints:
    app.register_blueprint(blueprint)
env = Environment(extensions=_get_extensions())
root = Path(__file__).resolve().parents[1] / "ckanext/dashboard_view"
templates = list((root / "templates").rglob("*.html"))
assert templates
for template in templates:
    env.parse(template.read_text())
for filename in ("dashboard.js", "dashboard.css"):
    assert (root / "public/dashboard" / filename).is_file(), filename
print(f"PLUGIN OK: {len(templates)} templates; {len(list(app.url_map.iter_rules()))} routes")
