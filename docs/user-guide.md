# Create and share an IHP-WINS dashboard

## Create

1. Open a CSV, TSV, XLSX or DataStore resource in IHP-WINS.
2. Choose **Manage views → New view → Dashboard**. You need edit access to the dataset and permission to download its data.
3. Review the detected columns in **Data**. For Excel, select the worksheet. Correct number/date/text/boolean types if needed; identifiers such as `00123` should remain text. For CSV, you can also choose the delimiter, encoding, decimal separator and date format. For example, `%d/%m/%Y` interprets `31/01/2026` as 31 January. Ambiguous dates remain text until their interpretation is chosen.
4. Choose a suggested template or add blocks individually. Before applying a template, review the columns it will use and confirm the main variable. Applying a template replaces the current blocks; undo restores them.
5. Select a block and choose its title, columns and calculation under **Data**. Use **Appearance** for its unit and main color; additional controls are under **Advanced options**.
6. Drag its header to move it or resize its corner. The properties panel also has move and size buttons. With a block header focused, arrow keys move it, Shift+arrows resize it, and Delete removes it. Undo and redo are available.
7. Add shared category, date or number filters. Choose **Personalize** to set the dashboard theme and colors. Use **Review and save** and mobile preview to check the result.
8. Choose **Save dashboard**. If a selected column has disappeared or has an incompatible type, the editor highlights the field to correct before saving. Reopen the saved view to edit it later.

Uploading or updating a CSV does not automatically create a dashboard. Multiple dashboards can use the same resource.

The editor's four guide buttons help you return to the next task: **Review data → Choose blocks → Personalize → Review and save**. They are shortcuts, so you can revisit any step without losing your work. Edits remain unsaved until you choose **Save dashboard**.

## Personalize the appearance

Open **Personalize** and choose **IHP-WINS light**, **Ocean** or **Dark**. A preset applies coordinated starting colors. You can then adjust **Dashboard background**, **Block background** and **Accent color**, using the color picker or a six-digit hexadecimal color such as `#E8F3F8`.

Use **Chart palette** to choose IHP-WINS, Contrast or Monochrome. The palette controls multiple series and doughnut segments. A single-series chart uses the **Main color** configured on its block. Preview the colors against the chosen background; when a main color has low contrast, **Improve contrast** offers a more readable version. Text and interface controls adapt automatically to the background.

Changing a preset replaces the appearance settings. **Reset appearance** restores the IHP-WINS light defaults; **Undo** can recover the previous customization. These choices belong to the saved dashboard, not to your personal account or the surrounding IHP-WINS website. The saved appearance is used in the viewer, embeds, Story Studio and chart PNG downloads. Custom map base styles keep their own design.

Changing colors, titles or layout updates the presentation using the available results; it does not need a fresh data query. Changes to columns, calculations or filters update the results. Changing source interpretation requires preparing the data again. Keep the editor open while a source update finishes.

## Choose the right block

| Block | Typical use |
|---|---|
| Indicator | Total observations, distinct sites, average or median measurement, earliest/latest date |
| Line / area | Change over time, optionally grouped by day, month or year |
| Bar | Compare categories |
| Doughnut | Show proportions for a small set of categories |
| Scatter | Compare two numeric variables |
| Histogram | Explore a numeric distribution |
| Map | Locate observations using latitude and longitude columns |
| Table | Inspect selected columns and move between result pages |
| Text | Explain methodology, units, caveats or context |

Statistics use the filtered rows supplied by the source. If the source CSV already contains aggregated values, the dashboard does not reconstruct the original observations. Set clear titles and units to explain what a metric represents. A value that cannot be converted to its selected type is excluded from calculations and reported in a warning; its original text remains in CSV exports. Numeric overflow produces a block error instead of an incorrect statistic.

For an earliest or latest observation indicator, select the date column and **Minimum** or **Maximum**. Row count needs no value column. Distinct count can use text, dates, numbers or boolean values; average, median and sum require numeric columns. A time chart needs a date column when day, month or year grouping is enabled.

Large maps group locations and scatterplots may show a bounded sample. The interface marks these reductions; totals and aggregations still use all filtered rows. Category/series limits are also disclosed. Coordinates outside valid latitude/longitude ranges are excluded from the map, not from unrelated statistics.

## Explore and download

Shared filters update all blocks and the CSV export. **Active filters** shows your current selections; choose **Clear filters** to remove them. Selecting a chart category filters its original value, including an empty category. The same action is available with the keyboard in the chart's accessible data table. Selecting a day, month or year in a time chart filters that whole period. Dates are interpreted in UTC, and an end-date filter includes the entire selected day.

The map's **Filter by this map area** button applies the current extent; reset it from the active filter chip. With several maps, the coordinates of the map whose button you select determine the shared filter. This also applies to the CSV export.

Exports contain every source column for the filtered rows, including columns hidden in table blocks. They preserve original cell values; an apostrophe is added to formula-like text so spreadsheet applications treat it as text. Charts offer PNG download and an accessible data table.

The source is rechecked every five minutes while the dashboard is open. Editors can request a refresh. During revalidation, an existing dashboard can remain visible with its previous timestamp and an updating notice. A temporary source outage can retain that last completed update with a warning; access denial, a removed source, invalid replacement data or a corrupt cache prevent reuse. Source changes retain the layout; a deleted column or incompatible type identifies the affected block for correction.

## Embed

Open **Share**, copy the link or the iframe code, and set the height that fits the destination page. **The standard share link opens the original dashboard and does not include your current filters.** A Story Studio chapter can separately store its dashboard filter selection. A typical embed is:

```html
<iframe
  src="https://data.dev-wins.com/dashboard/VIEW_ID/embed"
  title="Citizen science observations"
  loading="lazy"
  style="width:100%;height:900px;border:0"
  allowfullscreen>
</iframe>
```

Replace `VIEW_ID` with the saved view's identifier, or use the generated code directly. The embedded version preserves the saved appearance, interactive filters and maps without the portal header or editing tools. A dashboard backed by a private resource still requires the appropriate access; sharing a link does not publish its data.

CS UNESCO already registers approved citizen-science exports as IHP-WINS resources. Use those CSV resources directly. Citizens4Water stores its files in a separate catalogue: first register its CSV or public download URL as an IHP-WINS resource, then create a Dashboard view there. An uploaded copy follows changes to that resource file; a registered URL can follow changes at the original source.

The destination must support iframes. This plugin provides the embed endpoint and code; it does not add dashboard selectors to Citizens4Water, CS Toolbox or CS UNESCO, and it does not override their content sanitizers.

## Try a complete example

The local demonstration in `scripts/dev_server.py` contains synthetic water observations with `date`, `country`, `site`, `nitrate`, `temperature`, `lat` and `lon` columns. To practise the editor without changing published dashboards:

1. In **Review data**, check that `date` is a date, `nitrate` and coordinates are numbers, and `country` is text.
2. In **Choose blocks**, apply **Over time** and choose `nitrate` as the main variable. Review the date and value columns in the template preview.
3. Give the trend a clear title such as “Monthly nitrate”; group by month and use median. Set the indicator's unit to `mg/L`.
4. Add a category filter for `country` and use it to compare selections. Open the trend's accessible data table to inspect values.
5. In **Personalize**, try Dark and then Ocean. For a custom light background, enter `#E8F3F8`; choose the Contrast palette for multiple series.
6. Preview at mobile width, save, reopen the dashboard and check that its appearance persists. Test a chart PNG and the iframe preview. Clear filters before comparing totals with the unfiltered dataset.

The development portal also provides a [Madagascar water-quality dashboard](https://data.dev-wins.com/dashboard/8980b544-e1b1-4631-99db-1d53fdee20e5). Public viewers can explore filters and chart data; editing requires dataset permissions. Use the saved view's Share control to obtain its current embed code.

## Supported limits

Defaults are 256 MiB per source file, five million rows and 500 columns. Excel expansion is limited to 1 GiB, with separate caps of 64 MiB for shared text metadata and 8 MiB for style metadata. If an otherwise small workbook exceeds a metadata limit, export its selected worksheet as CSV. CSV records are limited to 4 MiB. A file exceeding a processing limit produces an explicit error rather than silently discarding rows.

A dashboard supports up to 24 blocks and 12 shared filters. Category charts show up to 100 groups and eight series. Scatterplots display at most 2,000 sampled points; large maps aggregate all valid points into cells. Tables show 50 rows per page. Long table cells and chart labels are shortened for display, while CSV export retains their full values. Category selectors list up to 100 values and provide an entry field when more values are available; individual filter values are limited to 2,000 characters.

Administrators can adjust source, export and worker limits to their deployment capacity. The default export limit is 1 GiB. A query that exceeds its time or memory budget reports an error; narrowing filters or reducing the number of blocks may help.
