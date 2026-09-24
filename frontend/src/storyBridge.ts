import type { Filter, Profile, Config } from './types';

export interface StoryState { filters: Filter[]; widgetId: string | null }

/** Only the CKAN parent may control an embedded viewer. Sharing remains read-only. */
export function storyState(value: unknown, profile: Profile, config: Config): StoryState {
  const data = value as Record<string, unknown>;
  if (!data || !Array.isArray(data.filters) || data.filters.length > 24)
    throw Error('Invalid story filters.');
  const fields = new Map(profile.fields.map(field => [field.key, field.type]));
  const filters = data.filters.map((filter: Filter) => {
    if (!filter || !fields.has(filter.field) || !['eq', 'in', 'gte', 'lte', 'between'].includes(filter.op))
      throw Error('A story filter is no longer available.');
    const values = ['in', 'between'].includes(filter.op) ? filter.value : [filter.value];
    if (!Array.isArray(values) || !values.length || values.length > 1000 ||
        (filter.op === 'between' && values.length !== 2) ||
        values.some(v => !['string', 'number', 'boolean'].includes(typeof v) ||
          (typeof v === 'number' && !Number.isFinite(v))))
      throw Error('Invalid story filter value.');
    return { field: filter.field, op: filter.op, value: filter.value };
  });
  const widgetId = typeof data.widgetId === 'string' && data.widgetId ? data.widgetId : null;
  if (widgetId && !config.widgets.some(widget => widget.id === widgetId))
    throw Error('This story chart is no longer available.');
  return { filters, widgetId };
}

export function connectStoryBridge(options: {
  viewId: string;
  metadata: () => { profile?: Profile; config: Config };
  apply: (state: StoryState) => Promise<boolean | undefined>;
  signal: AbortSignal;
}) {
  let revision = 0;
  const send = (data: Record<string, unknown>) => window.parent.postMessage(
    { version: 1, viewId: options.viewId, ...data }, window.location.origin);
  const ready = () => {
    const { profile, config } = options.metadata();
    if (profile) send({ type: 'dashboard:ready', fields: profile.fields,
      filters: config.filters, widgets: config.widgets.map(({ id, title, type }) => ({ id, title, type })) });
  };
  window.addEventListener('message', async event => {
    if (event.source !== window.parent || window.parent === window ||
        event.origin !== window.location.origin || event.data?.version !== 1) return;
    const data = event.data;
    if (data.type === 'dashboard:hello') { ready(); return; }
    if (data.type !== 'dashboard:applyState' || data.viewId !== options.viewId ||
        typeof data.requestId !== 'string' || data.requestId.length > 128) return;
    const current = ++revision;
    const reply = (fields: Record<string, unknown>) => send({
      type: 'dashboard:stateApplied', requestId: data.requestId, ...fields });
    try {
      const { profile, config } = options.metadata();
      if (!profile) throw Error('Dashboard is still loading.');
      const state = storyState(data.state, profile, config);
      reply({ phase: 'received' });
      const success = await options.apply(state);
      reply({ phase: 'complete', success: !!success, superseded: current !== revision });
    } catch (error) {
      reply({ phase: 'complete', success: false,
        error: error instanceof Error ? error.message : 'Unable to apply story filters.' });
    }
  }, { signal: options.signal });
  return ready;
}
