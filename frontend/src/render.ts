import { Chart, registerables, type ChartConfiguration } from 'chart.js';
import {
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  LngLatBounds,
  setWorkerUrl,
  type GeoJSONSource,
} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { Bounds, Result, Widget, Filter } from './types';
import { serverMessage, type Translator } from './i18n';
import { button, el } from './dom';
import { basemapStyle, updateBasemapAppearance } from './maps/basemap';
import { resolveAppearance, correctChartColor, type ResolvedAppearance } from './appearance';
Chart.register(...registerables);
setWorkerUrl(workerUrl);
export interface Handle {
  destroy: () => void;
  resize: () => void;
  png?: () => string;
  updateAppearance?: (appearance: ResolvedAppearance, widget?: Widget) => void;
}
export interface RenderContext {
  t: Translator;
  locale: string;
  basemap?: string;
  appearance?: ResolvedAppearance;
  filter: (filter: Filter) => void;
  bounds: (bounds: Bounds) => void;
  page: (page: number) => void;
}
/** The canvas and its keyboard-accessible table must use the same typed filter. */
export function chartFilterAt(widget: Widget, result: Result, index: number): Filter | undefined {
  if (widget.type === 'scatter' || widget.type === 'histogram') return;
  if (result.category_filters) return result.category_filters[index] ?? undefined;
  if (!widget.x_field || (widget.time_grain && widget.time_grain !== 'none')) return;
  const labels = result.labels ?? [];
  if (index < 0 || index >= labels.length) return;
  return { field: widget.x_field, op: 'eq', value: labels[index] };
}
function primaryColor(widget: Widget, appearance: ResolvedAppearance): string {
  // Preserve legacy white-card colors; custom/dark backgrounds need legible marks.
  return appearance.cardBackground.toLowerCase() === '#ffffff' && appearance.theme === 'light'
    ? widget.color
    : correctChartColor(widget.color, appearance.cardBackground);
}
function formatLabel(value: unknown, widget: Widget, locale: string) {
  if (widget.time_grain && widget.time_grain !== 'none' && typeof value === 'string') {
    const date = new Date(value);
    if (Number.isFinite(date.getTime()))
      return new Intl.DateTimeFormat(locale, {
        timeZone: 'UTC',
        year: 'numeric',
        month: widget.time_grain === 'year' ? undefined : 'short',
        day: widget.time_grain === 'day' ? 'numeric' : undefined,
      }).format(date);
  }
  return String(value ?? '—');
}
function number(value: unknown, locale: string) {
  return typeof value === 'number'
    ? new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value)
    : value == null
      ? '—'
      : String(value);
}
export function renderWidget(
  container: HTMLElement,
  widget: Widget,
  result: Result | undefined,
  ctx: RenderContext,
): Handle {
  const { t } = ctx;
  let appearance = ctx.appearance ?? resolveAppearance({ accent: '#0069b4' });
  container.replaceChildren();
  const noop = { destroy: () => {}, resize: () => {} };
  if (result?.error) {
    const state = el('div', 'dbv-block-state');
    state.append(el('strong', '', t('warning')), el('p', '', serverMessage(result.error, t, result.code)));
    container.append(state);
    return noop;
  }
  if (widget.type === 'text') {
    const text = el('div', 'dbv-text-content', widget.text || t('textPlaceholder'));
    container.append(text);
    return {
      ...noop,
      updateAppearance: (_appearance, next = widget) => {
        widget = next;
        text.textContent = widget.text || t('textPlaceholder');
      },
    };
  }
  if (!result) {
    const state = el('div', 'dbv-block-state');
    state.append(el('span', 'dbv-spinner'), el('span', '', t('loadingChart')));
    container.append(state);
    return noop;
  }
  if (widget.type === 'kpi') {
    const wrapper = el('div', 'dbv-kpi');
    wrapper.style.setProperty('--kpi-color', primaryColor(widget, appearance));
    wrapper.append(
      el('div', 'dbv-kpi-value', number(result.value, ctx.locale)),
      el('span', 'dbv-kpi-unit', widget.unit || ''),
      el(
        'p',
        'dbv-kpi-context',
        `${t(widget.aggregate)}${widget.y_field ? ' · ' + widget.y_field : ''}`,
      ),
    );
    container.append(wrapper);
    return {
      ...noop,
      updateAppearance: (nextAppearance, next = widget) => {
        widget = next;
        appearance = nextAppearance;
        wrapper.style.setProperty('--kpi-color', primaryColor(widget, appearance));
        wrapper.querySelector('.dbv-kpi-unit')!.textContent = widget.unit || '';
      },
    };
  }
  if (widget.type === 'table') {
    const scroll = el('div', 'dbv-table-scroll');
    scroll.append(dataTable(result.columns ?? [], result.rows ?? [], ctx));
    container.append(scroll);
    const page = result.page ?? 1,
      total = result.total ?? 0,
      pageSize = result.page_size ?? 50,
      pages = Math.max(1, Math.ceil(total / pageSize));
    const nav = el('div', 'dbv-pagination');
    const prev = button(t('previous'), () => ctx.page(page - 1), 'dbv-btn dbv-icon-only', 'left');
    prev.disabled = page <= 1;
    const next = button(t('next'), () => ctx.page(page + 1), 'dbv-btn dbv-icon-only', 'right');
    next.disabled = page >= pages;
    nav.append(
      el('span', '', `${number(total, ctx.locale)} ${t('rows')}`),
      prev,
      el('span', '', `${t('page')} ${page} ${t('of')} ${pages}`),
      next,
    );
    container.append(nav);
    if (!total) container.prepend(el('p', 'dbv-muted', t('emptyResults')));
    return noop;
  }
  if (widget.type === 'map') return renderMap(container, widget, result, ctx);
  const datasets = (result.datasets ?? []).map((dataset) => ({
    ...dataset,
    label: !widget.series_field && widget.title ? widget.title : dataset.label,
  })),
    labels = result.labels ?? [];
  if (!datasets.length || !datasets.some((d) => d.data.length)) {
    container.append(el('div', 'dbv-block-state', t('emptyResults')));
    return noop;
  }
  let renderedTitle = widget.title;
  const chartBox = el('div', 'dbv-chart');
  const canvas = el('canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', widget.title);
  chartBox.append(canvas);
  container.append(chartBox);
  const type = widget.type === 'area' ? 'line' : widget.type === 'histogram' ? 'bar' : widget.type;
  const config: ChartConfiguration = {
    type,
    data: {
      labels: labels.map((v) => formatLabel(v, widget, ctx.locale)),
      datasets: datasets.map((ds, i) => ({
        label: ds.label,
        data: ds.data,
        borderColor:
          i === 0 ? primaryColor(widget, appearance) : appearance.palette[i % appearance.palette.length],
        backgroundColor:
          type === 'doughnut'
            ? labels.map((_, j) => appearance.palette[j % appearance.palette.length])
            : widget.type === 'area'
              ? (i === 0
                  ? primaryColor(widget, appearance)
                  : appearance.palette[i % appearance.palette.length]) + '26'
              : i === 0
                ? primaryColor(widget, appearance)
                : appearance.palette[i % appearance.palette.length],
        borderWidth: type === 'doughnut' ? 2 : type === 'line' ? 2.4 : 0,
        pointRadius: type === 'scatter' ? 3 : type === 'line' ? 2 : 0,
        pointHoverRadius: 5,
        fill: widget.type === 'area',
        tension: 0.25,
        borderRadius: type === 'bar' ? 4 : undefined,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      locale: ctx.locale,
      plugins: {
        legend: {
          display: widget.show_legend !== false && (datasets.length > 1 || type === 'doughnut'),
          position: 'bottom',
          labels: {
            boxWidth: 10, boxHeight: 10, usePointStyle: true,
            color: appearance.cardInk, font: { size: 12 },
          },
        },
        tooltip: { padding: 10, backgroundColor: '#143144', cornerRadius: 8 },
      },
      scales:
        type === 'doughnut'
          ? undefined
          : {
              x: {
                type: type === 'scatter' ? 'linear' : 'category',
                grid: { display: false },
                border: { display: false },
                ticks: {
                  maxRotation: 0, maxTicksLimit: 9, color: appearance.cardMuted, font: { size: 11 },
                },
              },
              y: {
                beginAtZero: type !== 'scatter',
                title: {
                  display: !!widget.unit,
                  text: widget.unit,
                  color: appearance.cardMuted,
                  font: { size: 10 },
                },
                grid: { color: appearance.line },
                border: { display: false },
                ticks: { maxTicksLimit: 6, color: appearance.cardMuted, font: { size: 11 } },
              },
            },
      onClick: (_event, elements) => {
        const index = elements[0]?.index;
        if (index === undefined) return;
        const filter = chartFilterAt(widget, result, index);
        if (filter) ctx.filter(filter);
      },
      onHover: (event, elements) => {
        if (event.native?.target instanceof HTMLCanvasElement)
          event.native.target.style.cursor =
            elements.length && chartFilterAt(widget, result, elements[0].index)
              ? 'pointer'
              : 'default';
      },
    },
  };
  const chart = new Chart(canvas, config);
  if (
    result.valid_count !== undefined &&
    result.count !== undefined &&
    result.valid_count < result.count
  )
    container.append(
      el(
        'p',
        'dbv-reduction',
        `${number(result.valid_count, ctx.locale)} / ${number(result.count, ctx.locale)} · ${t('validRows')}`,
      ),
    );
  if (result.sampled || result.truncated)
    container.append(el('p', 'dbv-reduction', t(result.sampled ? 'sampled' : 'truncated')));
  const accessible = el('details', 'dbv-chart-data');
  accessible.append(el('summary', '', t('viewData')));
  const columns = [
    { key: 'label', label: widget.x_field || t('selection') },
    ...datasets.map((ds, i) => ({ key: String(i), label: ds.label })),
  ];
  const rows = labels.map((label, index) =>
    Object.fromEntries([
      ['label', label],
      ...datasets.map((ds, i) => [
        String(i),
        typeof ds.data[index] === 'object' ? JSON.stringify(ds.data[index]) : ds.data[index],
      ]),
    ]),
  );
  if (type === 'scatter') {
    columns.splice(
      0,
      columns.length,
      { key: 'series', label: t('series_field') },
      { key: 'x', label: widget.x_field || 'X' },
      { key: 'y', label: widget.y_field || 'Y' },
    );
    rows.splice(
      0,
      rows.length,
      ...datasets.flatMap((ds) => ds.data.map((p) => ({ series: ds.label, x: p.x, y: p.y }))),
    );
  }
  accessible.append(dataTable(
    columns, rows, ctx,
    rows.some((_, index) => chartFilterAt(widget, result, index))
      ? (index) => chartFilterAt(widget, result, index)
      : undefined,
  ));
  container.append(accessible);
  return {
    destroy: () => chart.destroy(),
    resize: () => chart.resize(),
    updateAppearance: (nextAppearance, next = widget) => {
      const titleChanged = renderedTitle !== next.title;
      renderedTitle = next.title;
      appearance = nextAppearance;
      widget = next;
      if (titleChanged && !widget.series_field && chart.data.datasets.length === 1) {
        const label = widget.title || t(widget.type === 'histogram' ? 'count' : widget.aggregate);
        chart.data.datasets[0].label = label;
        if (type === 'scatter') {
          accessible.querySelectorAll('tbody tr').forEach((row) => {
            if (row.firstElementChild) row.firstElementChild.textContent = label;
          });
        } else {
          const header = accessible.querySelectorAll('thead th')[1];
          if (header) header.textContent = label;
        }
      }
      canvas.setAttribute('aria-label', widget.title);
      chart.data.datasets.forEach((dataset, i) => {
        const color = i === 0
          ? primaryColor(widget, appearance)
          : appearance.palette[i % appearance.palette.length];
        dataset.borderColor = color;
        dataset.backgroundColor = type === 'doughnut'
          ? labels.map((_, j) => appearance.palette[j % appearance.palette.length])
          : widget.type === 'area' ? color + '26' : color;
      });
      const legend = chart.options.plugins?.legend;
      if (legend) {
        legend.display = widget.show_legend !== false && (datasets.length > 1 || type === 'doughnut');
        if (legend.labels) legend.labels.color = appearance.cardInk;
      }
      for (const [axis, scale] of Object.entries(chart.options.scales ?? {})) {
        if (!scale) continue;
        if (scale.ticks) scale.ticks.color = appearance.cardMuted;
        if (scale.grid) scale.grid.color = appearance.line;
        if (axis === 'y' && 'title' in scale && scale.title) {
          scale.title.color = appearance.cardMuted;
          scale.title.text = widget.unit || '';
          scale.title.display = !!widget.unit;
        }
      }
      chart.update('none');
    },
    png: () => {
      const scale = canvas.width / (canvas.clientWidth || canvas.width);
      const padding = 20 * scale;
      const heading = 40 * scale;
      const exported = document.createElement('canvas');
      exported.width = canvas.width + padding * 2;
      exported.height = canvas.height + heading + padding * 2;
      const painter = exported.getContext('2d')!;
      painter.fillStyle = appearance.cardBackground;
      painter.fillRect(0, 0, exported.width, exported.height);
      painter.fillStyle = appearance.cardInk;
      painter.font = `600 ${16 * scale}px system-ui, sans-serif`;
      painter.fillText(widget.title, padding, padding + 17 * scale, canvas.width);
      painter.drawImage(canvas, padding, padding + heading);
      return exported.toDataURL('image/png');
    },
  };
}
function dataTable(
  columns: { key: string; label: string }[],
  rows: Record<string, unknown>[],
  ctx: RenderContext,
  rowFilter?: (index: number) => Filter | undefined,
) {
  const table = el('table', 'dbv-table');
  const head = el('thead'),
    tr = el('tr');
  columns.forEach((c) => {
    const th = el('th', '', c.label);
    th.scope = 'col';
    tr.append(th);
  });
  if (rowFilter) {
    const th = el('th', '', ctx.t('filterAction'));
    th.scope = 'col';
    tr.append(th);
  }
  head.append(tr);
  table.append(head);
  const body = el('tbody');
  for (const [index, row] of rows.entries()) {
    const tr = el('tr');
    for (const column of columns) tr.append(el('td', '', number(row[column.key], ctx.locale)));
    if (rowFilter) {
      const cell = el('td');
      const filter = rowFilter(index);
      if (filter) {
        const action = button(ctx.t('filterAction'), () => ctx.filter(filter), 'dbv-btn dbv-btn-small', 'filter');
        action.setAttribute('aria-label', `${ctx.t('filterAction')}: ${String(row[columns[0].key] ?? ctx.t('emptyValue'))}`);
        cell.append(action);
      }
      tr.append(cell);
    }
    body.append(tr);
  }
  table.append(body);
  return table;
}
function renderMap(
  container: HTMLElement,
  widget: Widget,
  result: Result,
  ctx: RenderContext,
): Handle {
  const noop = { destroy: () => {}, resize: () => {} };
  let appearance = ctx.appearance ?? resolveAppearance({ accent: '#0069b4' });
  const mapColor = () => primaryColor(widget, appearance);
  const lowColor = () => appearance.theme === 'dark' ? '#567e96' : '#b4dce9';
  const points = (result.points ?? []).filter(
    (p) => Number.isFinite(p.lat) && Number.isFinite(p.lon),
  );
  if (!points.length) {
    container.append(el('div', 'dbv-block-state', ctx.t('emptyResults')));
    return noop;
  }
  const mapDiv = el('div', 'dbv-map');
  container.append(mapDiv);
  let map: MapLibreMap;
  try {
    map = new MapLibreMap({
      container: mapDiv,
      style: basemapStyle(ctx.basemap, appearance.theme === 'dark'),
      center: [0, 20],
      zoom: 1,
      pitch: 0,
      maxPitch: 0,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
      locale: {
        'NavigationControl.ZoomIn': ctx.t('mapZoomIn'),
        'NavigationControl.ZoomOut': ctx.t('mapZoomOut'),
        'AttributionControl.ToggleAttribution': ctx.t('mapToggleAttribution'),
      },
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
  } catch {
    container.replaceChildren(el('div', 'dbv-block-state', ctx.t('mapUnavailable')));
    return noop;
  }
  const bounds = new LngLatBounds();
  points.forEach((p) => bounds.extend([p.lon, p.lat]));
  const fit = () => map.fitBounds(bounds, { padding: 45, maxZoom: 11, duration: 0 });
  const bar = el('div', 'dbv-map-bar');
  const apply = button(
    ctx.t('mapFilter'),
    () => {
      const b = map.getBounds();
      const world = b.getEast() - b.getWest() >= 360;
      const wrap = (longitude: number) => ((((longitude + 180) % 360) + 360) % 360) - 180;
      ctx.bounds({
        widget_id: widget.id,
        west: world ? -180 : wrap(b.getWest()),
        south: Math.max(-90, b.getSouth()),
        east: world ? 180 : wrap(b.getEast()),
        north: Math.min(90, b.getNorth()),
        zoom: map.getZoom(),
      });
    },
    'dbv-btn dbv-btn-small',
    'filter',
  );
  bar.append(apply, button(ctx.t('fitMap'), fit, 'dbv-btn dbv-icon-only', 'map'));
  container.append(bar);
  const values = points
    .map((p) => p.value)
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  const lo = values.length ? Math.min(...values) : 0,
    hi = values.length ? Math.max(...values) : 0;
  const legend = el('div', 'dbv-map-legend');
  const swatch = el('span', 'dbv-map-swatch');
  const legendLabel = el('span');
  const updateLegend = () => {
    legend.hidden = widget.show_legend === false;
    swatch.style.background = hi > lo
      ? `linear-gradient(90deg,${lowColor()},${mapColor()})` : mapColor();
    legendLabel.textContent = hi > lo
      ? `${number(lo, ctx.locale)} – ${number(hi, ctx.locale)} ${widget.unit || ''}`
      : ctx.t('mapCount');
  };
  updateLegend();
  legend.append(swatch, legendLabel);
  if (
    result.valid_count !== undefined &&
    result.count !== undefined &&
    result.valid_count < result.count
  )
    legend.append(
      el(
        'small',
        '',
        `${number(result.valid_count, ctx.locale)} / ${number(result.count, ctx.locale)} · ${ctx.t('validRows')}`,
      ),
    );
  if (result.aggregated) legend.append(el('small', '', ctx.t('mapCluster')));
  container.append(legend);
  map.once('style.load', () => {
    map.addSource('observations', {
      type: 'geojson',
      cluster: true,
      clusterProperties: { observations: ['+', ['get', 'count']] },
      clusterMaxZoom: 12,
      clusterRadius: 32,
      data: {
        type: 'FeatureCollection',
        features: points.map((p) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
          properties: { value: p.value ?? null, count: p.count ?? 1 },
        })),
      },
    });
    map.addLayer({
      id: 'clusters',
      type: 'circle',
      source: 'observations',
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': mapColor(),
        'circle-radius': ['step', ['get', 'point_count'], 15, 50, 21, 200, 27],
        'circle-stroke-width': 2,
        'circle-stroke-color': appearance.cardBackground,
        'circle-opacity': 0.9,
      },
    });
    map.addLayer({
      id: 'points',
      type: 'circle',
      source: 'observations',
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color':
          hi > lo
            ? [
                'case',
                ['==', ['get', 'value'], null],
                '#94a3b8',
                [
                  'interpolate',
                  ['linear'],
                  ['number', ['get', 'value'], lo],
                  lo,
                  lowColor(),
                  hi,
                  mapColor(),
                ],
              ]
            : mapColor(),
        'circle-radius': 6,
        'circle-opacity': 0.85,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': appearance.cardBackground,
      },
    });
    for (const layer of ['points', 'clusters']) {
      map.on('mouseenter', layer, () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', layer, () => {
        map.getCanvas().style.cursor = '';
      });
      map.on('click', layer, (event) => {
        const feature = event.features?.[0];
        if (!feature || feature.geometry.type !== 'Point') return;
        if (layer === 'clusters') {
          void (map.getSource('observations') as GeoJSONSource)
            .getClusterExpansionZoom(Number(feature.properties?.cluster_id))
            .then((zoom) =>
              map.easeTo({
                center:
                  feature.geometry.type === 'Point'
                    ? (feature.geometry.coordinates.slice(0, 2) as [number, number])
                    : event.lngLat,
                zoom,
              }),
            );
          return;
        }
        const content = el('div', 'dbv-map-popup');
        content.append(
          el(
            'strong',
            '',
            ctx.t('mapCount') +
              ': ' +
              number(feature.properties?.observations ?? feature.properties?.count, ctx.locale),
          ),
        );
        if (feature.properties?.value != null)
          content.append(
            el(
              'p',
              '',
              ctx.t('mapValue') +
                ': ' +
                number(feature.properties.value, ctx.locale) +
                ' ' +
                (widget.unit || ''),
            ),
          );
        content.append(
          el('small', '', feature.geometry.coordinates.map((v: number) => v.toFixed(4)).join(', ')),
        );
        new Popup().setLngLat(event.lngLat).setDOMContent(content).addTo(map);
      });
    }
    updateBasemapAppearance(map, ctx.basemap, appearance.theme === 'dark');
    fit();
  });
  let errors = 0;
  map.on('error', () => {
    if (++errors === 1) mapDiv.setAttribute('aria-label', ctx.t('mapUnavailable'));
  });
  const observer = new ResizeObserver(() => map.resize());
  observer.observe(mapDiv);
  return {
    destroy: () => {
      observer.disconnect();
      map.remove();
    },
    resize: () => map.resize(),
    updateAppearance: (nextAppearance, next = widget) => {
      appearance = nextAppearance;
      widget = next;
      updateLegend();
      if (!map.getLayer('points')) return;
      updateBasemapAppearance(map, ctx.basemap, appearance.theme === 'dark');
      if (map.getLayer('clusters')) {
        map.setPaintProperty('clusters', 'circle-color', mapColor());
        map.setPaintProperty('clusters', 'circle-stroke-color', appearance.cardBackground);
      }
      if (map.getLayer('points')) {
        map.setPaintProperty('points', 'circle-color', hi > lo
          ? ['case', ['==', ['get', 'value'], null], '#94a3b8',
            ['interpolate', ['linear'], ['number', ['get', 'value'], lo], lo, lowColor(), hi, mapColor()]]
          : mapColor());
        map.setPaintProperty('points', 'circle-stroke-color', appearance.cardBackground);
      }
    },
  };
}
