import type { Config, FieldType, Profile, Widget } from './types';
import type { Translator } from './i18n';

export interface WidgetValidationIssue {
  widgetId: string;
  field: string;
  message: string;
}

/** Match the engine's column requirements; the server remains authoritative. */
export function validateWidgets(
  config: Config,
  profile: Profile | undefined,
  t: Translator,
): WidgetValidationIssue[] {
  if (!profile) return [];
  const fields = new Map(profile.fields.map((field) => [field.key, field]));
  const issues: WidgetValidationIssue[] = [];
  const requireField = (widget: Widget, field: keyof Widget, types?: FieldType[]) => {
    const key = widget[field] as string | null | undefined;
    const column = key ? fields.get(key) : undefined;
    let message: string | undefined;
    if (!key) message = t('fieldRequired').replace('{field}', () => t(field));
    else if (!column) message = t('fieldMissing').replace('{column}', () => key);
    else if (types && !types.includes(column.type))
      message = t('fieldIncompatible').replace('{column}', () => column.label);
    if (message) issues.push({ widgetId: widget.id, field, message });
  };
  const aggregate = (widget: Widget) => {
    if (widget.aggregate === 'count') return;
    const types: FieldType[] | undefined = widget.aggregate === 'count_distinct'
      ? undefined
      : widget.type === 'kpi' && ['min', 'max'].includes(widget.aggregate)
        ? ['number', 'date']
        : ['number'];
    requireField(widget, 'y_field', types);
  };
  for (const widget of config.widgets) {
    switch (widget.type) {
      case 'text':
        break;
      case 'table':
        if (widget.columns?.some((key) => !fields.has(key)))
          issues.push({ widgetId: widget.id, field: 'columns', message: t('tableColumnsMissing') });
        if (widget.x_field) requireField(widget, 'x_field');
        break;
      case 'kpi':
        aggregate(widget);
        break;
      case 'histogram':
        requireField(widget, widget.x_field ? 'x_field' : 'y_field', ['number']);
        break;
      case 'scatter':
        requireField(widget, 'x_field', ['number']);
        requireField(widget, 'y_field', ['number']);
        if (widget.series_field) requireField(widget, 'series_field');
        break;
      case 'map':
        requireField(widget, 'lat_field', ['number']);
        requireField(widget, 'lon_field', ['number']);
        aggregate(widget);
        break;
      default:
        requireField(widget, 'x_field', widget.time_grain && widget.time_grain !== 'none' ? ['date'] : undefined);
        aggregate(widget);
        if (widget.series_field) requireField(widget, 'series_field');
    }
  }
  return issues;
}
