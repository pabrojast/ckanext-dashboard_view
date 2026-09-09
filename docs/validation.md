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

Final integration and deployment results: pending their separate checks.
