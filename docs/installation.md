# Installation

Requires CKAN 2.10, Python 3.10 or newer, Redis/RQ, and a writable private cache directory shared by the CKAN web process and the two dashboard workers. Frontend assets ship with the Python package.

## Build and activate

```bash
cd frontend
npm ci
npm run build
cd ..
pip install .
```

Add `dashboard_view` to the existing `ckan.plugins` list. **Do not add it to `ckan.views.default_views`.** No resource-view creation hooks or listing overrides are installed.

Use the same CKAN configuration, database, Redis URL and `ckan.site_id` in the web process and workers. If `ckanext-envvars` is enabled, keep the INI plugin list and `CKAN__PLUGINS` consistent. Confirm the actual Dashboard option and route after startup; a status endpoint's plugin list alone is not proof of activation.

```ini
ckanext.dashboard_view.cache_dir = /var/lib/ckan/dashboard-cache
ckanext.dashboard_view.refresh_seconds = 300
ckanext.dashboard_view.max_file_bytes = 268435456
ckanext.dashboard_view.max_rows = 5000000
ckanext.dashboard_view.max_columns = 500
ckanext.dashboard_view.memory_limit = 1GB
ckanext.dashboard_view.queue_build = dashboard-build
ckanext.dashboard_view.queue_query = dashboard-query
```

The cache directory must be owned by the CKAN UID and mode `0700`; cached data files use `0600`. Configure an actual container/process memory limit above DuckDB's memory setting; the latter alone does not cap all memory used by the process.

## Workers

Run one process for each queue:

```bash
ckan -c /app/production.ini dashboard worker --queue build
ckan -c /app/production.ini dashboard worker --queue query
```

The workers initialize CKAN once and retain CKAN's connection cleanup around forked jobs. A dedicated query queue keeps source preparation from delaying existing dashboards. Set a 2 GiB memory limit per worker, concurrency one and two CPU threads. Confirm a real source-preparation job and query complete, not only that a job was enqueued.

Clean idle caches with `ckan -c /app/production.ini dashboard prune-cache`. Original data remains in CKAN storage or its registered remote source; losing the dashboard cache only requires rebuilding it. Configuration is stored in CKAN's existing `ResourceView.config`, without extra database tables or a migration.

## Alpine container builds

DuckDB 1.5.5 ships glibc wheels on PyPI. The CKAN images used here run Alpine/musl, so build a native CPython 3.10 wheel once and reuse it in both images:

```bash
docker build -f deploy/Dockerfile.duckdb -t dashboard-duckdb-wheel:1.5.5 .
docker build -f Dockerfile.test -t dashboard-view-test .
docker build -f Dockerfile.dev \
  --build-arg BASE_IMAGE=EXACT_CURRENT_DEV_IMAGE \
  -t YOUR_DEV_IMAGE .
```

The first build compiles C++ and may take approximately 20 minutes. Subsequent builds reuse the wheel image. Rebuild the wheel when changing Python ABI, CPU architecture or DuckDB version. The extension does not replace CKAN's Flask/Werkzeug dependencies.

## Development deployment

`Dockerfile.dev` derives from the exact current dev image. `deploy/configure_image.py` appends only this plugin's settings and leaves automatic view types unchanged. `deploy/deploy_dev.py` verifies the `data.dev-wins.com` ingress and patches only its CKAN deployment, adds two workers and a private 12 GiB `emptyDir` cache. It avoids a Helm upgrade that could regenerate unrelated session secrets.

```bash
python deploy/deploy_dev.py --image IMAGE_WITH_DASHBOARD
python deploy/deploy_dev.py --image IMAGE_WITH_DASHBOARD --apply
kubectl -n ckan rollout status deployment/ckan --timeout=50s
```

The first command prints a reviewable deployment summary. The second records a minimal rollback patch in `output/deploy/` and applies the change. The current dev readiness probe has a five-minute initial delay. Continue observing the rollout rather than interpreting an early timeout as a failed deployment.

Rollback:

```bash
kubectl -n ckan patch deployment ckan --type strategic --patch-file output/deploy/rollback-TIMESTAMP.json
```

This operational overlay is reproducible from this checkout. A later deployment through the main infrastructure repository must carry the same image/plugin/worker configuration or reapply this overlay.

## Local CKAN and browser testing

```bash
bash scripts/run-ckan-tests.sh
docker compose -f compose.dev.yml up -d --build
python scripts/http_smoke.py
```

The isolated CKAN is at `http://127.0.0.1:5189`. Its fixture-only account is `dashboard_admin` / `local-dashboard-only`. These credentials belong exclusively to the local stack. A lighter browser harness at port 5188 is documented in the repository README.

## Embedding and access

The embed route defaults to `Content-Security-Policy: frame-ancestors *`. Set `ckanext.dashboard_view.frame_ancestors` to space-separated exact origins if deployment policy requires restrictions. Check the final public response: a reverse proxy must not add a conflicting `X-Frame-Options` header to `/dashboard/*/embed`.

Resource and download access are revalidated for every data request, including cached data. With `ckanext-datashare`, its download policy applies. Public dashboards work without cookies; private dashboards require authorized CKAN access and are not intended to bypass third-party-cookie restrictions in external portals. Sharing never creates a public data copy.

Remote resources must resolve to public HTTP(S) destinations. Downloads pin the validated address, recheck redirects, verify HTTPS certificates, and enforce byte/time limits. CKAN-managed uploads use the configured uploader; signed storage URLs stay on the server.
