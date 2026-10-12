import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyAppearance, contrastRatio, correctChartColor, normalizeStyle, paletteColors,
  presetStyle, readableForeground, resolveAppearance,
} from '../src/appearance.ts';

test('legacy style preserves canvas, cards, accent and the original categorical palette', () => {
  const style = normalizeStyle({ accent: '#0069b4' });
  assert.deepEqual(style, { accent: '#0069b4', theme: 'light', palette: 'ihp', background: null, card_background: null });
  const appearance = resolveAppearance(style);
  assert.equal(appearance.background, '#f4f7fa');
  assert.equal(appearance.cardBackground, '#ffffff');
  assert.equal(appearance.accent, '#0069b4');
  assert.deepEqual(appearance.palette, ['#0069b4', '#00a5b5', '#755fbe', '#e29a36', '#48977b', '#cf688a', '#6393cd', '#7f8e9f']);
});

test('presets replace overrides and serialize without changing schema assumptions', () => {
  assert.deepEqual(normalizeStyle(JSON.parse(JSON.stringify(presetStyle('dark')))), presetStyle('dark'));
  assert.equal(presetStyle('ocean').theme, 'light');
  assert.equal(presetStyle('ocean').background, '#e8f3f8');
  assert.equal(presetStyle('light').background, null);
  assert.notEqual(resolveAppearance(presetStyle('dark')).cardBackground, '#ffffff');
});

test('appearance rejects CSS, arbitrary theme names and malformed colors', () => {
  for (const style of [[], 'dark', { theme: 'ocean' }, { theme: null }, { palette: 'remote' },
    { palette: null }, { accent: null }, { accent: '#abcdef\n' }, { background: '#fff' },
    { card_background: 'url(https://example.com)' }, { accent: '#123456;display:none' }]) {
    assert.throws(() => normalizeStyle(style));
  }
});

test('custom surfaces and accents retain readable text across light, dark and midtone colors', () => {
  const backgrounds = ['#000000', '#ffffff', '#777777', '#e8f3f8', '#101c29', '#ffcc00', '#cc00cc'];
  for (const background of backgrounds) {
    assert.ok(contrastRatio(readableForeground(background), background) >= 4.5, background);
    for (const accent of backgrounds) {
      const a = resolveAppearance({ accent, background, card_background: background });
      for (const text of [a.cardInk, a.cardMuted, a.link])
        assert.ok(contrastRatio(text, background) >= 4.5, `${text} against ${background}`);
      assert.ok(contrastRatio(a.cardMuted, a.hover) >= 4.5);
      assert.ok(contrastRatio(a.link, a.soft) >= 4.5);
      assert.ok(contrastRatio(a.error, a.errorSurface) >= 4.5);
      assert.ok(contrastRatio(a.accentInk, a.accent) >= 4.5);
      assert.ok(contrastRatio(a.accentInk, a.accentHover) >= 4.5);
    }
  }
});

test('contrast corrections retain usable colors and dark palettes meet chart contrast', () => {
  assert.equal(correctChartColor('#0069b4', '#ffffff'), '#0069b4');
  assert.ok(contrastRatio(correctChartColor('#ffffff', '#ffffff'), '#ffffff') >= 3);
  assert.ok(contrastRatio(correctChartColor('#000000', '#101c29'), '#101c29') >= 3);
  for (const palette of ['ihp', 'accessible', 'mono']) {
    const style = { ...presetStyle('dark'), palette };
    const colors = paletteColors(style, 12);
    assert.equal(colors.length, 12);
    for (const color of colors) assert.ok(contrastRatio(color, resolveAppearance(style).cardBackground) >= 3);
  }
});

test('applying appearance only changes the supplied dashboard root', () => {
  const tokens = new Map();
  const root = { style: { setProperty: (name, value) => tokens.set(name, value) }, dataset: {} };
  const appearance = applyAppearance(root, presetStyle('dark'));
  assert.equal(root.dataset.dbvTheme, 'dark');
  assert.equal(root.style.colorScheme, 'dark');
  assert.equal(tokens.get('--dbv-card'), appearance.cardBackground);
  assert.equal(tokens.get('--dbv-ink'), appearance.cardInk);
  assert.ok([...tokens.keys()].every((key) => key.startsWith('--dbv-')));
  // A dark theme with white custom cards still needs light native form controls.
  applyAppearance(root, { ...presetStyle('dark'), card_background: '#ffffff' });
  assert.equal(root.style.colorScheme, 'light');
});
