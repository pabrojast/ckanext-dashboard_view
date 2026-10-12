import type { DashboardStyle } from './types';

export type NormalizedStyle = Required<DashboardStyle>;
export type AppearancePreset = 'light' | 'ocean' | 'dark';
export interface ResolvedAppearance {
  theme: 'light' | 'dark';
  background: string;
  cardBackground: string;
  accent: string;
  accentInk: string;
  accentHover: string;
  link: string;
  ink: string;
  muted: string;
  cardInk: string;
  cardMuted: string;
  line: string;
  surface: string;
  hover: string;
  soft: string;
  error: string;
  errorSurface: string;
  palette: string[];
}

const IHP_COLORS = [
  '#0069b4', '#00a5b5', '#755fbe', '#e29a36',
  '#48977b', '#cf688a', '#6393cd', '#7f8e9f',
];
// Distinct hues adapted from the widely used Okabe-Ito categorical palette.
const ACCESSIBLE_COLORS = [
  '#0072b2', '#d55e00', '#009e73', '#cc79a7',
  '#e69f00', '#56b4e9', '#6f6500', '#555555',
];
const HEX_COLOR = /^#[0-9a-f]{6}$/i;

export function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && value.length === 7 && HEX_COLOR.test(value);
}

/** Tolerate missing legacy fields but reject invalid persisted appearance data. */
export function normalizeStyle(value?: Partial<DashboardStyle> | null): NormalizedStyle {
  if (value != null && (typeof value !== 'object' || Array.isArray(value)))
    throw new Error('Dashboard style must be an object.');
  const style = value ?? {};
  const accent = style.accent === undefined ? '#0069b4' : style.accent;
  const theme = style.theme === undefined ? 'light' : style.theme;
  const palette = style.palette === undefined ? 'ihp' : style.palette;
  if (!isHexColor(accent)) throw new Error('Colors must use #RRGGBB format.');
  if (theme !== 'light' && theme !== 'dark') throw new Error('Invalid dashboard theme.');
  if (!['ihp', 'accessible', 'mono'].includes(palette)) throw new Error('Invalid chart palette.');
  for (const color of [style.background, style.card_background])
    if (color != null && !isHexColor(color)) throw new Error('Colors must use #RRGGBB format.');
  return { accent, theme, palette, background: style.background ?? null, card_background: style.card_background ?? null };
}

export function presetStyle(preset: AppearancePreset): NormalizedStyle {
  if (preset === 'dark')
    return normalizeStyle({ theme: 'dark', accent: '#59b9ef' });
  if (preset === 'ocean')
    return normalizeStyle({ accent: '#006b83', background: '#e8f3f8', card_background: '#ffffff' });
  return normalizeStyle();
}

function rgb(color: string): number[] {
  if (!isHexColor(color)) throw new Error('Colors must use #RRGGBB format.');
  return [1, 3, 5].map((start) => Number.parseInt(color.slice(start, start + 2), 16));
}

function luminance(color: string): number {
  return rgb(color).map((value) => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
}

export function contrastRatio(foreground: string, background: string): number {
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

export function readableForeground(background: string): string {
  return contrastRatio('#173347', background) >= 4.5 ? '#173347'
    : contrastRatio('#ffffff', background) >= contrastRatio('#000000', background) ? '#ffffff' : '#000000';
}

function blend(from: string, to: string, proportion: number): string {
  const start = rgb(from), end = rgb(to);
  return '#' + start.map((value, index) => Math.round(value + (end[index] - value) * proportion).toString(16).padStart(2, '0')).join('');
}

/** Keep the hue where possible; find the smallest blend that meets contrast. */
export function correctChartColor(color: string, background: string, minimumContrast = 3): string {
  const destination = contrastRatio('#ffffff', background) > contrastRatio('#000000', background) ? '#ffffff' : '#000000';
  return correctOnSurfaces(color, [background], destination, minimumContrast);
}

function correctOnSurfaces(color: string, surfaces: string[], destination: string, minimumContrast: number): string {
  const readable = (foreground: string) => surfaces.every((background) => contrastRatio(foreground, background) >= minimumContrast);
  if (readable(color)) return color;
  let low = 0, high = 1;
  for (let index = 0; index < 18; index++) {
    const amount = (low + high) / 2;
    if (readable(blend(color, destination, amount))) high = amount;
    else low = amount;
  }
  return blend(color, destination, high);
}

function backgrounds(style: NormalizedStyle) {
  return {
    background: style.background ?? (style.theme === 'dark' ? '#101c29' : '#f4f7fa'),
    cardBackground: style.card_background ?? (style.theme === 'dark' ? '#1c2b3b' : '#ffffff'),
  };
}

export function paletteColors(value?: Partial<DashboardStyle> | null, count = 8): string[] {
  const style = normalizeStyle(value);
  const { cardBackground } = backgrounds(style);
  const colors = style.palette === 'accessible' ? ACCESSIBLE_COLORS : style.palette === 'mono'
    ? [0, 0.12, 0.24, 0.36, 0.48, 0.60, 0.72, 0.84].map((amount) => blend(style.accent, readableForeground(cardBackground), amount))
    : IHP_COLORS;
  // Preserve legacy chart colors on their original white cards.
  const unchanged = style.palette === 'ihp' && cardBackground.toLowerCase() === '#ffffff';
  return Array.from({ length: Math.max(0, Math.min(100, count)) }, (_, index) => {
    const color = colors[index % colors.length];
    return unchanged ? color : correctChartColor(color, cardBackground);
  });
}

export function resolveAppearance(value?: Partial<DashboardStyle> | null): ResolvedAppearance {
  const style = normalizeStyle(value);
  const { background, cardBackground } = backgrounds(style);
  const ink = readableForeground(background), cardInk = readableForeground(cardBackground);
  // Tinted surfaces must not cross into a different text-contrast range when
  // an author chooses a midtone card background.
  const hover = correctChartColor(blend(cardBackground, cardInk, 0.05), cardInk, 4.5);
  const soft = correctChartColor(blend(cardBackground, style.accent, 0.09), cardInk, 4.5);
  const errorSurface = correctChartColor(blend(cardBackground, '#b34840', 0.08), cardInk, 4.5);
  const onSurfaces = (color: string, surfaces: string[]) =>
    correctOnSurfaces(color, surfaces, cardInk, 4.5);
  const cardMuted = onSurfaces('#667d8e', [cardBackground, hover, soft]);
  const link = onSurfaces(style.accent, [cardBackground, soft, hover]);
  return {
    theme: style.theme, background, cardBackground, accent: style.accent,
    accentInk: readableForeground(style.accent),
    accentHover: blend(style.accent, readableForeground(style.accent) === '#ffffff' ? '#000000' : '#ffffff', 0.1),
    link, ink, muted: correctChartColor('#667d8e', background, 4.5), cardInk, cardMuted,
    line: blend(cardBackground, cardInk, 0.2), surface: background,
    hover, soft,
    error: onSurfaces('#b34840', [cardBackground, errorSurface]),
    errorSurface,
    palette: paletteColors(style),
  };
}

/** Scope all tokens to the dashboard; the CKAN page around it keeps its theme. */
export function applyAppearance(root: HTMLElement, style?: Partial<DashboardStyle> | null): ResolvedAppearance {
  const appearance = resolveAppearance(style);
  const tokens: Record<string, string> = {
    accent: appearance.accent, 'accent-ink': appearance.accentInk, 'accent-hover': appearance.accentHover,
    link: appearance.link, ink: appearance.cardInk, muted: appearance.cardMuted,
    'canvas-ink': appearance.ink, 'canvas-muted': appearance.muted,
    line: appearance.line, surface: appearance.background, card: appearance.cardBackground,
    hover: appearance.hover, soft: appearance.soft, error: appearance.error, 'error-surface': appearance.errorSurface,
    'control-line': correctChartColor(appearance.line, appearance.cardBackground, 3),
    focus: correctChartColor(appearance.accent, appearance.cardBackground, 3),
    'stage-dot': blend(appearance.background, appearance.ink, 0.14),
  };
  for (const [name, color] of Object.entries(tokens)) root.style.setProperty(`--dbv-${name}`, color);
  root.dataset.dbvTheme = appearance.theme;
  root.dataset.dbvCardTone = luminance(appearance.cardBackground) < 0.179 ? 'dark' : 'light';
  root.style.colorScheme = root.dataset.dbvCardTone;
  return appearance;
}
