# Validation record

The final verification results for this implementation are recorded here after the last code change. Raw benchmark reports, HTTP fixture IDs and browser artifacts live in `output/`, which is deliberately excluded from Git and container build contexts.

Reproducible checks:

```bash
.venv/bin/python -m pytest -q ckanext/dashboard_view/tests
bash scripts/run-ckan-tests.sh
cd frontend && npm ci && npm run build
cd ..
.venv/bin/python scripts/benchmark.py --rows 1000000
.venv/bin/python scripts/benchmark.py --rows 5000000
.venv/bin/python scripts/http_smoke.py
git diff --check
```

The numerical benchmark prepares original synthetic rows, checks exact row counts and median, confirms category/histogram/map totals, and times six widgets. It reports peak process RSS and response size. It is not a claim about every possible input: number of columns, cardinality and Excel metadata also affect cost.

The HTTP test creates isolated fixtures, saves a view through CKAN's native form, polls actual background jobs, checks filtered exports and embed headers, then revokes and restores public access to prove cached results do not bypass resource permissions. It accepts localhost by default; dev requires explicit `--dev` and a token file.

Browser verification covers editing, source interpretation, filters, save/reload, keyboard and pointer layout changes, undo/redo, responsive layouts, exports, and an iframe hosted from another origin. Unit test success alone does not establish these behaviors.

## Automated checks and local integration

- **118 tests passed** with the final backend and engine, including CSV/XLSX parsing, exact statistics, typed filters, multiple maps, parameterized queries, DNS pinning, truncated downloads, CSRF, authorization, cache invalidation and Azure upload signing. The suite also passed inside the stock CKAN 2.10 Alpine image with Python 3.10; CKAN's unrelated pytest plugins were excluded using `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- CKAN interface and template loading: **5 templates, 8 routes**, manual-only resource view registration.
- Native localhost CKAN HTTP integration: **18 checks passed**, including native create/edit/save, persisted layout, real RQ source preparation and queries, filtered CSV and map exports, anonymous restrictions, private-cache revocation, uploaded-resource replacement, PostgreSQL DataStore snapshots and refresh after upsert.
- Browser verification in the actual CKAN theme covered saving through the builder button and reloading, country filtering, CSV download, mobile editor/properties and standalone embed. The final 390 px viewport retained a 390 px document width. The standalone 20,000-row harness additionally covered pointer dragging, keyboard resizing, undo/redo, literal text safety, PNG download, and ES/EN/FR layouts.
- Frontend TypeScript/Vite build passed; notices for 26 runtime npm packages are included and reproducibly checked. Python wheel generation passed with templates, assets, map worker and licenses included.

Captures include `output/playwright/ckan-native-mobile-editor-final.png`, `ckan-native-mobile-properties-final.png` and `ckan-native-mobile-embed.png`. Local HTTP IDs and checks are recorded in `output/http/127.0.0.1.json`.

## Final engine benchmarks — 2026-09-09

Executed after the engine's category-filter, map-selection and XLSX metadata changes using `scripts/benchmark.py`. Local environment: Linux x86-64, Intel Xeon E-2124, Python 3.13.13, DuckDB 1.5.5 and openpyxl 3.1.5. Preparation used two DuckDB threads and a `1GB` memory setting; query connections used two threads and `768MB`.

| Source rows | Source size | Preparation | First query | Warm query p95 | Peak process RSS | JSON response |
|---|---:|---:|---:|---:|---:|---:|
| 1,000,000 | 30.7 MiB | 1.730 s | 0.124 s | 0.134 s | 222.4 MiB | 32,956 bytes |
| 5,000,000 | 153.6 MiB | 9.561 s | 0.747 s | 0.725 s | 527.6 MiB | 33,708 bytes |

Each run prepared the complete five-column CSV and executed seven queries containing six widgets: count, median, country categories, monthly mean, histogram and map. Assertions verified the exact row count, median `4.95` within `1e-9`, five equal country totals, histogram total and the sum of map-cell row counts. Every block completed without an error.

Warm p95 uses the nearest-rank method on six observations, so it equals the largest warm sample. The complete warm samples were `0.122, 0.134, 0.129, 0.122, 0.128, 0.132` seconds for one million rows and `0.602, 0.725, 0.563, 0.515, 0.525, 0.537` seconds for five million. Peak RSS covers the entire benchmark process, including preparation; it is not a measurement of the CKAN web process or simultaneous workers.

These measurements execute the pure engine against prepared data; they exclude HTTP, Redis/RQ queue waits, remote source download and browser rendering. The local one-million-row engine run meets the three-second target for this fixture; production response times still require deployment checks. Raw reports are in `output/benchmarks/1000000/report.json` and `output/benchmarks/5000000/report.json`.

### Native Alpine development image

The same one-million-row benchmark also passed inside `pabrojast/ckan-base210:dashboard-view-20260909-rc1`, with Docker enforcing **2 GiB memory and two CPUs**. Runtime: Alpine/musl, Python 3.10.18, DuckDB 1.5.5 and openpyxl 3.1.5. The image's `engine.py` SHA-256 matched the final workspace file (`908514f8d775dd5871b9cc0864ca132f8f878b0d5bbb66d85e1359dadfc9001f`).

| Source rows | Preparation | First query | Warm query p95 | Peak process RSS | JSON response |
|---|---:|---:|---:|---:|---:|
| 1,000,000 | 2.579 s | 0.165 s | 0.150 s | 294.4 MiB | 32,989 bytes |

All numerical assertions described above passed. Warm query samples were `0.150, 0.139, 0.145, 0.140, 0.135, 0.142` seconds. The process ran as the host UID/GID to write the mounted synthetic-output directory; this check establishes native engine compatibility and resource usage, not CKAN service-account permissions. Raw report: `output/benchmarks/alpine/1000000/report.json`.

```bash
mkdir -p output/benchmarks/alpine
docker run --rm --memory=2g --cpus=2 --user "$(id -u):$(id -g)" \
  -v "$PWD/output/benchmarks/alpine:/opt/ckanext-dashboard_view/output/benchmarks:Z" \
  --entrypoint python pabrojast/ckan-base210:dashboard-view-20260909-rc1 \
  /opt/ckanext-dashboard_view/scripts/benchmark.py --rows 1000000
```

## Development deployment and public integration

On 2026-09-09, deployment `ckan/ckan` in Kubernetes context `default` completed successfully with **3/3 containers ready and zero restarts**. Image:

```text
pabrojast/ckan-base210:dashboard-view-20260909-rc3
sha256:d8b488a3233f7821b1bf318228d614fb75763af6c4841a5aa7bc27438490c7af
```

The deployment is pinned to that digest. Public JavaScript matched the final compiled workspace bytes; CSS, map worker and license notices returned HTTP 200. The shared cache has CKAN UID 92 and mode 0700. Both dedicated RQ workers completed actual jobs. The previous application remained available while the new readiness probe waited.

**19 HTTP integration checks passed against `https://data.dev-wins.com`.** In addition to the local checks, these exercised real Azure uploads and signed downloads, and verified that datashare's `viewable` policy allows metadata while denying dashboard queries and exports. The fixture was restored to public access after the permission tests. Report: `output/http/data.dev-wins.com.json`.

An existing, approved **CS UNESCO** CSV also passed preview-only profiling and aggregation: **2 rows, 51 columns, exact count 2**. No resource view was created or modified on that source. Report: `output/http/csunesco-preview.json`.

A separate, explicitly authored example within the synthetic QA dataset contains **20,000 rows**, eight blocks and median nitrate **4.29**. Anonymous queries returned every block without errors. Its embed responds with `frame-ancestors *` and no `X-Frame-Options`; the `/es/` route selects Spanish.

- [Public dashboard](https://data.dev-wins.com/es/dashboard/70441d68-3fa1-4e54-b7be-f87b6b27f515)
- [Embed](https://data.dev-wins.com/es/dashboard/70441d68-3fa1-4e54-b7be-f87b6b27f515/embed)

The example is clearly labelled synthetic and is not research data. Creation is reproducible using `scripts/create_demo.py` after the authorized dev HTTP fixture run. Deployment rollback patches are in `output/deploy/`; the initial rollback is `rollback-20260909T221716Z.json`. See installation instructions before a future infrastructure release, which must retain the plugin, workers and shared cache configuration.

The temporary administrative QA token was revoked after these checks, and its local token file was removed; retrying an authenticated action returned 403. No portal editor integration or production deployment was performed.

Final public browser checks passed with no authentication: 20,000 rows and eight blocks, desktop and 390 px mobile embeds without horizontal overflow. A parent page at `http://127.0.0.1:5188` successfully embedded the HTTPS dev dashboard with zero console errors or warnings. Basemap and observation markers were visually confirmed. Screenshots: `output/playwright/dev-public-embed-desktop-final.png`, `dev-public-embed-mobile-final.png`, `dev-cross-origin-desktop-final.png` and `dev-cross-origin-map-final.png`. The IHP site header has an existing desktop overflow outside the dashboard; the isolated embed has none.
