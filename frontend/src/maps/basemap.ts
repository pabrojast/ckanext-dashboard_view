import type { StyleSpecification } from 'maplibre-gl';
import positronBorderless from './positron-borderless.json';

const DEFAULT_BASEMAP_URL = 'https://tiles.openfreemap.org/styles/positron';

/** Use the bundled borderless style for the default map; retain custom styles. */
export function basemapStyle(url?: string): string | StyleSpecification {
  if (url && url !== DEFAULT_BASEMAP_URL) return url;
  // MapLibre can modify the style, so each dashboard map needs its own copy.
  return JSON.parse(JSON.stringify(positronBorderless)) as StyleSpecification;
}
