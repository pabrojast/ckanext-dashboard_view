# Dashboard Builder for CKAN

An independent CKAN 2.10 resource-view plugin for manually authored dashboards over CSV, TSV, XLSX and DataStore resources. Chart.js charts, a flat MapLibre map, shared filters, and a responsive GridStack editor use server-side DuckDB queries. The resource remains the source of truth.

The plugin is named `dashboard_view`. Installing it does **not** create views. A dataset editor chooses **Manage views → New view → Dashboard**, configures the dashboard, and saves it. The saved view can be shared with a stable link or embedded in an iframe.

See [installation](docs/installation.md), [user guide](docs/user-guide.md) and [validation](docs/validation.md).

[Try the development example](https://data.dev-wins.com/es/dashboard/70441d68-3fa1-4e54-b7be-f87b6b27f515) with 20,000 clearly labelled synthetic observations.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test,demo]'
cd frontend
npm ci
python3 ../scripts/collect-frontend-licenses.py
npm run build
cd ..
.venv/bin/python scripts/dev_server.py --port 5188
```

The standalone development server uses real parsing and aggregation over synthetic data. It is bound to localhost and is a QA harness, not an alternative production server or an authentication implementation.

Run the CKAN package checks with `bash scripts/run-ckan-tests.sh`. Browser artifacts and deployment records go in the ignored `output/` directory. Compiled frontend assets are included in the Python package, so the CKAN runtime needs no Node.js or JavaScript CDN.

## Boundaries

- One resource per dashboard; multiple dashboards can reference that resource.
- Creation and editing use existing CKAN resource permissions. Download restrictions are enforced for the data API and exports.
- No SQL, executable JavaScript or arbitrary iframe HTML in dashboard configuration.
- The separate Citizens4Water and CS UNESCO portals are not modified. CS UNESCO's existing CSV resources can be used directly; C4W files or their URLs must first be registered as CKAN resources.
- Public embeds do not require login. Private dashboards retain authorization and are not published by sharing their link.

Licensed under AGPL-3.0-or-later. Frontend dependency licenses and copyright notices are included in [THIRD_PARTY_NOTICES.txt](frontend/public/THIRD_PARTY_NOTICES.txt), which the frontend build copies alongside the distributed assets. Regenerate them after `npm ci` with `python3 scripts/collect-frontend-licenses.py`; use `--check` to verify that they match the lockfile and installed packages.
