import type { Map, StyleSpecification, LayerSpecification } from 'maplibre-gl';
import positronBorderless from './positron-borderless.json';

const DEFAULT_BASEMAP_URL = 'https://tiles.openfreemap.org/styles/positron';

function defaultBasemap(url?: string): boolean {
  return !url || url === DEFAULT_BASEMAP_URL;
}

/** Color changes only: retain every source, layer, filter and attribution. */
function darkPaint(layer: LayerSpecification): Record<string, string> {
  if (layer.type === 'background') return { 'background-color': '#18252f' };
  if (layer.type === 'fill') {
    const color = layer.id === 'water' ? '#0d1c28'
      : layer.id === 'park' || layer.id.includes('wood') ? '#263b36'
      : layer.id.includes('ice') || layer.id.includes('glacier') ? '#546976'
      : layer.id === 'building' ? '#2e3d47' : '#22313b';
    const paint: Record<string, string> = { 'fill-color': color };
    if (layer.paint?.['fill-outline-color']) paint['fill-outline-color'] = '#3a4b57';
    return paint;
  }
  if (layer.type === 'line') return {
    'line-color': layer.id === 'waterway' ? '#294b60'
      : layer.id.startsWith('boundary') ? '#53636e'
      : layer.id.includes('casing') ? '#283943' : '#435460',
  };
  if (layer.type === 'symbol' && layer.layout?.['text-field']) return {
    'text-color': layer.id.startsWith('water') ? '#96b7cd' : '#c1ced7',
    'text-halo-color': '#18252f',
  };
  return {};
}

/** Use the bundled borderless style for the default map; retain custom styles. */
export function basemapStyle(url?: string, dark = false): string | StyleSpecification {
  if (!defaultBasemap(url)) return url!;
  // MapLibre can modify the style, so each dashboard map needs its own copy.
  const style = JSON.parse(JSON.stringify(positronBorderless)) as StyleSpecification;
  if (dark) for (const layer of style.layers) {
    layer.paint = { ...layer.paint, ...darkPaint(layer) } as typeof layer.paint;
  }
  return style;
}

/** Update existing paint rather than replacing the style or resetting the map camera. */
export function updateBasemapAppearance(
  map: Pick<Map, 'getLayer' | 'setPaintProperty'>,
  url: string | undefined,
  dark: boolean,
): void {
  if (!defaultBasemap(url)) return;
  for (const layer of (positronBorderless as StyleSpecification).layers) {
    if (!map.getLayer(layer.id)) continue;
    for (const [property, value] of Object.entries(darkPaint(layer))) {
      const original = (layer.paint as Record<string, unknown> | undefined)?.[property];
      map.setPaintProperty(
        layer.id,
        property as Parameters<Map['setPaintProperty']>[1],
        (dark ? value : original) as Parameters<Map['setPaintProperty']>[2],
      );
    }
  }
}
