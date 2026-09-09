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
import type { Translator } from './i18n';
import { button, el } from './dom';
Chart.register(...registerables);
setWorkerUrl(workerUrl);
export interface Handle {
  destroy: () => void;
  resize: () => void;
  png?: () => string;
}
export interface RenderContext {
  t: Translator;
  locale: string;
  basemap?: string;
  filter: (filter: Filter) => void;
  bounds: (bounds: Bounds) => void;
  page: (page: number) => void;
}
const palette = [
  '#0069b4',
  '#00a5b5',
  '#755fbe',
  '#e29a36',
  '#48977b',
  '#cf688a',
  '#6393cd',
  '#7f8e9f',
];
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
  container.replaceChildren();
  const noop = { destroy: () => {}, resize: () => {} };
  if (result?.error) {
    const state = el('div', 'dbv-block-state');
    state.append(el('strong', '', t('warning')), el('p', '', result.error));
    container.append(state);
    return noop;
  }
  if (widget.type === 'text') {
    container.append(el('div', 'dbv-text-content', widget.text || t('textPlaceholder')));
    return noop;
  }
  if (!result) {
    const state = el('div', 'dbv-block-state');
    state.append(el('span', 'dbv-spinner'), el('span', '', t('loadingChart')));
    container.append(state);
    return noop;
  }
  if (widget.type === 'kpi') {
    const wrapper = el('div', 'dbv-kpi');
    wrapper.style.setProperty('--kpi-color', widget.color);
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
    return noop;
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
  const datasets = result.datasets ?? [],
    labels = result.labels ?? [];
  if (!datasets.length || !datasets.some((d) => d.data.length)) {
    container.append(el('div', 'dbv-block-state', t('emptyResults')));
    return noop;
  }
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
        borderColor: i === 0 ? widget.color : palette[i % palette.length],
        backgroundColor:
          type === 'doughnut'
            ? palette
            : widget.type === 'area'
              ? (i === 0 ? widget.color : palette[i % palette.length]) + '26'
              : i === 0
                ? widget.color
                : palette[i % palette.length],
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
          labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 11 } },
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
                ticks: { maxRotation: 0, maxTicksLimit: 9, color: '#65788a', font: { size: 11 } },
              },
              y: {
                beginAtZero: type !== 'scatter',
                title: {
                  display: !!widget.unit,
                  text: widget.unit,
                  color: '#65788a',
                  font: { size: 10 },
                },
                grid: { color: '#edf1f5' },
                border: { display: false },
                ticks: { maxTicksLimit: 6, color: '#65788a', font: { size: 11 } },
              },
            },
      onClick: (_event, elements) => {
        const index = elements[0]?.index;
        if (index === undefined) return;
        if (result.category_filters) {
          const filter = result.category_filters[index];
          if (filter) ctx.filter(filter);
          return;
        }
        if (
          !widget.x_field ||
          type === 'scatter' ||
          widget.type === 'histogram' ||
          (widget.time_grain && widget.time_grain !== 'none')
        )
          return;
        ctx.filter({ field: widget.x_field, op: 'eq', value: labels[index] });
      },
      onHover: (event, elements) => {
        if (event.native?.target instanceof HTMLCanvasElement)
          event.native.target.style.cursor =
            elements.length &&
            (result.category_filters
              ? !!result.category_filters[elements[0].index]
              : widget.x_field &&
                type !== 'scatter' &&
                widget.type !== 'histogram' &&
                (!widget.time_grain || widget.time_grain === 'none'))
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
  accessible.append(dataTable(columns, rows, ctx));
  container.append(accessible);
  return {
    destroy: () => chart.destroy(),
    resize: () => chart.resize(),
    png: () => {
      const scale = canvas.width / (canvas.clientWidth || canvas.width);
      const padding = 20 * scale;
      const heading = 40 * scale;
      const exported = document.createElement('canvas');
      exported.width = canvas.width + padding * 2;
      exported.height = canvas.height + heading + padding * 2;
      const painter = exported.getContext('2d')!;
      painter.fillStyle = '#ffffff';
      painter.fillRect(0, 0, exported.width, exported.height);
      painter.fillStyle = '#173347';
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
) {
  const table = el('table', 'dbv-table');
  const head = el('thead'),
    tr = el('tr');
  columns.forEach((c) => {
    const th = el('th', '', c.label);
    th.scope = 'col';
    tr.append(th);
  });
  head.append(tr);
  table.append(head);
  const body = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    for (const column of columns) tr.append(el('td', '', number(row[column.key], ctx.locale)));
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
      style: ctx.basemap || {
        version: 8,
        sources: {},
        layers: [
          { id: 'background', type: 'background', paint: { 'background-color': '#e7f0f3' } },
        ],
      },
      center: [0, 20],
      zoom: 1,
      pitch: 0,
      maxPitch: 0,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
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
  if (widget.show_legend !== false) {
    const legend = el('div', 'dbv-map-legend');
    const swatch = el('span', 'dbv-map-swatch');
    swatch.style.background =
      hi > lo ? `linear-gradient(90deg,#b4dce9,${widget.color})` : widget.color;
    legend.append(
      swatch,
      el(
        'span',
        '',
        hi > lo
          ? `${number(lo, ctx.locale)} – ${number(hi, ctx.locale)} ${widget.unit || ''}`
          : ctx.t('mapCount'),
      ),
    );
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
  }
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
        'circle-color': widget.color,
        'circle-radius': ['step', ['get', 'point_count'], 15, 50, 21, 200, 27],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
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
                  '#b4dce9',
                  hi,
                  widget.color,
                ],
              ]
            : widget.color,
        'circle-radius': 6,
        'circle-opacity': 0.85,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#fff',
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
  };
}
