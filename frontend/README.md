# Dashboard editor and viewer

The TypeScript entry point mounts every `[data-dashboard]` element with an embedded
`script[data-dashboard-bootstrap]` JSON bootstrap. It reuses the enclosing CKAN
form's `dashboard_config` hidden input and submits the native resource-view form.
The viewer shares the chart, table, map and filtering renderer.

```sh
npm ci
npm run build
```

Use Node 22.12 or newer. Locked versions are checked in. The production build emits
`dashboard.js`, `dashboard.css` and a standalone `dashboard-worker.js` under
`../ckanext/dashboard_view/public/dashboard/`. CKAN serves these through
`/dashboard-static/`; runtime libraries and the map worker are local assets.
Only the configured map style can request external basemap data.

For frontend development, start `scripts/dev_server.py` on port 5188 as described
in the project README, then run `npm run dev -- --port 5190`. Open
`http://127.0.0.1:5190/dashboard-static/?lang=es` (`en` and `fr` are also supported).
Use `?empty=1` for manual creation and `?mode=view` for viewer-only rendering.
This development harness talks to the real DuckDB engine and synthetic CSV source;
it is excluded from the production build. Saving opens the Python harness's
persisted dashboard.

Layout editing uses a 12-column GridStack canvas. Drag a block header or resize its
corner; keyboard-focused headers support arrow keys, Shift+arrows, Delete, and
Ctrl/Cmd+D. Undo and redo keep the serialized CKAN form configuration synchronized.
Mobile and tablet properties open as a drawer; preview stacks blocks without
changing their saved desktop coordinates.

Runtime filters are separate from saved filter definitions. Categorical chart
clicks use the server's typed `category_filters`, including date intervals and null
values. Map selection sends `bounds.widget_id`. The client requests aggregates,
pages and spatial summaries; it never downloads whole source files to plot them.
Exports request filtered CSV from the server. Chart values are available through
accessible data tables, and charts can be downloaded as PNG.

Browser validation artifacts are written to the repository's ignored
`output/playwright/` directory. They cover real API data, CSV content, PNG, drag
and drop, keyboard resize, history, save/reload, sharing, ES/EN/FR and 390px mobile
editor/viewer layouts.
