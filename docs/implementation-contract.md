# Implementation contract

CKAN 2.10, Python >=3.10. Plugin entry point `dashboard_view`. One CKAN resource per saved ResourceView. Never auto-create views. All agents own distinct files; communicate changes to this contract.

## Configuration

`dashboard_config` is a JSON object (native form stores JSON text) with:

```json
{"schema_version":1,"source":{"kind":"file","sheet":null,"delimiter":null,"encoding":null,"date_format":null,"decimal":".","types":{}},"widgets":[{"id":"w1","type":"bar","title":"Observations","x":0,"y":0,"w":6,"h":4,"x_field":"country","y_field":null,"series_field":null,"aggregate":"count","limit":20,"bins":20,"color":"#0069b4"}],"filters":[],"style":{"accent":"#0069b4"}}
```

Widget types: kpi,line,area,bar,doughnut,scatter,histogram,table,text,map. Additional widget properties: `lat_field`, `lon_field`, `columns` (string array), `text`, `unit`, `time_grain` (day/month/year/none), `sort` (asc/desc), `show_legend` boolean. Aggregates: count,count_distinct,sum,avg,median,min,max. Filters definitions `{field,type:category|number|date,label}`. Runtime filters `{field,op:in|eq|gte|lte|between,value}`; optional map bounds `{west,south,east,north,zoom,widget_id}`. `widget_id` identifies the map whose coordinate columns filter all blocks and the CSV export; omission preserves the first valid map for compatibility. Longitude bounds may cross the antimeridian (`west > east`). Grid is 12 columns, row height 72; widget height minimum 2, map 5, chart 4. Maximum 24 widgets, 12 filter definitions and 24 runtime conditions.

Dates normalize to UTC. A date-only upper bound (`YYYY-MM-DD`) with `lte` or `between` includes that entire UTC day; timestamp bounds retain their precise time. Filter values are parameterized scalars; `in` permits up to 100 values and strings are limited to 2,000 characters. Configuration and JSON request bodies are each limited to 256 KiB.

## Browser bootstrap and routes

All UI mounts via `[data-dashboard]` containing a child `script[type=application/json][data-dashboard-bootstrap]`. JSON bootstrap: `{mode:editor|view,resource_id,view_id,title,config,lang,api_base,view_url,embed_url,resource_url,basemap_url,can_edit}`. `api_base` is `/dashboard-api/resource/<resource_id>`; all internal URLs server-generated (locale aware). Editor renders hidden input `name=dashboard_config` in native CKAN form and synchronizes it. Viewer uses same renderer without edit controls. No hard dependency on C4W.

API JSON response envelope is plain (not CKAN action envelope), always has `status` ready|pending|error; HTTP 202 pending, 4xx/5xx errors with `message`, optional `code`. Browser POSTs JSON with CKAN CSRF header `X-CSRFToken` read from containing form or meta. Anonymous saved-view queries may POST without session CSRF, but no save/preview/refresh bypass. Every request reauthorizes resource/download access.

- `POST <api_base>/profile`: editor sends `{source}`; viewer sends `{view_id}`. Starts/deduplicates preparation. Ready returns `{status,generation,updated_at,rows,fields:[{key,label,type,examples,invalid_count?}],sheets:[],warnings:[]}`. Examples contain at most five values of 200 characters each. Poll by repeating the same request. Pending adds `message`.
- `POST <api_base>/query`: `{view_id,filters:[],bounds:null,pages:{widgetId:1}}`; editor instead `{config,filters,bounds,pages}`. Ready returns `{status,generation,updated_at,rows,results:{widgetId:...},warnings:[],facets:{field:[{value,count}]},ranges:{field:{min,max}},facets_truncated:[]}`. Config accepted ONLY for editors. Server batches widgets. Each facet/range excludes runtime conditions on its own field while respecting other filters and map bounds. Category facets contain at most 100 values; overlong values are omitted and disclosed through `facets_truncated`.
- `POST <api_base>/refresh`: editor-only `{source}` or `{view_id}`. Forces revalidation. Returns pending when no usable generation exists, or the previous ready profile with `refreshing:true` and a warning while its replacement is prepared.
- `POST <api_base>/export`: same selectors, filters and bounds as query; streams filtered CSV when ready (or pending JSON). Browser must handle pending/retry. All original source columns are exported, independently of visible table columns, with spreadsheet formula defense.
- `GET /dashboard/<view_id>` and `/dashboard/<view_id>/embed`: stable public/read-authorized view routes. Sharing does not grant access.

Result shapes per widget: `kpi: {type,value,count}`; categorical/time charts and histograms `{type,labels:[],datasets:[{label,data:[]}],count}`; scatter `{type,datasets:[{label,data:[{x,y}]}],count,sampled:false}`; table `{type,columns:[{key,label}],rows:[{field:value}],total,page,page_size}`; map `{type,points:[{lat,lon,value,count}],count,aggregated:false}`; text `{type,text}`; unavailable widget `{type,error,code}`. Maps, scatterplots and histograms also return `valid_count`, counting rows with usable coordinates/numbers. Reduction metadata includes `truncated`, `sampled`, `aggregated` and `text_truncated` where applicable.

Categorical/time chart results include `category_filters`, parallel to `labels`. Each entry is an exact runtime filter or `null` when clicking is unavailable. Use this value for interactions; display labels can represent nulls or shortened text. Empty categories return an `eq` filter with `value:null`; temporal buckets return inclusive `between` dates for their day/month/year. Original category strings longer than 2,000 characters are noninteractive.

An existing generation can remain ready during revalidation, with `refreshing:true` and a warning. Temporary source failures may return the last completed generation with `refreshing:false` and a warning. Its `updated_at` remains the last successful data update. Access denial, deleted sources, invalid replacement data and corrupt caches block reuse. Every response still enforces current resource/download authorization.

## Output and processing bounds

- Category charts show at most 100 groups (default 20) and eight series. Scatterplots return a seeded reservoir sample of at most 2,000 valid points; extra series are combined into a disclosed additional series.
- Maps return at most 2,000 original valid points, or aggregate all valid rows into a bounded spatial grid. Cell statistics are calculated directly from their source rows. Histograms allow 2–100 configured bins, reducing to one for a constant value or an unrepresentably small interval.
- Tables contain 50 rows per page. Displayed text cells are shortened after 2,000 characters, chart labels after 512 characters; originals remain available in export. Text blocks permit 10,000 characters.
- Source defaults: 256 MiB, 5,000,000 rows, 500 columns. CSV record parsing is bounded to 4 MiB. XLSX expansion is limited to 1 GiB; shared text metadata to 64 MiB and style metadata to 8 MiB. External workbook links are not loaded. These separate XLSX safeguards apply even to small compressed archives.
- DuckDB preparation defaults to a `1GB` engine memory setting and two threads; query/export connections use `768MB` and two threads. These settings do not replace container memory limits. The engine interrupts a dashboard query after 45 seconds and an export after 120 seconds; the deployment's RQ timeout may impose a shorter limit. The service defaults to a 1 GiB CSV export limit.

## Pure engine API (owned by engine agent)

`schema.normalize_config(value, allow_empty=False) -> dict` raises ValueError with user-safe detail. `schema.normalize_source(value) -> dict`. `schema.validate_filters(filters, fields) -> list`.

`engine.prepare_table(input_path, output_path, source=None, format_hint='csv', limits=None) -> profile dict`: create a standalone DuckDB database at a new output path, preserving original text rows separately from interpreted data; no CKAN imports. Existing generations are never overwritten and failed builds remove their partial database. Source kinds are irrelevant once materialized; the service forces UTF-8/comma interpretation for its DataStore CSV snapshots. Engine uses openpyxl streaming for XLSX. Profile is JSON serializable. Limits dict defaults: `max_rows=5000000,max_columns=500,max_bytes=268435456,memory_limit='1GB',threads=2,max_xlsx_uncompressed_bytes=1073741824`.

`engine.query_table(db_path, config, filters=None, bounds=None, pages=None) -> {rows,results,warnings,facets,ranges,facets_truncated}`. `engine.export_csv(db_path, config, filters=None, bounds=None) -> iterator of UTF-8 byte chunks` (all original filtered columns, Excel injection defense). `engine.inspect_file(input_path, source=None, format_hint='csv') -> {sheets,...}`. Schema types text|number|date|boolean. Type inference samples up to 1,000 rows; conversion-loss counts and statistics use the complete table. Invalid typed values become null with warnings while their original text remains exportable. Missing/incompatible widget columns produce individual block errors; invalid shared filters reject the query.

## Service (backend agent)

Materializes authorized CKAN uploaded resources or registered HTTP(S) resource URLs. SSRF protection, redirects, time/byte limits and complete-response checks; never accepts client URLs or arbitrary SQL. DataStore reads an authorized repeatable-read snapshot via a read-only database connection and batches to CSV. Builds immutable cache DB/profile with atomic publication; Redis locks/job states and queue `dashboard-build`, query work queue `dashboard-query`. Local shared cache root configurable. Tasks recheck actor permissions; no token persistence. Query results are keyed by source generation/config/filters/bounds/pages/actor and export mode. Cache refresh defaults to 300 seconds. Access denial invalidates reusable results; cache filesystem is private and browser responses use private/no-store.

Worker CLI `ckan dashboard worker --queue build|query`, initialized once with CKAN, RQ worker pattern from c4w without runtime dependency. Local development harness can execute pure engine synchronously; deployed requests enqueue costly work. Read-only processing state GET/POST never writes ResourceView or creates dashboards.
