import test from 'node:test';
import assert from 'node:assert/strict';
import { validateWidgets } from '../src/validation.ts';
import { translator, serverMessage } from '../src/i18n.ts';

const t = translator('en');
const profile = { fields: [
  { key: 'site', label: 'Site', type: 'text' },
  { key: 'value', label: 'Value', type: 'number' },
  { key: 'date', label: 'Date', type: 'date' },
  { key: 'active', label: 'Active', type: 'boolean' },
] };
const widget = (overrides = {}) => ({
  id: 'block', type: 'bar', aggregate: 'count', time_grain: 'none',
  x_field: 'site', y_field: null, series_field: null, columns: [], ...overrides,
});
const validate = (blocks, lang = 'en') => validateWidgets({ widgets: blocks }, profile, translator(lang));

test('legacy row counts do not require a value column or validate unused selections', () => {
  assert.deepEqual(validate([
    widget({ type: 'kpi', x_field: 'old', y_field: 'old', series_field: 'old' }),
    widget({ y_field: 'old' }),
    widget({ type: 'text', x_field: 'old' }),
  ]), []);
  assert.deepEqual(validateWidgets({ widgets: [widget({ x_field: null })] }, undefined, t), []);
});

test('checks selected column requirements, date grains, and group columns', () => {
  assert.deepEqual(validate([widget({ x_field: null })]).map((issue) => issue.field), ['x_field']);
  assert.match(validate([widget({ x_field: 'deleted' })])[0].message, /no longer available/);
  assert.deepEqual(validate([widget({ time_grain: 'month', x_field: 'date' })]), []);
  assert.deepEqual(validate([widget({ time_grain: 'month', x_field: 'site' })]).map((issue) => issue.field), ['x_field']);
  assert.deepEqual(validate([widget({ series_field: 'deleted' })]).map((issue) => issue.field), ['series_field']);
});

test('KPI min/max accepts dates while numeric statistics require numbers', () => {
  for (const aggregate of ['min', 'max']) {
    assert.deepEqual(validate([widget({ type: 'kpi', aggregate, y_field: 'date' })]), []);
    assert.deepEqual(validate([widget({ aggregate, y_field: 'date' })]).map((issue) => issue.field), ['y_field']);
  }
  for (const aggregate of ['sum', 'avg', 'median']) {
    assert.deepEqual(validate([widget({ type: 'kpi', aggregate, y_field: 'value' })]), []);
    assert.deepEqual(validate([widget({ type: 'kpi', aggregate, y_field: 'date' })]).map((issue) => issue.field), ['y_field']);
  }
  for (const y_field of ['site', 'date', 'active', 'value'])
    assert.deepEqual(validate([widget({ aggregate: 'count_distinct', y_field })]), []);
});

test('histograms use the same x-then-y fallback as the engine', () => {
  assert.deepEqual(validate([widget({ type: 'histogram', x_field: 'value' })]), []);
  assert.deepEqual(validate([widget({ type: 'histogram', x_field: null, y_field: 'value' })]), []);
  assert.deepEqual(validate([widget({ type: 'histogram', x_field: 'site', y_field: 'value' })]).map((issue) => issue.field), ['x_field']);
  assert.deepEqual(validate([widget({ type: 'histogram', x_field: null })]).map((issue) => issue.field), ['y_field']);
});

test('map and scatter requirements match numeric coordinates and measurements', () => {
  assert.deepEqual(validate([widget({ type: 'map', lat_field: 'value', lon_field: 'value' })]), []);
  assert.deepEqual(validate([widget({ type: 'map', lat_field: 'site', lon_field: null })]).map((issue) => issue.field), ['lat_field', 'lon_field']);
  assert.deepEqual(validate([widget({ type: 'map', lat_field: 'value', lon_field: 'value', aggregate: 'avg', y_field: 'date' })]).map((issue) => issue.field), ['y_field']);
  assert.deepEqual(validate([widget({ type: 'scatter', x_field: 'value', y_field: 'value', series_field: 'site' })]), []);
  assert.deepEqual(validate([widget({ type: 'scatter', x_field: 'date', y_field: 'site' })]).map((issue) => issue.field), ['x_field', 'y_field']);
});

test('tables allow all columns and only validate selected columns and sorting', () => {
  assert.deepEqual(validate([widget({ type: 'table', columns: [], x_field: null })]), []);
  assert.deepEqual(validate([widget({ type: 'table', columns: ['value', 'deleted'], x_field: 'deleted' })]).map((issue) => issue.field), ['columns', 'x_field']);
});

test('validation identifies each block and localizes errors without interpreting column labels', () => {
  const blocks = [widget({ id: 'first', x_field: null }), widget({ id: 'second', x_field: '$&' })];
  const errors = validate(blocks, 'es');
  assert.deepEqual(errors.map((issue) => issue.widgetId), ['first', 'second']);
  assert.match(errors[0].message, /^Elige una columna/);
  assert.ok(errors[1].message.includes('$&'));
  assert.match(validate(blocks, 'fr')[0].message, /^Choisissez une colonne/);
});

test('all appearance and guidance labels exist in English, Spanish, and French', () => {
  const keys = ['reviewData', 'chooseBlocks', 'personalize', 'reviewSave', 'guideHelp',
    'appearance', 'theme', 'themeLight', 'themeOcean', 'themeDark', 'background',
    'cardBackground', 'accent', 'palette', 'paletteIhp', 'paletteAccessible', 'paletteMono',
    'resetAppearance', 'customColor', 'lowContrast', 'fixContrast', 'advancedOptions',
    'templateFields', 'mainVariable', 'applyTemplate', 'sharedFiltersHelp', 'activeFilters',
    'shareOriginal', 'loadingQuery', 'updatingSource', 'validationSummary', 'filterAction',
    'principalColor', 'paletteHelp', 'invalidColor'];
  for (const lang of ['en', 'es', 'fr']) {
    const translate = translator(lang);
    for (const key of keys) assert.notEqual(translate(key), key, `${lang}:${key}`);
  }
});

test('server messages translate pending, source notices, and widget diagnostics', () => {
  for (const lang of ['es', 'fr']) {
    const translate = translator(lang);
    for (const message of ['Calculating the dashboard.',
      'The source is updating. Showing the last completed update.',
      'The source could not be refreshed. Showing the last completed update; try refreshing again.',
      'Spreadsheet formulas use their last saved values. Save the workbook in a spreadsheet application to refresh calculations.',
      'Choose a y column.', "Column 'removed' is no longer available.",
      "Column 'value' has an incompatible type. Update this block or its column interpretation."])
      assert.notEqual(serverMessage(message, translate), message);
    assert.equal(serverMessage('opaque server message', translate, 'queue_unavailable'), translate('statusQueueUnavailable'));
    assert.equal(serverMessage(undefined, translate), translate('error'));
    assert.equal(serverMessage('Unrecognized diagnostic', translate), 'Unrecognized diagnostic');
  }
});

test('server warnings retain column names and counts while translating the explanation', () => {
  const translate = translator('es');
  const values = serverMessage('CHL $&: 12 values could not be interpreted as number; they are excluded from calculations and preserved in CSV export.', translate);
  assert.ok(values.includes('CHL $&'));
  assert.ok(values.includes('12'));
  assert.ok(values.includes('Número'));
  assert.ok(values.includes('exportación CSV'));
  assert.equal(serverMessage("Type override column '$&' is no longer available.", translate), 'La columna «$&» con un tipo personalizado ya no está disponible.');
  assert.equal(serverMessage('Observation date: Ambiguous dates were preserved as text. Set a date format to interpret this column.', translate), `Observation date: ${translate('warnAmbiguousDates')}`);
});
