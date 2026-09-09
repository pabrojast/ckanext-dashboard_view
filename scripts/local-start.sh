#!/usr/bin/env bash
set -euo pipefail
ckan config-tool "$CKAN_INI" \
  "sqlalchemy.url = $CKAN_SQLALCHEMY_URL" \
  "ckan.datastore.write_url = $CKAN_DATASTORE_WRITE_URL" \
  "ckan.datastore.read_url = $CKAN_DATASTORE_READ_URL" \
  "solr_url = $CKAN_SOLR_URL" \
  "ckan.redis.url = $CKAN_REDIS_URL" \
  "ckan.site_url = $CKAN_SITE_URL" \
  "ckan.plugins = $CKAN__PLUGINS" \
  "ckan.storage_path = /var/lib/ckan/storage" \
  "ckan.webassets.path = /var/lib/ckan/storage/webassets" \
  "ckanext.dashboard_view.cache_dir = /var/lib/ckan/dashboard-cache" \
  "ckan.views.default_views = image_view text_view" \
  "ckan.csrf_protection.ignore_extensions = false" \
  "beaker.session.secret = localhost-dashboard-only-secret-for-testing" \
  "WTF_CSRF_SECRET_KEY = localhost-dashboard-only-csrf-secret-for-testing" \
  "api_token.jwt.encode.secret = string:localhost-dashboard-only-jwt-secret" \
  "api_token.jwt.decode.secret = string:localhost-dashboard-only-jwt-secret"
mkdir -p /var/lib/ckan/storage /var/lib/ckan/dashboard-cache
if [[ "${1:-}" == "worker" ]]; then
  # Wait for the web process to initialize its isolated database.
  python - <<'PY'
import time, urllib.request
for attempt in range(120):
    try:
        with urllib.request.urlopen('http://ckan:5000/api/3/action/status_show', timeout=2) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit('Local CKAN did not become ready')
PY
  exec ckan -c "$CKAN_INI" dashboard worker --queue "$2"
fi
ckan -c "$CKAN_INI" db init
ckan -c "$CKAN_INI" asset build
ckan -c "$CKAN_INI" user add "$CKAN_SYSADMIN_NAME" "password=$CKAN_SYSADMIN_PASSWORD" "email=$CKAN_SYSADMIN_EMAIL" >/dev/null 2>&1 || true
ckan -c "$CKAN_INI" sysadmin add "$CKAN_SYSADMIN_NAME" >/dev/null
exec ckan -c "$CKAN_INI" run -H 0.0.0.0 -p 5000 --disable-reloader
