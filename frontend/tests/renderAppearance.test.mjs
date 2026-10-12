import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

// Exercise the actual TypeScript modules with minimal browser/Chart adapters.
const source = fileURLToPath(new URL('../src/', import.meta.url));
function load(relative, mocks = {}) {
  const filename = path.resolve(source, relative);
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const exports = {};
  const require = (name) => {
    if (name in mocks) return mocks[name];
    if (name.endsWith('.json')) return JSON.parse(fs.readFileSync(path.resolve(path.dirname(filename), name), 'utf8'));
    if (name.startsWith('.')) return load(path.relative(source, path.resolve(path.dirname(filename), name + '.ts')), mocks);
    throw new Error(`Unmocked dependency: ${name}`);
  };
  new Function('require', 'exports', output)(require, exports);
  return exports;
}
const { basemapStyle, updateBasemapAppearance } = load('maps/basemap.ts');
const { resolveAppearance, presetStyle } = load('appearance.ts');

test('dark default map preserves geographic sources, attribution, layer order, filters and geometry', () => {
  const light = basemapStyle(), dark = basemapStyle(undefined, true);
  assert.deepEqual(dark.sources, light.sources);
  assert.equal(dark.sprite, light.sprite);
  assert.equal(dark.glyphs, light.glyphs);
  assert.deepEqual(dark.layers.map(({ paint, ...layer }) => layer), light.layers.map(({ paint, ...layer }) => layer));
  assert.notEqual(dark.layers[0].paint['background-color'], light.layers[0].paint['background-color']);
  for (const [index, layer] of dark.layers.entries()) {
    for (const [property, value] of Object.entries(light.layers[index].paint ?? {})) {
      if (!property.endsWith('color')) assert.deepEqual(layer.paint[property], value);
    }
  }
  assert.equal(dark.layers.some(layer => /boundary_2|disputed/.test(layer.id)), false);
  dark.layers[0].paint['background-color'] = '#123456';
  assert.notEqual(basemapStyle(undefined, true).layers[0].paint['background-color'], '#123456');
});

test('theme toggles change default paint only and restore original colors without camera/style resets', () => {
  const light = basemapStyle(), changes = [];
  const map = { getLayer: id => light.layers.find(layer => layer.id === id), setPaintProperty: (...args) => changes.push(args) };
  updateBasemapAppearance(map, undefined, true);
  assert.ok(changes.length > 20);
  changes.length = 0;
  updateBasemapAppearance(map, undefined, false);
  for (const [id, property, value] of changes) {
    assert.deepEqual(value, light.layers.find(layer => layer.id === id).paint?.[property]);
  }
  changes.length = 0;
  const custom = 'https://maps.example.test/custom-style.json';
  assert.equal(basemapStyle(custom, true), custom);
  updateBasemapAppearance(map, custom, true);
  assert.equal(changes.length, 0);
});

class Node {
  constructor(tag, className = '', textContent = '') {
    Object.assign(this, { tag, className, textContent, children: [], attributes: {}, style: {} });
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  querySelectorAll(selector) {
    const tag = selector.split(' ').at(-1);
    const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
    return descendants(this).filter(node => node.tag === tag);
  }
  get firstElementChild() { return this.children[0]; }
}
class Chart {
  static register() {}
  constructor(canvas, config) {
    Object.assign(this, { canvas, data: config.data, options: config.options, updates: [], destroyed: false });
    Chart.latest = this;
  }
  update(mode) { this.updates.push(mode); }
  destroy() { this.destroyed = true; }
  resize() {}
}
const mocks = {
  'chart.js': { Chart, registerables: [] },
  'maplibre-gl': { setWorkerUrl() {} },
  'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url': 'worker.js',
  './dom': {
    el: (...args) => new Node(...args),
    button: (label, action, className) => Object.assign(new Node('button', className, label), { action }),
  },
};
const { chartFilterAt, renderWidget } = load('render.ts', mocks);
const widget = { type: 'bar', id: 'bar', title: 'Water quality', x_field: 'category', y_field: 'value', color: '#0069b4', aggregate: 'sum' };

test('canvas and keyboard action use backend typed category filters, including empty and time ranges', () => {
  const filters = [
    { field: 'category', op: 'eq', value: null },
    { field: 'category', op: 'eq', value: false },
    { field: 'category', op: 'eq', value: 123 },
    { field: 'date', op: 'between', value: ['2026-01-01', '2026-01-31'] },
  ];
  filters.forEach((filter, index) => assert.deepEqual(chartFilterAt(widget, { category_filters: filters }, index), filter));
  assert.equal(chartFilterAt(widget, { category_filters: [null], labels: ['Other'] }, 0), undefined);
  assert.deepEqual(chartFilterAt(widget, { labels: [false] }, 0), filters[1]);
  assert.equal(chartFilterAt({ ...widget, time_grain: 'month' }, { labels: ['2026-01'] }, 0), undefined);
  assert.equal(chartFilterAt(widget, { labels: [] }, 0), undefined);
  for (const type of ['scatter', 'histogram']) {
    assert.equal(chartFilterAt({ ...widget, type }, { category_filters: filters, labels: ['A'] }, 0), undefined);
  }
});

test('visual updates retain chart data and use the live theme for legends, axes and exported PNG', () => {
  const container = new Node('div'), selected = [];
  const filter = { field: 'category', op: 'eq', value: false };
  const result = { labels: ['False'], datasets: [{ label: 'Count', data: [2] }], category_filters: [filter] };
  const handle = renderWidget(container, widget, result, {
    locale: 'en', t: key => key, filter: value => selected.push(value), bounds() {}, page() {},
  });
  const chart = Chart.latest, originalData = chart.data.datasets[0].data;
  const allNodes = node => [node, ...node.children.flatMap(allNodes)];
  const action = allNodes(container).find(node => node.tag === 'button');
  assert.ok(action);
  assert.equal(action.attributes['aria-label'], 'filterAction: False');
  action.action();
  chart.options.onClick(null, [{ index: 0 }]);
  assert.deepEqual(selected, [filter, filter]);
  const appearance = resolveAppearance(presetStyle('dark'));
  const editedWidget = { ...widget, title: 'Updated title', unit: 'mg/L', color: '#ffcc00' };
  handle.updateAppearance(appearance, editedWidget);
  assert.equal(chart.destroyed, false);
  assert.equal(chart.data.datasets[0].data, originalData);
  assert.deepEqual(chart.updates, ['none']);
  assert.equal(chart.options.plugins.legend.labels.color, appearance.cardInk);
  assert.equal(chart.data.datasets[0].label, 'Updated title');
  assert.equal(container.querySelectorAll('thead th')[1].textContent, 'Updated title');
  assert.equal(chart.options.scales.y.title.text, 'mg/L');
  assert.equal(chart.options.scales.x.ticks.color, appearance.cardMuted);
  const commands = [], painter = {
    fillRect() { commands.push(['background', this.fillStyle]); },
    fillText(title) { commands.push(['title', title, this.fillStyle]); }, drawImage() {},
  };
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({ getContext: () => painter, toDataURL: () => 'data:image/png;base64,test' }) };
  try {
    Object.assign(chart.canvas, { width: 400, height: 200, clientWidth: 400 });
    assert.equal(handle.png(), 'data:image/png;base64,test');
    assert.deepEqual(commands, [['background', appearance.cardBackground], ['title', 'Updated title', appearance.cardInk]]);
  } finally { if (previous) globalThis.document = previous; else delete globalThis.document; }
  // The editor mutates the existing widget rather than replacing its object.
  editedWidget.title = 'Inline edit';
  handle.updateAppearance(appearance, editedWidget);
  assert.equal(chart.data.datasets[0].label, 'Inline edit');
  assert.equal(container.querySelectorAll('thead th')[1].textContent, 'Inline edit');
});

test('doughnut sectors follow the selected palette and change without rebuilding the chart', () => {
  const container = new Node('div');
  const handle = renderWidget(container, { ...widget, type: 'doughnut' }, {
    labels: ['A', 'B', 'C'], datasets: [{ label: 'Count', data: [2, 3, 4] }],
  }, { locale: 'en', t: key => key, filter() {}, bounds() {}, page() {} });
  const chart = Chart.latest;
  assert.deepEqual(chart.data.datasets[0].backgroundColor, ['#0069b4', '#00a5b5', '#755fbe']);
  const appearance = resolveAppearance({ accent: '#0069b4', palette: 'accessible' });
  handle.updateAppearance(appearance);
  assert.deepEqual(chart.data.datasets[0].backgroundColor, appearance.palette.slice(0, 3));
  assert.equal(chart.destroyed, false);
});

test('map visual updates preserve camera and sources, including a theme change before initial load', () => {
  class Map {
    constructor(options) {
      Object.assign(this, { options, layers: new globalThis.Map(), paints: [], sources: [], fits: 0, loaded: false });
      this.touchZoomRotate = { disableRotation() {} };
      Map.latest = this;
    }
    addControl() {}
    on() {}
    once(_event, callback) { this.onLoad = callback; }
    getLayer(id) {
      return this.layers.get(id) ?? (this.loaded ? this.options.style.layers.find(layer => layer.id === id) : undefined);
    }
    addSource(id, value) { this.sources.push([id, value]); }
    addLayer(layer) { this.layers.set(layer.id, layer); }
    setPaintProperty(...args) { this.paints.push(args); }
    fitBounds() { this.fits++; }
    resize() {}
  }
  const mapMocks = { ...mocks, 'maplibre-gl': {
    setWorkerUrl() {}, Map, NavigationControl: class {}, LngLatBounds: class { extend() {} },
  } };
  const renderer = load('render.ts', mapMocks);
  const previous = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  try {
    const handle = renderer.renderWidget(new Node('div'), { ...widget, type: 'map' }, {
      points: [{ lat: 2, lon: 3, value: 4 }, { lat: 4, lon: 5, value: 9 }],
    }, { locale: 'en', t: key => key, filter() {}, bounds() {}, page() {} });
    const map = Map.latest;
    const dark = resolveAppearance(presetStyle('dark'));
    handle.updateAppearance(dark, { ...widget, type: 'map', color: '#ffcc00' });
    assert.equal(map.sources.length, 0);
    map.loaded = true;
    map.onLoad();
    assert.equal(map.layers.get('clusters').paint['circle-stroke-color'], dark.cardBackground);
    assert.ok(map.paints.some(([id, property, color]) => id === 'background' && property === 'background-color' && color === '#18252f'));
    assert.equal(map.fits, 1);
    assert.equal(map.sources.length, 1);
    const data = map.sources[0][1].data;
    handle.updateAppearance(resolveAppearance(presetStyle('light')));
    assert.equal(map.fits, 1);
    assert.equal(map.sources.length, 1);
    assert.equal(map.sources[0][1].data, data);
  } finally { if (previous) globalThis.ResizeObserver = previous; else delete globalThis.ResizeObserver; }
});
