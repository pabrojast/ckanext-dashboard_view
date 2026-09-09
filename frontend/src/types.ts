export type WidgetType =
  | 'kpi'
  | 'line'
  | 'area'
  | 'bar'
  | 'doughnut'
  | 'scatter'
  | 'histogram'
  | 'table'
  | 'text'
  | 'map';
export type FieldType = 'text' | 'number' | 'date' | 'boolean';
export interface Source {
  kind: 'file' | 'datastore';
  sheet?: string | null;
  delimiter?: string | null;
  encoding?: string | null;
  date_format?: string | null;
  decimal?: string;
  types: Record<string, FieldType>;
}
export interface Widget {
  id: string;
  type: WidgetType;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
  x_field?: string | null;
  y_field?: string | null;
  series_field?: string | null;
  aggregate: string;
  limit: number;
  bins: number;
  color: string;
  lat_field?: string | null;
  lon_field?: string | null;
  columns?: string[];
  text?: string;
  unit?: string;
  time_grain?: string;
  sort?: string;
  show_legend?: boolean;
}
export interface FilterDefinition {
  field: string;
  type: 'category' | 'number' | 'date';
  label: string;
}
export interface Filter {
  field: string;
  op: 'in' | 'eq' | 'gte' | 'lte' | 'between';
  value: unknown;
}
export interface Bounds {
  widget_id?: string;
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
}
export interface Config {
  schema_version: 1;
  source: Source;
  widgets: Widget[];
  filters: FilterDefinition[];
  style: { accent: string };
}
export interface Bootstrap {
  mode: 'editor' | 'view';
  resource_id: string;
  view_id?: string;
  title: string;
  config: Config;
  lang: string;
  api_base: string;
  view_url?: string;
  embed_url?: string;
  resource_url?: string;
  basemap_url?: string;
  can_edit: boolean;
}
export interface Profile {
  status: string;
  refreshing?: boolean;
  generation: string;
  updated_at: string;
  rows: number;
  fields: { key: string; label: string; type: FieldType; examples: unknown[] }[];
  sheets: string[];
  warnings: string[];
}
export interface Result {
  type: WidgetType;
  error?: string;
  code?: string;
  value?: unknown;
  count?: number;
  valid_count?: number;
  labels?: unknown[];
  category_filters?: (Filter | null)[];
  datasets?: { label: string; data: any[] }[];
  columns?: { key: string; label: string }[];
  rows?: Record<string, unknown>[];
  total?: number;
  page?: number;
  page_size?: number;
  points?: { lat: number; lon: number; value?: number; count?: number }[];
  aggregated?: boolean;
  sampled?: boolean;
  truncated?: boolean;
  text?: string;
}
export interface QueryResult {
  status: string;
  refreshing?: boolean;
  generation: string;
  updated_at: string;
  rows: number;
  results: Record<string, Result>;
  warnings: string[];
}
export const emptyConfig = (): Config => ({
  schema_version: 1,
  source: {
    kind: 'file',
    sheet: null,
    delimiter: null,
    encoding: null,
    date_format: null,
    decimal: '.',
    types: {},
  },
  widgets: [],
  filters: [],
  style: { accent: '#0069b4' },
});
