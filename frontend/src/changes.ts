import type { Config } from './types';

/** Presentation changes must not invalidate data or re-download the source. */
export function changeEffect(previous: Config, next: Config): 'source' | 'query' | 'visual' {
  if (JSON.stringify(previous.source) !== JSON.stringify(next.source)) return 'source';
  const queryShape = (config: Config) => ({
    widgets: config.widgets.map(({ x, y, w, h, title, color, unit, show_legend, text, ...data }) => data),
    // Labels belong to the UI; fields and types determine requested facets.
    filters: config.filters.map(({ field, type }) => ({ field, type })),
  });
  return JSON.stringify(queryShape(previous)) === JSON.stringify(queryShape(next)) ? 'visual' : 'query';
}
