# Native simple dashboards

Independent module `ckanext.dashboard_view.simple`; existing ResourceViews and `/dashboard-api` contracts are unchanged. The Terria editor selects up to six durable sources and six KPI, line, bar or table blocks. No joins, SQL or free expressions are accepted.

## Enable

1. Install this extension and the pinned Terria calculator bundle at `/opt/terria-calculator/dist/calculator.mjs` (Node 22+).
2. Run `ckan -c /app/production.ini dashboard simple-init-db`. This additive, repeatable migration creates `simple_dashboard`, `simple_dashboard_revision` and `simple_dashboard_result` in CKAN's PostgreSQL database.
3. Supervise `ckan -c /app/production.ini dashboard worker --queue simple`. Jobs run in the dedicated `simple-dashboard` queue, timeout 900 seconds; request claims expire after 1200 seconds. Each actor can have at most three pending calculations.
4. Set `ckanext.dashboard_view.simple_public_prefixes` to administrator-approved, public URL namespaces ending in `/`, separated by spaces. Default empty; CKAN resource IDs do not need this setting.
5. Enable `ckanext.dashboard_view.simple_enabled = true`, then Terria `parameters.simpleDashboards.enabled` after backend checks. Both default off.

## API

Same-origin `/api/simple-dashboards`:

- `GET /config` provides session CSRF token and availability.
- `GET /` lists the signed-in owner's library; `?public=1` lists authorized published revisions.
- `POST /` creates a private dashboard from `config`.
- `GET /<id>?revision=N` reads that immutable revision; without revision, readers get the published edition and owners get the latest draft.
- `POST /<id>` saves a new revision, requiring the current `revision` for optimistic concurrency.
- `DELETE /<id>` withdraws the dashboard and its references.
- `POST /<id>/publish` takes `revision` and boolean `publish`. Unpublishing withdraws every published revision.
- `POST /<id>/duplicate` creates a new private copy of an authorized revision.
- `POST /preview` previews validated source/configuration for an authenticated reader.
- `POST /<id>/query` and `/export` accept revision and optional bounded date/area `state`; query reports pending/ready/stale/error. CSV exports contain calculation timestamps and status and escape spreadsheet formulas.

Cookie-authenticated writes/previews require CSRF. Anonymous saved/public reads cannot submit source definitions. All endpoints use private, no-store responses. Source read/download checks run before and after calculation and on every cached read; only owner/sysadmin edits. Public publication and reads recheck all sources as anonymous. Draft content is never implicitly published.

Account state is checked against the current database on requests and queued calculations. A cookie or job created before account deactivation does not retain authoring, ownership or private-result access; inactive sysadmins have no bypass.

## Calculations and cache

CSV/TSV/XLSX and DataStore reuse source authorization/materialization and the bounded DuckDB engine. GeoJSON FeatureCollection properties become a table; point coordinates are available as columns. Raster sources use a stored CKAN URL (COG or JSON `times` with one COG/date); physical conversion can come from TIFF metadata or stored `simple_dashboard_cog` resource metadata. Bodies in registered water pilots use the original analytics JSON and Terria WaterQuality functions. Local browser files are never accepted as shared server results.

PostgreSQL holds persistent results; Redis only tracks pending jobs. Every 300 seconds of active use, source content/validators are checked. Block keys include engine version, content identity, filters, band and geometry. Raster date keys reuse unaffected dates; sources without verifiable validators are rechecked after the interval. A restart losing local materializations recreates those files; saved results survive in PostgreSQL. Temporary failures can retain prior values with explicit stale status; access failures cannot. Versioned source URLs remain on their edition until the registered URL changes.

Private snapshot and DuckDB files live under the existing `cache_dir` in `simple-sources` and `simple-tables`. Normal CKAN/database backups must include the three new tables. The existing cache pruning command does not delete dashboard definitions or revisions. Server cache maintenance is independent of old ResourceView generations.

## Validation

`python -m pytest -q` includes API login/CSRF/ownership, private drafts, explicit publication, old revisions, optimistic conflicts, revocation, duplicate/delete, persistent restart, deduplicated jobs, changed content, missing values and transient failures. The Node package in Terria separately verifies public-network transport restrictions and shares the browser math core.

## Spatial runtime state

`state.spatial` optionally selects `configured` (legacy default), `viewport`, or `fixed`. Non-configured modes require WGS84 `bounds: {west,south,east,north}`; `west > east` crosses the antimeridian. `quality` defaults to `quick`; `native` requires fixed bounds. The same state is accepted by preview, query and export. It does not modify a stored revision. CSV exports with spatial state include a `__context__` row.

Sources accept optional `latitude_field`/`longitude_field` (otherwise detect unambiguous numeric lat/lon column labels), and `analysis_resource_id` for a registered analysis COG. Additional resources are authorized on every read, execution and publication. GeoJSON generations retain their original geometries privately, use the bounded Node calculator for exact entity intersection, and select typed DuckDB rows before aggregation. The shared engine's optional internal `coordinates` and `row_ids` arguments do not allow SQL expressions or external files. Existing Dashboard Builder map-widget bounds remain compatible.

Water blocks keep `body_scope: fixed` by default. `body_scope: viewport` selects intersecting body bboxes and computes an area-weighted median of body summaries for each period. This is explicitly distinct from clipped-pixel means. Native analysis uses the registered raster, including its physical conversion metadata, with 500,000 pixels per read window, 5,000,000 pixels per temporal block and the existing worker/date limits. Unlocated tables are marked `spatial_scope: unfiltered`; empty means are null.

Spatial results and intermediate statistics use Redis keys `simple-dashboard:extent:*` with a 3600-second TTL. Source generations and configured calculations retain existing persistence. Engine version `simple-2-spatial` prevents reuse of old results that ignored spatial filtering. Deploy the compatible calculator and backend before the viewer. No database migration is required.
