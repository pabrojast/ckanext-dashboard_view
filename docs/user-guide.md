# Create and share a dashboard

## Create

1. Open a CSV, TSV, XLSX or DataStore resource in CKAN.
2. Choose **Manage views → New view → Dashboard**. You need edit access to the dataset and permission to download its data.
3. Review the detected columns in **Data**. For Excel, select the worksheet. Correct number/date/text/boolean types if needed; identifiers such as `00123` should remain text. For CSV, you can also choose the delimiter, encoding, decimal separator and date format. For example, `%d/%m/%Y` interprets `31/01/2026` as 31 January. Ambiguous dates remain text until their interpretation is chosen.
4. Choose a suggested template or add blocks individually.
5. Select a block and choose its columns, aggregation, title, units and colors.
6. Drag its header to move it or resize its corner. The properties panel also has move and size buttons. With a block header focused, arrow keys move it, Shift+arrows resize it, and Delete removes it. Undo and redo are available.
7. Add shared category, date or number filters. Use the preview and mobile preview before saving.
8. Choose **Save dashboard**. Reopen the saved view to edit it later.

Uploading or updating a CSV does not automatically create a dashboard. Multiple dashboards can use the same resource.

## Choose the right block

| Block | Typical use |
|---|---|
| Indicator | Total observations, distinct sites, average or median measurement |
| Line / area | Change over time, optionally grouped by day, month or year |
| Bar | Compare categories |
| Doughnut | Show proportions for a small set of categories |
| Scatter | Compare two numeric variables |
| Histogram | Explore a numeric distribution |
| Map | Locate observations using latitude and longitude columns |
| Table | Inspect selected columns and move between result pages |
| Text | Explain methodology, units, caveats or context |

Statistics use the filtered rows supplied by the source. If the source CSV already contains aggregated values, the dashboard does not reconstruct the original observations. Set clear titles and units to explain what a metric represents. A value that cannot be converted to its selected type is excluded from calculations and reported in a warning; its original text remains in CSV exports. Numeric overflow produces a block error instead of an incorrect statistic.

Large maps group locations and scatterplots may show a bounded sample. The interface marks these reductions; totals and aggregations still use all filtered rows. Category/series limits are also disclosed. Coordinates outside valid latitude/longitude ranges are excluded from the map, not from unrelated statistics.

## Explore and download

Shared filters update all blocks. Selecting a chart category filters its original value, including an empty category. Selecting a day, month or year in a time chart filters that whole period. Dates are interpreted in UTC, and an end-date filter includes the entire selected day.

The map's **Filter by this map area** button applies the current extent; reset it from the active filter chip. With several maps, the coordinates of the map whose button you select determine the shared filter. This also applies to the CSV export.

Exports contain every source column for the filtered rows, including columns hidden in table blocks. They preserve original cell values; an apostrophe is added to formula-like text so spreadsheet applications treat it as text. Charts offer PNG download and an accessible data table.

The source is rechecked every five minutes while the dashboard is open. Editors can request a refresh. During revalidation, an existing dashboard can remain visible with its previous timestamp and an updating notice. A temporary source outage can retain that last completed update with a warning; access denial, a removed source, invalid replacement data or a corrupt cache prevent reuse. Source changes retain the layout; a deleted column or incompatible type identifies the affected block for correction.

## Embed

Open **Share**, copy the link or the iframe code, and set the height that fits the destination page. A typical embed is:

```html
<iframe
  src="https://data.dev-wins.com/dashboard/VIEW_ID/embed"
  title="Citizen science observations"
  loading="lazy"
  style="width:100%;height:900px;border:0"
  allowfullscreen>
</iframe>
```

Replace `VIEW_ID` with the saved view's identifier, or use the generated code directly. The embedded version preserves interactive filters and maps without the CKAN portal header or editing tools.

CS UNESCO already registers approved citizen-science exports as CKAN resources. Use those CSV resources directly. Citizens4Water stores its files in a separate catalogue: first register its CSV or public download URL as a CKAN resource, then create a Dashboard view there. An uploaded copy follows changes to that CKAN file; a registered URL can follow changes at the original source.

The destination must support iframes. This plugin provides the embed endpoint and code; it does not add dashboard selectors to Citizens4Water, CS Toolbox or CS UNESCO, and it does not override their content sanitizers.

## Supported limits

Defaults are 256 MiB per source file, five million rows and 500 columns. Excel expansion is limited to 1 GiB, with separate caps of 64 MiB for shared text metadata and 8 MiB for style metadata. If an otherwise small workbook exceeds a metadata limit, export its selected worksheet as CSV. CSV records are limited to 4 MiB. A file exceeding a processing limit produces an explicit error rather than silently discarding rows.

A dashboard supports up to 24 blocks and 12 shared filters. Category charts show up to 100 groups and eight series. Scatterplots display at most 2,000 sampled points; large maps aggregate all valid points into cells. Tables show 50 rows per page. Long table cells and chart labels are shortened for display, while CSV export retains their full values. Category selectors list up to 100 values and provide an entry field when more values are available; individual filter values are limited to 2,000 characters.

Administrators can adjust source, export and worker limits to their deployment capacity. The default export limit is 1 GiB. A query that exceeds its time or memory budget reports an error; narrowing filters or reducing the number of blocks may help.
