"""Append only this plugin's settings to the inherited dev image INI."""
import re
from pathlib import Path

seen = set()
for name in ("/app/production.ini", "/srv/app/production.ini"):
    path = Path(name)
    if not path.is_file() or path.resolve() in seen:
        continue
    seen.add(path.resolve())
    text = path.read_text()
    match = re.search(r"^ckan\.plugins\s*=\s*(.*)$", text, re.M)
    if not match:
        raise SystemExit(f"No ckan.plugins declaration in {name}")
    plugins = match.group(1).split()
    if "dashboard_view" not in plugins:
        plugins.append("dashboard_view")
    text = text[:match.start()] + "ckan.plugins = " + " ".join(plugins) + text[match.end():]
    # Leave default views untouched: explicit authorship is required.
    settings = {
        "ckanext.dashboard_view.cache_dir": "/var/lib/ckan/dashboard-cache",
        "ckanext.dashboard_view.refresh_seconds": "300",
    }
    for key, value in settings.items():
        pattern = rf"^{re.escape(key)}\s*=.*$"
        if re.search(pattern, text, re.M):
            text = re.sub(pattern, f"{key} = {value}", text, flags=re.M)
        else:
            # CKAN configuration belongs before logging or other INI sections.
            app_section = re.search(r"^\[app:main\]\s*$", text, re.M)
            if not app_section:
                raise SystemExit(f"No app:main section in {name}")
            following = re.search(r"^\[[^\]]+\]", text[app_section.end():], re.M)
            insert_at = app_section.end() + following.start() if following else len(text)
            text = text[:insert_at] + f"\n{key} = {value}\n\n" + text[insert_at:]
    path.write_text(text)
print("Dashboard plugin registered in inherited INI; automatic views unchanged.")
