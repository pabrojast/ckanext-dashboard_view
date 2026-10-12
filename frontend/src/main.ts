import { GridStack, type GridStackNode } from 'gridstack';
import 'gridstack/dist/gridstack.min.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import {
  type Bootstrap,
  type Config,
  type Filter,
  type FilterDefinition,
  type Profile,
  type QueryResult,
  type Widget,
  type WidgetType,
  emptyConfig,
  type Bounds,
} from './types';
import { translator, serverMessage, type Translator } from './i18n';
import { button, download, el, icon } from './dom';
import { renderWidget, type Handle } from './render';
import { connectStoryBridge } from './storyBridge';
import { applyAppearance, normalizeStyle, resolveAppearance, presetStyle, contrastRatio, correctChartColor } from './appearance';
import { changeEffect } from './changes';
import { validateWidgets } from './validation';

const TYPES: WidgetType[] = [
  'kpi',
  'line',
  'bar',
  'area',
  'doughnut',
  'scatter',
  'histogram',
  'map',
  'table',
  'text',
];
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
class Dashboard {
  root: HTMLElement;
  boot: Bootstrap;
  config: Config;
  t: Translator;
  profile?: Profile;
  query?: QueryResult;
  grid?: GridStack;
  hidden: HTMLInputElement;
  form: HTMLFormElement | null;
  initial: string;
  initialTitle: string;
  instance = crypto.randomUUID().slice(0, 8);
  selected: string | null = null;
  panel = 'blocks';
  catalogExpanded = false;
  preview = false;
  mobile = false;
  dirty = false;
  sourceDraft: Config['source'];
  filters: Filter[] = [];
  bounds: Bounds | null = null;
  pages: Record<string, number> = {};
  history: Config[] = [];
  future: Config[] = [];
  handles = new Map<string, Handle>();
  canvas!: HTMLElement;
  inspector!: HTMLElement;
  catalog!: HTMLElement;
  filterBar!: HTMLElement;
  status!: HTMLElement;
  meta!: HTMLElement;
  toolbar!: HTMLElement;
  guide!: HTMLElement;
  toast!: HTMLElement;
  empty!: HTMLElement;
  generation = 0;
  profileRequest = 0;
  queryRequest = 0;
  requestTimer?: number;
  toastTimer?: number;
  refreshTimer?: number;
  refreshPoll?: number;
  ready = false;
  advancedOpen = false;
  storyReady?: () => void;
  layoutLoading = false;
  abort = new AbortController();
  constructor(root: HTMLElement, boot: Bootstrap) {
    this.root = root;
    root.closest<HTMLElement>('article.module')?.classList.add('dbv-host');
    boot.lang = (boot.lang || 'en').replaceAll('_', '-');
    this.boot = boot;
    this.t = translator(boot.lang);
    this.config = { ...emptyConfig(), ...clone(boot.config || emptyConfig()) };
    this.config.source = { ...emptyConfig().source, ...this.config.source };
    this.config.style = normalizeStyle(this.config.style);
    this.config.widgets = this.config.widgets.map((widget) =>
      Object.assign(
        {
          aggregate: 'count',
          limit: 20,
          bins: 20,
          color: '#0069b4',
          time_grain: 'none',
          sort: 'desc',
          show_legend: true,
        },
        widget,
      ),
    );
    this.sourceDraft = clone(this.config.source);
    this.initial = JSON.stringify(this.config);
    this.initialTitle = boot.title;
    this.form = root.closest('form');
    this.hidden =
      this.form?.querySelector<HTMLInputElement>('input[name=dashboard_config]') ?? el('input');
    this.hidden.type = 'hidden';
    this.hidden.name = 'dashboard_config';
    if (!this.hidden.parentElement) root.append(this.hidden);
    const title = this.form?.querySelector<HTMLInputElement>('[name=title]');
    if (title)
      title.addEventListener('input', () => {
        this.boot.title = title.value;
        this.root.querySelector<HTMLElement>('.dbv-heading')!.textContent =
          title.value || this.t('defaultTitle');
        this.dirty = true;
        this.updateToolbarState();
      });
    this.form?.addEventListener('submit', (event) => {
      this.sync();
      if (!this.validateSave()) {
        event.preventDefault();
        return;
      }
      this.dirty = false;
    });
    window.addEventListener(
      'beforeunload',
      (event) => {
        if (this.dirty) {
          event.preventDefault();
          event.returnValue = '';
        }
      },
      { signal: this.abort.signal },
    );
    root.classList.add('dbv');
    root.setAttribute('lang', boot.lang || 'en');
    this.build();
    this.sync();
    if (boot.mode === 'view' && boot.view_id && window.parent !== window) {
      this.storyReady = connectStoryBridge({
        viewId: boot.view_id, signal: this.abort.signal,
        metadata: () => ({ profile: this.profile, config: this.config }),
        apply: async state => {
          clearTimeout(this.requestTimer);
          this.filters = clone(state.filters);
          this.bounds = null;
          this.pages = {};
          for (const item of this.canvas.querySelectorAll<HTMLElement>('[data-widget-id]')) {
            const active = item.dataset.widgetId === state.widgetId;
            item.classList.toggle('is-story-highlighted', active);
            if (active) {
              // scrollIntoView also scrolls the host story through the iframe,
              // changing its active paragraph and resetting the narrative state.
              const rect = item.getBoundingClientRect();
              const offset = rect.top < 0 ? rect.top : Math.max(0,
                Math.min(rect.top, rect.bottom - window.innerHeight));
              if (offset) window.scrollBy({ top: offset, behavior: 'instant' });
            }
          }
          this.renderFilters();
          return this.loadQuery();
        },
      });
    }
    void this.loadProfile();
    this.refreshTimer = window.setInterval(() => {
      if (!document.hidden) void this.loadProfile(false);
    }, 300000);
    this.root.addEventListener('keydown', (event) => this.keydown(event));
  }
  editing() {
    return this.boot.mode === 'editor' && !this.preview;
  }
  build() {
    const shell = el('div', 'dbv-shell');
    const header = el('header', 'dbv-header');
    const brand = el('div', 'dbv-brand');
    const mark = el('div', 'dbv-brand-mark');
    mark.append(icon('bar'));
    const names = el('div');
    names.append(
      el('div', 'dbv-eyebrow', this.t(this.boot.mode === 'editor' ? 'builder' : 'eyebrow')),
      el('h2', 'dbv-heading', this.boot.title || this.t('defaultTitle')),
    );
    brand.append(mark, names);
    this.toolbar = el('div', 'dbv-toolbar');
    header.append(brand, this.toolbar);
    const info = el('div', 'dbv-info');
    this.meta = el('div', 'dbv-meta', this.t('loading'));
    info.append(this.meta);
    if (this.boot.resource_url) {
      const link = el('a', 'dbv-source-link', this.t('data'));
      link.href = this.boot.resource_url;
      link.append(icon('share'));
      info.append(link);
    }
    this.status = el('div', 'dbv-status');
    this.status.setAttribute('role', 'status');
    this.status.setAttribute('aria-live', 'polite');
    this.filterBar = el('div', 'dbv-filter-bar');
    this.guide = el('nav', 'dbv-guide');
    this.guide.setAttribute('aria-label', this.t('guideHelp'));
    const workspace = el('div', 'dbv-workspace');
    this.catalog = el('aside', 'dbv-catalog');
    this.catalog.setAttribute('aria-label', this.t('add'));
    const middle = el('main', 'dbv-stage');
    this.empty = el('div', 'dbv-empty');
    this.canvas = el('div', 'dbv-canvas grid-stack');
    middle.append(this.empty, this.canvas);
    this.inspector = el('aside', 'dbv-inspector');
    this.inspector.setAttribute('aria-label', this.t('properties'));
    workspace.append(this.catalog, middle, this.inspector);
    const footer = el('footer', 'dbv-footer');
    footer.append(
      el('span', '', this.t('keyboard')),
      el('span', 'dbv-brand-credit', 'IHP-WINS'),
    );
    this.toast = el('div', 'dbv-toast');
    this.toast.setAttribute('role', 'status');
    this.toast.hidden = true;
    shell.append(header, info, this.status, this.guide, this.filterBar, workspace, footer, this.toast);
    this.root.append(shell);
    this.renderToolbar();
    this.renderGuide();
    this.renderCatalog();
    this.renderInspector();
    this.renderFilters();
    this.renderGrid();
  }
  renderToolbar() {
    const t = this.t;
    this.toolbar.replaceChildren();
    if (this.boot.mode === 'editor') {
      const state = el(
        'span',
        'dbv-save-state',
        t(this.dirty || !this.boot.view_id ? 'unsaved' : 'saved'),
      );
      this.toolbar.append(state);
      const undo = button(t('undo'), () => this.undo(), 'dbv-btn dbv-icon-only', 'undo');
      undo.dataset.dashboardAction = 'undo';
      undo.disabled = !this.history.length;
      const redo = button(t('redo'), () => this.redo(), 'dbv-btn dbv-icon-only', 'redo');
      redo.dataset.dashboardAction = 'redo';
      redo.disabled = !this.future.length;
      this.toolbar.append(undo, redo);
      const preview = button(
        t(this.preview ? 'edit' : 'preview'),
        () => {
          this.preview = !this.preview;
          this.renderMode();
        },
        'dbv-btn',
        this.preview ? 'settings' : 'eye',
      );
      preview.setAttribute('aria-pressed', String(this.preview));
      this.toolbar.append(preview);
    }
    const mobile = button(
      t(this.mobile ? 'desktop' : 'mobile'),
      () => {
        this.mobile = !this.mobile;
        this.renderMode();
      },
      'dbv-btn',
      this.mobile ? 'desktop' : 'phone',
    );
    mobile.setAttribute('aria-pressed', String(this.mobile));
    this.toolbar.append(
      mobile,
      button(t('export'), () => void this.exportCsv(), 'dbv-btn', 'download'),
    );
    if (this.boot.can_edit)
      this.toolbar.append(
        button(t('refresh'), () => void this.refresh(), 'dbv-btn', 'refresh'),
      );
    this.toolbar.append(button(t('share'), () => this.share(), 'dbv-btn', 'share'));
    if (this.boot.mode === 'editor')
      this.toolbar.append(button(t('save'), () => this.save(), 'dbv-btn dbv-btn-primary', 'save'));
  }
  updateToolbarState() {
    // A field's change event can run between pointerdown and click on Save.
    // Keep the buttons attached so committing a focused field cannot consume
    // that first click (or move keyboard focus away from another action).
    const state = this.toolbar.querySelector('.dbv-save-state');
    if (state)
      state.textContent = this.t(this.dirty || !this.boot.view_id ? 'unsaved' : 'saved');
    const undo = this.toolbar.querySelector<HTMLButtonElement>('[data-dashboard-action="undo"]');
    if (undo) undo.disabled = !this.history.length;
    const redo = this.toolbar.querySelector<HTMLButtonElement>('[data-dashboard-action="redo"]');
    if (redo) redo.disabled = !this.future.length;
  }
  renderGuide() {
    this.guide.hidden = this.boot.mode !== 'editor';
    this.guide.replaceChildren();
    if (this.guide.hidden) return;
    const steps = ['reviewData', 'chooseBlocks', 'personalize', 'reviewSave'];
    steps.forEach((key, index) => {
      const control = button(`${index + 1}. ${this.t(key)}`, () => {
        const wasPreview = this.preview;
        this.preview = index === 3;
        if (!this.preview) this.panel = ['data', 'blocks', 'appearance'][index];
        if (wasPreview !== this.preview) this.renderMode();
        else { this.renderCatalog(); this.renderGuide(); }
        if (index === 3) this.notify(this.t('guideHelp'));
      }, 'dbv-btn dbv-guide-step');
      const active = this.preview ? index === 3 : ['data', 'blocks', 'appearance'][index] === this.panel;
      if (active) control.setAttribute('aria-current', 'step');
      this.guide.append(control);
    });
    this.guide.append(el('p', 'dbv-guide-help', this.t('guideHelp')));
  }
  renderAppearance() {
    const t = this.t;
    const panel = el('div', 'dbv-appearance');
    panel.append(el('h3', 'dbv-panel-label', t('appearance')));
    const presets = el('div', 'dbv-theme-presets');
    for (const [name, key] of [['light', 'themeLight'], ['ocean', 'themeOcean'], ['dark', 'themeDark']] as const) {
      const option = button(t(key), () => {
        this.mutate(() => { this.config.style = presetStyle(name); }, false);
        this.renderCatalog();
        this.renderInspector();
      }, 'dbv-btn dbv-theme-preset');
      option.dataset.themePreset = name;
      const sample = resolveAppearance(presetStyle(name));
      const swatch = el('span', 'dbv-theme-swatch');
      swatch.style.background = sample.background;
      swatch.style.borderColor = sample.accent;
      swatch.setAttribute('aria-hidden', 'true');
      option.prepend(swatch);
      presets.append(option);
    }
    panel.append(presets);
    const style = normalizeStyle(this.config.style);
    const appearance = resolveAppearance(style);
    for (const [key, value] of [
      ['background', style.background || appearance.background],
      ['card_background', style.card_background || appearance.cardBackground],
      ['accent', style.accent],
    ] as const) {
      const name = t(key === 'card_background' ? 'cardBackground' : key);
      const row = el('div', 'dbv-color-control');
      const color = this.input('color', value);
      color.setAttribute('aria-label', name);
      const hex = this.input('text', value);
      hex.maxLength = 7;
      hex.pattern = '#[0-9a-fA-F]{6}';
      hex.setAttribute('aria-label', `${name} · HEX`);
      const apply = (value: string) => {
        if (!/^#[0-9a-fA-F]{6}$/.test(value)) {
          hex.setAttribute('aria-invalid', 'true');
          this.notify(t('invalidColor'));
          return;
        }
        hex.removeAttribute('aria-invalid');
        color.value = value;
        hex.value = value;
        this.mutate(() => { this.config.style[key] = value; }, false);
        const colors = resolveAppearance(this.config.style).palette;
        panel.querySelectorAll<HTMLElement>('.dbv-palette-swatch').forEach((swatch, index) => {
          swatch.style.background = colors[index % colors.length];
          swatch.title = colors[index % colors.length];
        });
        this.renderContrastNotice(panel);
      };
      color.addEventListener('change', () => apply(color.value));
      hex.addEventListener('change', () => apply(hex.value));
      row.append(color, hex);
      const field = el('div', 'dbv-field');
      field.append(el('span', 'dbv-field-label', name), row);
      panel.append(field);
    }
    const palette = this.select('palette', [
      ['ihp', t('paletteIhp')], ['accessible', t('paletteAccessible')], ['mono', t('paletteMono')],
    ], style.palette);
    palette.addEventListener('change', () => {
      this.mutate(() => { this.config.style.palette = palette.value as typeof style.palette; }, false);
      this.renderCatalog();
    });
    panel.append(this.label(t('palette'), palette), el('p', 'dbv-panel-description', t('paletteHelp')));
    const swatches = el('div', 'dbv-palette-swatches');
    for (const color of appearance.palette) {
      const swatch = el('span', 'dbv-palette-swatch');
      swatch.style.background = color;
      swatch.title = color;
      swatches.append(swatch);
    }
    panel.append(swatches);
    this.renderContrastNotice(panel);
    panel.append(button(t('resetAppearance'), () => {
      this.mutate(() => { this.config.style = presetStyle('light'); }, false);
      this.renderCatalog();
      this.renderInspector();
    }, 'dbv-btn dbv-btn-wide', 'undo'));
    this.catalog.append(panel);
  }
  renderContrastNotice(panel: HTMLElement) {
    panel.querySelector('.dbv-contrast-notice')?.remove();
    const { cardBackground } = resolveAppearance(this.config.style);
    const low = this.config.widgets.filter(w => !['table', 'text', 'doughnut'].includes(w.type) && contrastRatio(w.color, cardBackground) < 3);
    if (!low.length) return;
    const note = el('div', 'dbv-contrast-notice dbv-callout');
    note.append(el('p', '', this.t('lowContrast')),
      button(this.t('fixContrast'), () => {
        this.mutate(() => { for (const widget of low) widget.color = correctChartColor(widget.color, cardBackground); }, false);
        this.renderContrastNotice(panel);
        this.renderInspector();
      }, 'dbv-btn dbv-btn-small'));
    panel.append(note);
  }
  renderMode() {
    this.root.classList.toggle('dbv-preview', !this.editing());
    this.root.classList.toggle('dbv-mobile-preview', this.mobile);
    this.renderToolbar();
    this.renderGuide();
    this.renderGrid();
    this.renderCatalog();
    this.renderInspector();
  }
  sync() {
    this.hidden.value = JSON.stringify(this.config);
    this.dirty = this.hidden.value !== this.initial || this.boot.title !== this.initialTitle;
    applyAppearance(this.root, this.config.style);
  }
  changed(previous: Config, rebuild = true, remember = true) {
    const effect = changeEffect(previous, this.config);
    if (remember) {
      this.history.push(previous);
      if (this.history.length > 60) this.history.shift();
      this.future = [];
    }
    this.sync();
    this.updateToolbarState();
    if (effect === 'visual') {
      this.updatePresentation(previous);
      if (rebuild) this.renderInspector();
      if (JSON.stringify(previous.filters) !== JSON.stringify(this.config.filters)) this.renderFilters();
      return;
    }
    if (rebuild) {
      this.renderGrid();
      this.renderInspector();
      this.renderFilters();
    }
    if (effect === 'source') {
      clearTimeout(this.requestTimer);
      this.queryRequest++;
      this.ready = false;
      this.filters = [];
      this.bounds = null;
      this.pages = {};
      void this.loadProfile();
    } else {
      this.scheduleQuery();
    }
  }
  updatePresentation(previous: Config) {
    const appearance = resolveAppearance(this.config.style);
    let layoutChanged = false;
    this.layoutLoading = true;
    this.grid?.batchUpdate();
    for (const widget of this.config.widgets) {
      const item = this.canvas.querySelector<HTMLElement>(`[data-widget-id="${widget.id}"]`);
      if (!item) continue;
      const old = previous.widgets.find(w => w.id === widget.id);
      if (old && ['x', 'y', 'w', 'h'].some(key => old[key as 'x'] !== widget[key as 'x'])) {
        layoutChanged = true;
        this.grid?.update(item, { x: widget.x, y: widget.y, w: widget.w, h: widget.h });
      }
      item.querySelector<HTMLElement>('.dbv-widget')?.style.setProperty('--widget-color', widget.color);
      const title = item.querySelector('.dbv-widget-title');
      if (title) title.textContent = widget.title || this.t(widget.type);
      if (this.editing()) item.querySelector('.dbv-widget-header')?.setAttribute('aria-label', `${widget.title}. ${this.t('keyboard')}`);
      this.handles.get(widget.id)?.updateAppearance?.(appearance, widget);
    }
    this.grid?.batchUpdate(false);
    // GridStack can move neighbors when a keyboard/button move collides with
    // another block. Persist the resolved layout, never the mobile stacking.
    if (layoutChanged && this.grid && this.grid.getColumn() !== 1) {
      for (const node of this.grid.engine.nodes) {
        const widget = this.config.widgets.find(w => w.id === node.id);
        if (widget) Object.assign(widget, { x: node.x ?? 0, y: node.y ?? 0, w: node.w ?? 6, h: node.h ?? 4 });
      }
      this.sync();
      this.updateToolbarState();
    }
    this.layoutLoading = false;
  }
  mutate(fn: () => void, rebuild = true) {
    const previous = clone(this.config);
    fn();
    this.changed(previous, rebuild);
  }
  undo() {
    const old = this.history.pop();
    if (!old) return;
    const previous = clone(this.config);
    this.future.push(previous);
    this.config = old;
    this.sourceDraft = clone(old.source);
    this.changed(previous, true, false);
    this.renderCatalog();
  }
  redo() {
    const next = this.future.pop();
    if (!next) return;
    const previous = clone(this.config);
    this.history.push(previous);
    this.config = next;
    this.sourceDraft = clone(next.source);
    this.changed(previous, true, false);
    this.renderCatalog();
  }
  validateSave() {
    if (!this.profile || !this.ready) {
      this.notify(this.t('loading'));
      return false;
    }
    const issues = validateWidgets(this.config, this.profile, this.t);
    if (!this.config.widgets.length || issues.length) {
      this.preview = false;
      this.renderMode();
      if (issues[0]) {
        this.selectWidget(issues[0].widgetId);
        this.inspector.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      }
      this.notify(this.t('validationSummary'));
      return false;
    }
    return true;
  }
  save() {
    this.sync();
    if (this.form) {
      const submit = this.form.querySelector<HTMLButtonElement>(
        'button[name=save],input[name=save],button[type=submit]:not([name=preview]),input[type=submit]:not([name=preview])',
      );
      if (submit) this.form.requestSubmit(submit);
      else this.form.requestSubmit();
    } else this.notify(this.t('saveError'));
  }
  showStatus(message: string, error = false) {
    this.status.replaceChildren();
    this.status.hidden = !message;
    this.status.classList.toggle('is-error', error);
    if (!message) return;
    if (!error) this.status.append(el('span', 'dbv-spinner'));
    this.status.append(el('span', '', message));
    if (error)
      this.status.append(
        button(this.t('retry'), () => void this.loadProfile(), 'dbv-btn dbv-btn-small', 'refresh'),
      );
  }
  notify(message: string) {
    this.toast.textContent = message;
    this.toast.hidden = false;
    clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => {
      this.toast.hidden = true;
    }, 4500);
  }
  csrf() {
    return (
      this.form?.querySelector<HTMLInputElement>('[name=_csrf_token],[name=csrf_token]')?.value ??
      this.root.querySelector<HTMLInputElement>('[name=_csrf_token],[name=csrf_token]')?.value ??
      document.querySelector<HTMLMetaElement>('meta[name=csrf-token]')?.content ??
      ''
    );
  }
  async post(path: string, body: unknown): Promise<Response> {
    return fetch(`${this.boot.api_base}/${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf() },
      body: JSON.stringify(body),
      signal: this.abort.signal,
    });
  }
  async poll<T>(path: string, body: unknown, active: () => boolean): Promise<T | null> {
    let wait = 800;
    while (active()) {
      const response = await this.post(path, body);
      const contentType = response.headers.get('content-type') ?? '';
      if (!contentType.includes('json')) throw Error(this.t('error'));
      const data = await response.json();
      if (!active()) return null;
      if (data.status === 'pending' || response.status === 202) {
        this.showStatus(serverMessage(data.message || this.t(path === 'query' ? 'loadingQuery' : 'loading'), this.t, data.code));
        await new Promise((resolve) => setTimeout(resolve, wait));
        wait = Math.min(4000, wait * 1.3);
        continue;
      }
      if (!response.ok || data.status === 'error') throw Error(serverMessage(data.message || this.t('error'), this.t, data.code));
      return data as T;
    }
    return null;
  }
  async loadProfile(show = true) {
    const request = ++this.profileRequest;
    try {
      if (show) this.showStatus(this.t('loading'));
      const source =
        this.boot.mode === 'editor'
          ? { source: clone(this.config.source) }
          : { view_id: this.boot.view_id };
      const profile = await this.poll<Profile>(
        'profile',
        source,
        () => request === this.profileRequest,
      );
      if (!profile) return;
      this.profile = profile;
      this.ready = true;
      this.revalidateLater(!!profile.refreshing && !this.config.widgets.length);
      this.meta.textContent = `${new Intl.NumberFormat(this.boot.lang).format(profile.rows)} ${this.t('rows')} · ${profile.fields.length} ${this.t('columns').toLowerCase()}`;
      this.renderCatalog();
      this.renderInspector();
      this.renderFilters();
      this.renderEmpty();
      this.storyReady?.();
      await this.loadQuery();
    } catch (error) {
      if (request === this.profileRequest)
        this.showStatus(error instanceof Error ? error.message : this.t('error'), true);
    }
  }
  selectors() {
    return this.boot.mode === 'editor'
      ? { config: clone(this.config) }
      : { view_id: this.boot.view_id };
  }
  scheduleQuery() {
    clearTimeout(this.requestTimer);
    this.requestTimer = window.setTimeout(() => void this.loadQuery(), 250);
  }
  async loadQuery() {
    if (!this.ready) return;
    const request = ++this.queryRequest;
    if (!this.config.widgets.length) {
      this.showStatus('');
      return;
    }
    try {
      this.canvas.setAttribute('aria-busy', 'true');
      const result = await this.poll<QueryResult>(
        'query',
        {
          ...this.selectors(),
          filters: clone(this.filters),
          bounds: this.bounds,
          pages: this.pages,
        },
        () => request === this.queryRequest,
      );
      if (!result) return;
      this.query = result;
      this.revalidateLater(!!result.refreshing);
      this.showStatus('');
      this.renderResults();
      this.renderFilters();
      const stamp = result.updated_at
        ? new Date(result.updated_at).toLocaleString(this.boot.lang)
        : '';
      this.meta.replaceChildren(
        el('span', 'dbv-ready-dot'),
        el(
          'span',
          '',
          `${new Intl.NumberFormat(this.boot.lang).format(result.rows)} ${this.t('rows')}`,
        ),
      );
      if (stamp)
        this.meta.append(
          el('span', 'dbv-meta-divider', '·'),
          el('span', '', `${this.t('updated')} ${stamp}`),
        );
      const warnings = [
        ...new Set([...(this.profile?.warnings ?? []), ...(result.warnings ?? [])]),
      ];
      if (warnings.length) {
        this.status.hidden = false;
        this.status.append(icon('info'), el('span', '', warnings.map(message => serverMessage(message, this.t)).join(' · ')));
      }
      this.canvas.setAttribute('aria-busy', 'false');
      return true;
    } catch (error) {
      if (request === this.queryRequest) {
        this.canvas.setAttribute('aria-busy', 'false');
        this.showStatus(error instanceof Error ? error.message : this.t('error'), true);
      }
      return false;
    }
  }
  revalidateLater(refreshing: boolean) {
    clearTimeout(this.refreshPoll);
    if (refreshing) this.refreshPoll = window.setTimeout(() => void this.loadProfile(false), 4000);
  }
  async refresh() {
    try {
      this.showStatus(this.t('processing'));
      const response = await this.post(
        'refresh',
        this.boot.mode === 'editor'
          ? { source: this.config.source }
          : { view_id: this.boot.view_id },
      );
      if (!response.ok && response.status !== 202) {
        const data = await response.json();
        throw Error(serverMessage(data.message, this.t, data.code));
      }
      await this.loadProfile();
    } catch (error) {
      this.showStatus(error instanceof Error ? error.message : this.t('error'), true);
    }
  }
  async exportCsv() {
    try {
      this.notify(this.t('downloadPending'));
      for (let tries = 0; tries < 90; tries++) {
        const response = await this.post('export', {
          ...this.selectors(),
          filters: this.filters,
          bounds: this.bounds,
        });
        if (response.headers.get('content-type')?.includes('json')) {
          const data = await response.json();
          if (data.status === 'pending') {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            continue;
          }
          throw Error(serverMessage(data.message || this.t('exportError'), this.t, data.code));
        }
        if (!response.ok) throw Error(this.t('exportError'));
        download(await response.blob(), `${this.boot.title || 'dashboard'}.csv`);
        return;
      }
      throw Error(this.t('waiting'));
    } catch (error) {
      this.notify(error instanceof Error ? error.message : this.t('exportError'));
    }
  }
  renderCatalog() {
    this.catalog.classList.toggle('is-blocks', this.panel === 'blocks');
    this.catalog.classList.toggle('is-expanded', this.catalogExpanded);
    this.catalog.hidden = !this.editing();
    if (!this.editing()) return;
    const t = this.t;
    this.catalog.replaceChildren();
    const tabs = el('div', 'dbv-tabs');
    for (const key of ['blocks', 'data', 'appearance']) {
      const tab = button(
        t(key === 'blocks' ? 'design' : key),
        () => {
          this.panel = key;
          this.renderCatalog();
          this.renderGuide();
        },
        `dbv-tab ${this.panel === key ? 'is-active' : ''}`,
        key === 'blocks' ? 'grid' : key === 'data' ? 'data' : 'settings',
      );
      tab.setAttribute('aria-pressed', String(this.panel === key));
      tabs.append(tab);
    }
    this.catalog.append(tabs);
    if (this.panel === 'appearance') {
      this.renderAppearance();
      return;
    }
    if (this.panel === 'data') {
      this.renderSource();
      return;
    }
    this.catalog.append(el('h3', 'dbv-panel-label', t('add')));
    const list = el('div', 'dbv-block-list');
    for (const type of TYPES) {
      const add = button(t(type), () => this.addWidget(type), 'dbv-block-option', type);
      add.disabled = !this.ready || this.config.widgets.length >= 24;
      list.append(add);
    }
    this.catalog.append(
      list,
      button(
        t(this.catalogExpanded ? 'fewerOptions' : 'moreOptions'),
        () => {
          this.catalogExpanded = !this.catalogExpanded;
          this.renderCatalog();
        },
        'dbv-btn dbv-catalog-expand',
        'settings',
      ),
      el('h3', 'dbv-panel-label', t('useTemplate')),
    );
    for (const name of ['overview', 'timeSeries', 'spatial'])
      this.catalog.append(
        button(
          t(name),
          () => this.chooseTemplate(name),
          'dbv-template-mini',
          name === 'spatial' ? 'map' : name === 'timeSeries' ? 'line' : 'grid',
        ),
      );
    this.catalog.append(el('h3', 'dbv-panel-label', t('filters')));
    const field = this.select(
      '',
      this.profile?.fields.map((f) => [f.key, f.label]) ?? [],
      '',
      true,
    );
    field.setAttribute('aria-label', t('selectField'));
    const addFilter = button(
      t('addFilter'),
      () => {
        if (field.value) this.addFilter(field.value);
      },
      'dbv-btn dbv-btn-wide',
      'plus',
    );
    this.catalog.append(field, addFilter);
    for (const def of this.config.filters) {
      const label = this.input('text', def.label);
      label.maxLength = 200;
      label.addEventListener('change', () =>
        this.mutate(() => {
          def.label = label.value || def.field;
        }),
      );
      const type = this.select(
        '',
        ['category', 'number', 'date'].map((k) => [k, t(k)]),
        def.type,
      );
      type.addEventListener('change', () => {
        this.filters = this.filters.filter((f) => f.field !== def.field);
        this.mutate(() => {
          def.type = type.value as FilterDefinition['type'];
        });
      });
      const box = el('div', 'dbv-filter-settings');
      box.append(
        this.label(def.field + ' · ' + t('filterLabel'), label),
        this.label(t('filters'), type),
      );
      this.catalog.append(box);
    }
  }
  renderSource() {
    const t = this.t;
    this.catalog.append(el('p', 'dbv-panel-description', t('sourceHelp')));
    const draft = this.sourceDraft;
    const kind = this.select(
      'kind',
      [
        ['file', t('file')],
        ['datastore', t('datastore')],
      ],
      draft.kind,
    );
    kind.addEventListener('change', () => {
      draft.kind = kind.value as 'file' | 'datastore';
    });
    this.catalog.append(this.label(t('kind'), kind));
    const advanced = el('details', 'dbv-inspector-section');
    advanced.append(el('summary', '', t('advancedOptions')));
    const fields: [string, HTMLInputElement | HTMLSelectElement][] = [
      [
        'sheet',
        this.select(
          'sheet',
          (this.profile?.sheets ?? []).map((s) => [s, s]),
          draft.sheet ?? '',
          true,
        ),
      ],
      [
        'delimiter',
        this.select(
          'delimiter',
          [
            [',', ','],
            [';', ';'],
            ['\t', 'Tab'],
            ['|', '|'],
          ],
          draft.delimiter ?? '',
          true,
        ),
      ],
      [
        'encoding',
        this.select(
          'encoding',
          [
            ['utf-8', 'UTF-8'],
            ['utf-8-sig', 'UTF-8 BOM'],
            ['latin-1', 'Latin-1'],
            ['cp1252', 'Windows-1252'],
          ],
          draft.encoding ?? '',
          true,
        ),
      ],
      [
        'decimal',
        this.select(
          'decimal',
          [
            ['.', '.'],
            [',', ','],
          ],
          draft.decimal ?? '.',
        ),
      ],
      ['date_format', this.input('text', draft.date_format ?? '')],
    ];
    for (const [key, input] of fields) {
      input.addEventListener('change', () => {
        (draft as unknown as Record<string, unknown>)[key] = input.value || null;
      });
      if (key === 'date_format') (input as HTMLInputElement).placeholder = '%d/%m/%Y';
      (key === 'sheet' ? this.catalog : advanced).append(this.label(t(key), input));
    }
    this.catalog.append(advanced);
    this.catalog.append(el('h3', 'dbv-panel-label', t('fieldTypes')));
    for (const field of this.profile?.fields ?? []) {
      const select = this.select(
        '',
        ['text', 'number', 'date', 'boolean'].map((type) => [type, t(type)]),
        draft.types[field.key] ?? field.type,
      );
      select.addEventListener('change', () => {
        draft.types[field.key] = select.value as typeof field.type;
      });
      const label = this.label(field.label, select);
      label.append(
        el(
          'small',
          'dbv-field-example',
          (field.examples ?? []).slice(0, 3).map(String).join(' · '),
        ),
      );
      this.catalog.append(label);
    }
    if (!this.profile?.fields.length) this.catalog.append(el('p', 'dbv-muted', t('noFields')));
    this.catalog.append(
      button(
        t('applySource'),
        () => {
          if (JSON.stringify(this.config.source) === JSON.stringify(draft)) {
            void this.loadProfile();
            return;
          }
          this.mutate(() => {
            this.config.source = clone(draft);
          }, false);
        },
        'dbv-btn dbv-btn-primary dbv-btn-wide',
        'refresh',
      ),
    );
  }
  newWidget(type: WidgetType): Widget {
    const fields = this.profile?.fields ?? [];
    const number = fields.find((f) => f.type === 'number');
    const category = fields.find((f) => f.type === 'text' || f.type === 'boolean');
    const date = fields.find((f) => f.type === 'date');
    const lat = fields.find((f) => /^lat(itude)?$/i.test(f.key));
    const lon = fields.find((f) => /^(lon(gitude)?|lng)$/i.test(f.key));
    const bottom = Math.max(0, ...this.config.widgets.map((w) => w.y + w.h));
    return {
      id: `w_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`,
      type,
      title: this.t(type),
      x: 0,
      y: bottom,
      w: type === 'kpi' ? 3 : type === 'table' || type === 'text' ? 12 : 6,
      h: type === 'kpi' ? 2 : type === 'map' ? 5 : type === 'text' ? 3 : 4,
      x_field:
        type === 'histogram' || type === 'scatter'
          ? number?.key
          : ((type === 'line' || type === 'area' ? date?.key : category?.key) ?? fields[0]?.key),
      y_field:
        type === 'scatter'
          ? (fields.filter((f) => f.type === 'number')[1]?.key ?? number?.key)
          : number?.key,
      series_field: null,
      aggregate: type === 'kpi' ? 'count' : number ? 'avg' : 'count',
      limit: 20,
      bins: 20,
      color: this.config.style.accent,
      lat_field: lat?.key,
      lon_field: lon?.key,
      columns: fields.slice(0, 8).map((f) => f.key),
      text: '',
      unit: '',
      time_grain: date && (type === 'line' || type === 'area') ? 'month' : 'none',
      sort: 'desc',
      show_legend: true,
    };
  }
  addWidget(type: WidgetType) {
    if (this.config.widgets.length >= 24) {
      this.notify(this.t('limitWidgets'));
      return;
    }
    const widget = this.newWidget(type);
    this.selected = widget.id;
    this.mutate(() => this.config.widgets.push(widget));
    this.root
      .querySelector(`[data-widget-id="${widget.id}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  chooseTemplate(name: string) {
    if (!this.ready) return;
    const t = this.t;
    const fields = this.profile?.fields ?? [];
    const values = fields.filter(f => f.type === 'number');
    const suggested = values.find(f => !/^(lat(itude)?|lon(gitude)?|lng|id)$/i.test(f.key)) ?? values[0];
    const dialog = el('dialog', 'dbv-dialog');
    const header = el('div', 'dbv-dialog-head');
    header.append(el('h3', '', t(name)), button(t('close'), () => dialog.close(), 'dbv-btn dbv-icon-only', 'close'));
    const main = this.select('template_value', values.map(f => [f.key, f.label]), suggested?.key ?? '', true);
    main.setAttribute('aria-label', t('mainVariable'));
    const fieldsPreview = el('div', 'dbv-template-fields');
    const update = () => {
      const sample = this.newWidget(name === 'spatial' ? 'map' : name === 'timeSeries' ? 'line' : 'bar');
      const names = name === 'spatial' ? [sample.lat_field, sample.lon_field] : [sample.x_field];
      const category = fields.find(f => f.type === 'text' || f.type === 'boolean') ?? fields[0];
      const filterFields = fields.filter(f => f.type === 'text' || f.type === 'date').slice(0, 2);
      const fieldsUsed = [...new Set([...names, main.value, category?.key,
        ...fields.slice(0, 8).map(f => f.key), ...filterFields.map(f => f.key)].filter(Boolean))];
      fieldsPreview.textContent = `${t('templateFields')}: ${fieldsUsed.map(key => fields.find(f => f.key === key)?.label ?? key).join(' · ') || t('count')}`;
    };
    main.addEventListener('change', update);
    update();
    dialog.append(header, el('p', 'dbv-panel-description', t(name + 'Desc')),
      this.label(t('mainVariable'), main), fieldsPreview,
      button(t('applyTemplate'), () => { this.template(name, main.value); dialog.close(); }, 'dbv-btn dbv-btn-primary'),
      button(t('cancel'), () => dialog.close(), 'dbv-btn'));
    dialog.addEventListener('close', () => dialog.remove());
    this.root.append(dialog);
    dialog.showModal();
  }
  template(name: string, measure = '') {
    if (!this.ready) return;
    if (this.config.widgets.length && !window.confirm(this.t('replaceTemplate'))) return;
    const fields = this.profile?.fields ?? [];
    if (
      (name === 'timeSeries' && !fields.some((f) => f.type === 'date')) ||
      (name === 'spatial' && (!fields.some((f) => f.type === 'number' && /^lat(itude)?$/i.test(f.key)) ||
        !fields.some((f) => f.type === 'number' && /^(lon(gitude)?|lng)$/i.test(f.key))))
    ) {
      this.notify(this.t('templateUnavailable'));
      this.panel = 'data';
      this.renderCatalog();
      return;
    }
    const a = this.newWidget('kpi');
    a.title = this.t('rowCount');
    a.x = 0;
    a.y = 0;
    a.w = 3;
    const b = this.newWidget('kpi');
    b.aggregate = b.y_field ? 'avg' : 'count';
    b.title = b.y_field ? `${this.t('avg')} · ${b.y_field}` : this.t('count');
    b.x = 3;
    b.y = 0;
    b.w = 3;
    const c = this.newWidget('kpi');
    c.aggregate = c.y_field ? 'max' : 'count';
    c.title = c.y_field ? `${this.t('max')} · ${c.y_field}` : this.t('count');
    c.x = 6;
    c.y = 0;
    c.w = 3;
    const d = this.newWidget('kpi');
    d.aggregate = d.y_field ? 'min' : 'count';
    d.title = d.y_field ? `${this.t('min')} · ${d.y_field}` : this.t('count');
    d.x = 9;
    d.y = 0;
    d.w = 3;
    const left = this.newWidget(
      name === 'spatial' ? 'map' : name === 'timeSeries' ? 'line' : 'bar',
    );
    left.x = 0;
    left.y = 2;
    left.w = 8;
    left.h = 5;
    const right = this.newWidget('doughnut');
    right.x = 8;
    right.y = 2;
    right.w = 4;
    right.h = 5;
    right.aggregate = 'count';
    const table = this.newWidget('table');
    table.y = 7;
    table.x = 0;
    table.w = 12;
    table.h = 4;
    for (const widget of [b, c, d, left]) {
      widget.y_field = measure || null;
      if (!measure) widget.aggregate = 'count';
      if (widget.type === 'kpi') widget.title = measure ? `${this.t(widget.aggregate)} · ${measure}` : this.t('count');
    }
    this.selected = left.id;
    this.bounds = null;
    this.mutate(() => {
      this.config.widgets = [a, b, c, d, left, right, table];
      this.config.filters = fields
        .filter((f) => f.type === 'text' || f.type === 'date')
        .slice(0, 2)
        .map((f) => ({
          field: f.key,
          label: f.label,
          type: f.type === 'date' ? 'date' : 'category',
        }));
    });
    this.filters = [];
    this.pages = {};
    this.renderFilters();
  }
  renderEmpty() {
    const empty = !this.config.widgets.length;
    this.empty.hidden = !empty;
    this.canvas.hidden = empty;
    this.empty.replaceChildren();
    if (!empty) return;
    const mark = el('div', 'dbv-empty-mark');
    mark.append(icon('bar'));
    this.empty.append(mark, el('h3', '', this.t(this.editing() ? 'emptyTitle' : 'emptyViewer')));
    if (!this.editing()) return;
    this.empty.append(el('p', '', this.t('emptyBody')));
    const choices = el('div', 'dbv-template-choices');
    for (const name of ['overview', 'timeSeries', 'spatial']) {
      const choice = button(
        this.t(name),
          () => this.chooseTemplate(name),
        'dbv-template-card',
        name === 'spatial' ? 'map' : name === 'timeSeries' ? 'line' : 'grid',
      );
      choice.append(el('small', '', this.t(name + 'Desc')));
      choice.disabled = !this.ready;
      choices.append(choice);
    }
    this.empty.append(choices);
  }
  renderGrid() {
    this.layoutLoading = true;
    this.handles.forEach((h) => h.destroy());
    this.handles.clear();
    this.grid?.destroy(false);
    this.canvas.replaceChildren();
    this.root.classList.toggle('dbv-preview', !this.editing());
    this.renderEmpty();
    for (const widget of this.config.widgets) {
      const item = el('section', 'grid-stack-item');
      item.dataset.widgetId = widget.id;
      item.setAttribute('gs-id', widget.id);
      for (const key of ['x', 'y', 'w', 'h'] as const)
        item.setAttribute('gs-' + key, String(widget[key]));
      item.setAttribute(
        'gs-min-h',
        String(
          widget.type === 'map' ? 5 : widget.type === 'kpi' ? 2 : widget.type === 'text' ? 2 : 4,
        ),
      );
      item.setAttribute('gs-min-w', '2');
      item.setAttribute('gs-max-h', '50');
      const content = el('div', 'grid-stack-item-content dbv-widget');
      content.style.setProperty('--widget-color', widget.color);
      const head = el('header', 'dbv-widget-header');
      if (this.editing()) {
        head.tabIndex = 0;
        head.setAttribute('aria-label', `${widget.title}. ${this.t('keyboard')}`);
        head.append(icon('grip'));
        head.addEventListener('click', () => this.selectWidget(widget.id));
      }
      head.append(el('h3', 'dbv-widget-title', widget.title || this.t(widget.type)));
      const tools = el('div', 'dbv-widget-tools');
      if (this.editing())
        tools.append(
          button(
            this.t('configure'),
            () => this.selectWidget(widget.id),
            'dbv-btn dbv-icon-only dbv-btn-small',
            'settings',
          ),
        );
      if (!['kpi', 'map', 'table', 'text'].includes(widget.type))
        tools.append(
          button(
            this.t('png'),
            () => {
              const url = this.handles.get(widget.id)?.png?.();
              if (url) {
                const a = el('a');
                a.href = url;
                a.download = `${widget.title || widget.type}.png`;
                a.click();
              }
            },
            'dbv-btn dbv-icon-only dbv-btn-small',
            'download',
          ),
        );
      head.append(tools);
      const body = el('div', 'dbv-widget-body');
      content.append(head, body);
      item.append(content);
      this.canvas.append(item);
    }
    this.grid =
      GridStack.init(
        {
          column: 12,
          cellHeight: 72,
          margin: 7,
          animate: true,
          float: true,
          handle: '.dbv-widget-header',
          staticGrid: !this.editing(),
          columnOpts: { breakpoints: [{ w: 640, c: 1 }] },
          resizable: { handles: 'se' },
          draggable: { cancel: 'button,input,textarea,select,a' },
        },
        this.canvas,
      ) ?? undefined;
    this.grid?.on('change', (_event, items: GridStackNode[]) => {
      if (this.layoutLoading || this.grid?.getColumn() === 1) return;
      const previous = clone(this.config);
      for (const node of items) {
        const w = this.config.widgets.find((w) => w.id === node.id);
        if (w) {
          w.x = node.x ?? 0;
          w.y = node.y ?? 0;
          w.w = node.w ?? 6;
          w.h = node.h ?? 4;
        }
      }
      if (JSON.stringify(previous) !== JSON.stringify(this.config)) this.changed(previous, false);
    });
    this.layoutLoading = false;
    this.selectWidget(this.selected, false);
    this.renderResults();
  }
  renderResults() {
    for (const widget of this.config.widgets) {
      const body = this.canvas.querySelector<HTMLElement>(
        `[data-widget-id="${widget.id}"] .dbv-widget-body`,
      );
      if (!body) continue;
      this.handles.get(widget.id)?.destroy();
      this.handles.set(
        widget.id,
        renderWidget(body, widget, this.query?.results[widget.id], {
          t: this.t,
          locale: this.boot.lang || 'en',
          basemap: this.boot.basemap_url,
          appearance: resolveAppearance(this.config.style),
          filter: (filter) => this.setFilter(filter),
          bounds: (bounds) => {
            this.bounds = bounds;
            this.pages = {};
            this.renderFilters();
            void this.loadQuery();
          },
          page: (page) => {
            this.pages[widget.id] = page;
            void this.loadQuery();
          },
        }),
      );
    }
  }
  selectWidget(id: string | null, render = true) {
    const previous = this.selected;
    this.selected = id;
    for (const item of this.canvas.querySelectorAll<HTMLElement>('[data-widget-id]'))
      item.classList.toggle('is-selected', this.editing() && item.dataset.widgetId === id);
    if (render) this.renderInspector();
    if (render && id && window.matchMedia('(max-width: 950px)').matches)
      this.inspector.querySelector<HTMLElement>('button')?.focus({ preventScroll: true });
    if (render && !id && previous)
      this.canvas.querySelector<HTMLElement>(`[data-widget-id="${previous}"] .dbv-widget-header`)?.focus({ preventScroll: true });
  }
  input(type: string, value: string) {
    const input = el('input', 'dbv-input');
    input.type = type;
    input.value = value;
    return input;
  }
  select(name: string, options: string[][], value: string, optional = false) {
    const select = el('select', 'dbv-input');
    select.dataset.property = name;
    if (optional) {
      const opt = el(
        'option',
        '',
        this.t(
          name === 'sheet' || name === 'delimiter' || name === 'encoding' ? 'automatic' : 'none',
        ),
      );
      opt.value = '';
      select.append(opt);
    }
    for (const [key, label] of options) {
      const opt = el('option', '', label);
      opt.value = key;
      select.append(opt);
    }
    if (value && !options.some((o) => o[0] === value)) {
      const missing = el('option', '', value + ' ⚠');
      missing.value = value;
      select.append(missing);
    }
    select.value = value;
    return select;
  }
  label(text: string, input: HTMLElement) {
    const label = el('label', 'dbv-field');
    label.append(el('span', 'dbv-field-label', text), input);
    return label;
  }
  renderInspector() {
    this.root.classList.toggle('dbv-has-selection', !!this.selected && this.editing());
    this.inspector.hidden = !this.editing();
    this.inspector.replaceChildren();
    if (!this.editing()) return;
    const t = this.t;
    const header = el('div', 'dbv-panel-heading');
    header.append(
      el('h3', '', t('properties')),
      button(
        t('close'),
        () => this.selectWidget(null),
        'dbv-btn dbv-icon-only dbv-btn-small',
        'close',
      ),
    );
    this.inspector.append(header);
    const widget = this.config.widgets.find((w) => w.id === this.selected);
    if (!widget) {
      const hint = el('div', 'dbv-inspector-empty');
      hint.append(
        icon('settings'),
        el('strong', '', t('chooseBlock')),
        el('p', '', t('chooseBody')),
      );
      this.inspector.append(hint);
      return;
    }
    this.inspector.append(el('span', 'dbv-widget-type', t(widget.type)));
    const data = el('section', 'dbv-inspector-section');
    data.append(el('h3', 'dbv-panel-label', t('data')));
    const appearance = el('section', 'dbv-inspector-section');
    appearance.append(el('h3', 'dbv-panel-label', t('appearance')));
    const advanced = el('details', 'dbv-inspector-section');
    advanced.open = this.advancedOpen;
    advanced.append(el('summary', '', t('advancedOptions')));
    advanced.addEventListener('toggle', () => { this.advancedOpen = advanced.open; });
    this.inspector.append(data, appearance, advanced);
    const modify = (key: string, value: unknown) =>
      this.mutate(() => {
        (widget as unknown as Record<string, unknown>)[key] = value;
      });
    const title = this.input('text', widget.title);
    title.maxLength = 200;
    title.addEventListener('change', () => modify('title', title.value));
    title.dataset.property = 'title';
    data.append(this.label(t('title'), title));
    const fields = this.profile?.fields ?? [];
    const fieldControl = (
      key: 'x_field' | 'y_field' | 'series_field' | 'lat_field' | 'lon_field',
      numeric = false,
    ) => {
      const select = this.select(
        key,
        fields.filter((f) => !numeric || f.type === 'number' ||
          (key === 'y_field' && widget.type === 'kpi' && ['min', 'max'].includes(widget.aggregate) && f.type === 'date')).map((f) => [f.key, f.label]),
        widget[key] ?? '',
        true,
      );
      select.addEventListener('change', () => modify(key, select.value || null));
      data.append(this.label(t(key), select));
    };
    if (['line', 'area', 'bar', 'doughnut', 'scatter', 'histogram', 'table'].includes(widget.type))
      fieldControl('x_field', widget.type === 'scatter' || widget.type === 'histogram');
    if (
      !['table', 'text', 'histogram'].includes(widget.type) &&
      (widget.aggregate !== 'count' || widget.type === 'scatter')
    )
      fieldControl('y_field', !['count', 'count_distinct'].includes(widget.aggregate));
    if (['line', 'area', 'bar', 'scatter'].includes(widget.type) ||
      (widget.type === 'doughnut' && widget.series_field)) fieldControl('series_field');
    if (!['table', 'text', 'scatter', 'histogram'].includes(widget.type)) {
      const aggregate = this.select(
        'aggregate',
        ['count', 'count_distinct', 'sum', 'avg', 'median', 'min', 'max'].map((k) => [k, t(k)]),
        widget.aggregate,
      );
      aggregate.addEventListener('change', () => modify('aggregate', aggregate.value));
      data.append(this.label(t('aggregate'), aggregate));
    }
    if (widget.type === 'map') {
      fieldControl('lat_field', true);
      fieldControl('lon_field', true);
    }
    if (widget.type === 'table') {
      const group = el('div', 'dbv-columns');
      group.dataset.property = 'columns';
      group.tabIndex = -1;
      if (widget.columns?.some(key => !fields.some(field => field.key === key)))
        group.append(button(t('allColumns'), () => modify('columns', []), 'dbv-btn dbv-btn-small'));
      for (const field of fields) {
        const checkbox = this.input('checkbox', '');
        checkbox.checked = !widget.columns?.length || widget.columns.includes(field.key);
        checkbox.addEventListener('change', () => {
          const visible = new Set(
            widget.columns?.length ? widget.columns.filter(key => fields.some(f => f.key === key)) : fields.map((f) => f.key),
          );
          checkbox.checked ? visible.add(field.key) : visible.delete(field.key);
          if (!visible.size) {
            checkbox.checked = true;
            return;
          }
          modify('columns', [...visible]);
        });
        const label = el('label', 'dbv-check');
        label.append(checkbox, el('span', '', field.label));
        group.append(label);
      }
      data.append(this.label(t('columns'), group));
    }
    if (widget.type === 'text') {
      const text = el('textarea', 'dbv-input');
      text.value = widget.text || '';
      text.rows = 8;
      text.maxLength = 10000;
      text.placeholder = t('textPlaceholder');
      text.addEventListener('change', () => modify('text', text.value));
      data.append(this.label(t('text'), text));
    }
    if (!['table', 'text'].includes(widget.type)) {
      if (widget.type !== 'doughnut') {
        const color = this.input('color', widget.color);
        color.addEventListener('change', () => modify('color', color.value));
        appearance.append(this.label(t('principalColor'), color));
        const background = resolveAppearance(this.config.style).cardBackground;
        if (contrastRatio(widget.color, background) < 3) {
          appearance.append(el('p', 'dbv-field-error', t('lowContrast')),
            button(t('fixContrast'), () => modify('color', correctChartColor(widget.color, background)), 'dbv-btn dbv-btn-small'));
        }
      }
      if (widget.type === 'doughnut' || widget.series_field)
        appearance.append(button(t('palette'), () => { this.panel = 'appearance'; this.selectWidget(null); this.renderCatalog(); this.renderGuide(); }, 'dbv-btn'));
      const unit = this.input('text', widget.unit || '');
      unit.maxLength = 40;
      unit.addEventListener('change', () => modify('unit', unit.value));
      appearance.append(this.label(t('unit'), unit));
    }
    if (['bar', 'line', 'area', 'doughnut'].includes(widget.type)) {
      const limit = this.input('number', String(widget.limit));
      limit.min = '1';
      limit.max = '100';
      limit.addEventListener('change', () =>
        modify('limit', Math.max(1, Math.min(100, Number(limit.value) || 20))),
      );
      advanced.append(this.label(t('limit'), limit));
    }
    if (!['kpi', 'text', 'table'].includes(widget.type)) {
      const legend = this.input('checkbox', '');
      legend.checked = widget.show_legend !== false;
      legend.addEventListener('change', () => modify('show_legend', legend.checked));
      const label = el('label', 'dbv-check');
      label.append(legend, el('span', '', t('show_legend')));
      appearance.append(label);
    }
    if (widget.type === 'histogram') {
      const bins = this.input('number', String(widget.bins));
      bins.min = '2';
      bins.max = '100';
      bins.addEventListener('change', () =>
        modify('bins', Math.max(2, Math.min(100, Number(bins.value) || 20))),
      );
      advanced.append(this.label(t('bins'), bins));
    }
    if (['line', 'area', 'bar'].includes(widget.type)) {
      const grain = this.select(
        'time_grain',
        ['none', 'day', 'month', 'year'].map((k) => [k, t(k)]),
        widget.time_grain || 'none',
      );
      grain.addEventListener('change', () => modify('time_grain', grain.value));
      data.append(this.label(t('time_grain'), grain));
    }
    if (!['kpi', 'text', 'map', 'scatter', 'table', 'histogram'].includes(widget.type)) {
      const sort = this.select(
        'sort',
        ['asc', 'desc'].map((k) => [k, t(k)]),
        widget.sort || 'desc',
      );
      sort.addEventListener('change', () => modify('sort', sort.value));
      advanced.append(this.label(t('sort'), sort));
    }
    advanced.append(el('h3', 'dbv-panel-label', t('move')));
    const position = el('div', 'dbv-position-controls');
    for (const [key, dx, dy] of [
      ['left', -1, 0],
      ['up', 0, -1],
      ['down', 0, 1],
      ['right', 1, 0],
    ] as const)
      position.append(
        button(t(key), () => this.move(widget, dx, dy, false), 'dbv-btn dbv-icon-only', key),
      );
    advanced.append(position, el('h3', 'dbv-panel-label', t('resize')));
    const sizes = el('div', 'dbv-size-controls');
    for (const [key, dx, dy] of [
      ['narrower', -1, 0],
      ['wider', 1, 0],
      ['shorter', 0, -1],
      ['taller', 0, 1],
    ] as const)
      sizes.append(button(t(key), () => this.move(widget, dx, dy, true), 'dbv-btn dbv-btn-small'));
    advanced.append(sizes);
    const actions = el('div', 'dbv-inspector-actions');
    actions.append(
      button(t('duplicate'), () => this.duplicate(widget), 'dbv-btn', 'copy'),
      button(t('delete'), () => this.remove(widget), 'dbv-btn dbv-danger', 'trash'),
    );
    this.inspector.append(actions);
    appearance.hidden = appearance.children.length === 1;
    const issues = validateWidgets(this.config, this.profile, this.t).filter(issue => issue.widgetId === widget.id);
    for (const [index, issue] of issues.entries()) {
      const property = widget.type === 'histogram' && issue.field === 'y_field' ? 'x_field' : issue.field;
      const input = this.inspector.querySelector<HTMLElement>(`[data-property="${property}"]`);
      const message = el('p', 'dbv-field-error', issue.message);
      message.id = `validation_${this.instance}_${widget.id}_${index}`;
      if (input) {
        input.setAttribute('aria-invalid', 'true');
        input.setAttribute('aria-describedby', message.id);
        (input.closest('.dbv-field') ?? input.parentElement)?.append(message);
      } else data.append(message);
    }
  }
  move(widget: Widget, dx: number, dy: number, size: boolean) {
    this.mutate(() => {
      if (size) {
        widget.w = Math.max(2, Math.min(12 - widget.x, widget.w + dx));
        widget.h = Math.max(
          widget.type === 'map' ? 5 : widget.type === 'kpi' || widget.type === 'text' ? 2 : 4,
          Math.min(50, widget.h + dy),
        );
      } else {
        widget.x = Math.max(0, Math.min(12 - widget.w, widget.x + dx));
        widget.y = Math.max(0, widget.y + dy);
      }
    });
    this.canvas
      .querySelector<HTMLElement>(`[data-widget-id="${widget.id}"] .dbv-widget-header`)
      ?.focus();
  }
  duplicate(widget: Widget) {
    if (this.config.widgets.length >= 24) {
      this.notify(this.t('limitWidgets'));
      return;
    }
    const copy = clone(widget);
    copy.id = this.newWidget(widget.type).id;
    copy.y = Math.max(0, ...this.config.widgets.map((w) => w.y + w.h));
    this.selected = copy.id;
    this.mutate(() => this.config.widgets.push(copy));
  }
  remove(widget: Widget) {
    this.mutate(() => {
      this.config.widgets = this.config.widgets.filter((w) => w.id !== widget.id);
      this.selected = null;
    });
  }
  keydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && this.editing()) {
      this.selectWidget(null);
      return;
    }
    if (
      !this.editing() ||
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLTextAreaElement ||
      event.target instanceof HTMLSelectElement
    )
      return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      event.shiftKey ? this.redo() : this.undo();
      return;
    }
    if (
      !(event.target instanceof HTMLElement) ||
      !event.target.classList.contains('dbv-widget-header')
    )
      return;
    const id = event.target.closest<HTMLElement>('[data-widget-id]')?.dataset.widgetId;
    const widget = this.config.widgets.find((w) => w.id === id);
    if (!widget) return;
    const key = event.key;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) {
      event.preventDefault();
      this.selected = widget.id;
      this.move(
        widget,
        key === 'ArrowLeft' ? -1 : key === 'ArrowRight' ? 1 : 0,
        key === 'ArrowUp' ? -1 : key === 'ArrowDown' ? 1 : 0,
        event.shiftKey,
      );
    } else if (key === 'Delete') {
      event.preventDefault();
      this.remove(widget);
    } else if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === 'd') {
      event.preventDefault();
      this.duplicate(widget);
    }
  }
  addFilter(field: string) {
    if (this.config.filters.length >= 12) {
      this.notify(this.t('limitFilters'));
      return;
    }
    if (this.config.filters.some((f) => f.field === field)) return;
    const data = this.profile?.fields.find((f) => f.key === field);
    this.mutate(() =>
      this.config.filters.push({
        field,
        label: data?.label || field,
        type: data?.type === 'number' ? 'number' : data?.type === 'date' ? 'date' : 'category',
      }),
    );
  }
  setFilter(filter: Filter) {
    this.filters = this.filters.filter((f) => f.field !== filter.field);
    if (filter.value !== undefined) this.filters.push(filter);
    this.pages = {};
    this.renderFilters();
    void this.loadQuery();
  }
  renderFilters() {
    const focused = document.activeElement;
    const activeId =
      focused instanceof HTMLElement && this.filterBar.contains(focused) ? focused.id : '';
    this.filterBar.replaceChildren();
    const t = this.t;
    const definitions = this.config.filters;
    this.filterBar.hidden = !definitions.length && !this.filters.length && !this.bounds;
    if (this.filterBar.hidden) return;
    const label = el('div', 'dbv-filter-label');
    label.append(icon('filter'), el('span', '', t('filters')));
    this.filterBar.append(label);
    label.title = t('sharedFiltersHelp');
    const description = el('p', 'dbv-filter-help', t('sharedFiltersHelp'));
    if (this.filters.length || this.bounds)
      description.append(el('strong', '', ` ${t('activeFilters')}: ${this.filters.length + (this.bounds ? 1 : 0)}`));
    this.filterBar.append(description);
    for (const def of definitions) {
      const group = el('div', 'dbv-filter');
      const id = 'filter_' + this.instance + '_' + definitions.indexOf(def);
      const caption = el('label', 'dbv-filter-caption', def.label || def.field);
      caption.htmlFor = id;
      group.append(caption);
      const active = this.filters.find((f) => f.field === def.field);
      if (def.type === 'category') {
        const facets = (
          this.query as unknown as { facets?: Record<string, { value: unknown; count: number }[]> }
        )?.facets?.[def.field];
        const values =
          facets?.map((item) => item.value) ??
          this.profile?.fields.find((f) => f.key === def.field)?.examples ??
          [];
        const choices = values.map((value) => [
          JSON.stringify(value),
          value == null ? t('emptyValue') : String(value),
        ]);
        if (active && !choices.some((choice) => choice[0] === JSON.stringify(active.value)))
          choices.push([
            JSON.stringify(active.value),
            active.value == null ? t('emptyValue') : String(active.value),
          ]);
        const input = this.select(
          '',
          [['__all__', t('all')], ...choices],
          active ? JSON.stringify(active.value) : '__all__',
        );
        input.id = id;
        input.addEventListener('change', () =>
          this.setFilter({
            field: def.field,
            op: 'eq',
            value: input.value === '__all__' ? undefined : JSON.parse(input.value),
          }),
        );
        group.append(input);
        if (
          (this.query as unknown as { facets_truncated?: string[] })?.facets_truncated?.includes(
            def.field,
          )
        ) {
          const search = this.input('text', '');
          search.placeholder = t('categoryHint');
          search.setAttribute('aria-label', (def.label || def.field) + ' ' + t('categoryHint'));
          search.addEventListener('change', () =>
            this.setFilter({ field: def.field, op: 'eq', value: search.value || undefined }),
          );
          search.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              search.blur();
            }
          });
          group.append(search);
        }
      } else {
        const row = el('div', 'dbv-range');
        const inputType = def.type === 'date' ? 'date' : 'number';
        const from = this.input(
          inputType,
          active?.op === 'between'
            ? String((active.value as unknown[])[0])
            : active?.op === 'gte'
              ? String(active.value)
              : '',
        );
        const to = this.input(
          inputType,
          active?.op === 'between'
            ? String((active.value as unknown[])[1])
            : active?.op === 'lte'
              ? String(active.value)
              : '',
        );
        from.id = id;
        to.id = id + '_to';
        from.setAttribute('aria-label', (def.label || def.field) + ' ' + t('from'));
        to.setAttribute('aria-label', (def.label || def.field) + ' ' + t('to'));
        from.placeholder = t('from');
        to.placeholder = t('to');
        const apply = () => {
          const parse = (v: string) => (def.type === 'number' ? Number(v) : v);
          if (from.value && to.value && parse(from.value) > parse(to.value)) {
            this.notify(t('invalidRange'));
            return;
          }
          this.setFilter({
            field: def.field,
            op: from.value && to.value ? 'between' : from.value ? 'gte' : 'lte',
            value:
              from.value && to.value
                ? [parse(from.value), parse(to.value)]
                : from.value
                  ? parse(from.value)
                  : to.value
                    ? parse(to.value)
                    : undefined,
          });
        };
        from.addEventListener('change', apply);
        to.addEventListener('change', apply);
        row.append(from, el('span', '', '–'), to);
        group.append(row);
      }
      if (this.editing())
        group.append(
          button(
            t('removeFilter'),
            () => {
              this.mutate(() => {
                this.config.filters = this.config.filters.filter((f) => f !== def);
              });
              this.filters = this.filters.filter((f) => f.field !== def.field);
              this.renderFilters();
            },
            'dbv-btn dbv-icon-only dbv-filter-remove',
            'close',
          ),
        );
      this.filterBar.append(group);
    }
    for (const filter of this.filters.filter(
      (f) =>
        !definitions.some(
          (d) =>
            d.field === f.field &&
            (d.type === 'category' ? f.op === 'eq' : ['between', 'gte', 'lte'].includes(f.op)),
        ),
    )) {
      const chip = button(
        `${filter.field}: ${Array.isArray(filter.value) ? filter.value.join(' – ') : filter.value}`,
        () => {
          this.filters = this.filters.filter((f) => f !== filter);
          this.renderFilters();
          void this.loadQuery();
        },
        'dbv-chip',
        'close',
      );
      this.filterBar.append(chip);
    }
    if (this.bounds)
      this.filterBar.append(
        button(
          t('mapFiltered'),
          () => {
            this.bounds = null;
            this.renderFilters();
            void this.loadQuery();
          },
          'dbv-chip',
          'close',
        ),
      );
    if (this.filters.length || this.bounds)
      this.filterBar.append(
        button(
          t('reset'),
          () => {
            this.filters = [];
            this.bounds = null;
            this.pages = {};
            this.renderFilters();
            void this.loadQuery();
          },
          'dbv-btn dbv-btn-small',
          'refresh',
        ),
      );
    if (activeId)
      this.filterBar
        .querySelector<HTMLElement>('#' + CSS.escape(activeId))
        ?.focus({ preventScroll: true });
  }
  share() {
    const t = this.t;
    const dialog = el('dialog', 'dbv-dialog');
    const head = el('div', 'dbv-dialog-head');
    head.append(
      el('h3', '', t('shareTitle')),
      button(t('close'), () => dialog.close(), 'dbv-btn dbv-icon-only', 'close'),
    );
    dialog.append(head, el('p', 'dbv-muted', t('shareBody')), el('p', 'dbv-callout', t('shareOriginal')));
    if (!this.boot.view_id || !this.boot.view_url || !this.boot.embed_url) {
      dialog.append(el('p', 'dbv-callout', t('saveFirst')));
    } else {
      const link = this.input('url', new URL(this.boot.view_url, location.href).href);
      link.readOnly = true;
      const embed = el('textarea', 'dbv-input dbv-code');
      embed.readOnly = true;
      embed.rows = 5;
      const height = this.input('number', '720');
      height.min = '320';
      height.max = '3000';
      const update = () => {
        const url = new URL(this.boot.embed_url!, location.href);
        const iframe = document.createElement('iframe');
        iframe.src = url.href;
        iframe.title = this.boot.title || t('dashboard');
        iframe.loading = 'lazy';
        iframe.style.width = '100%';
        iframe.style.height = `${Math.max(320, Math.min(3000, Number(height.value) || 720))}px`;
        iframe.style.border = '0';
        iframe.setAttribute('allowfullscreen', '');
        embed.value = iframe.outerHTML;
      };
      height.addEventListener('input', update);
      update();
      const copy = (input: HTMLInputElement | HTMLTextAreaElement) => {
        if (!navigator.clipboard) {
          input.select();
          this.notify(t('copyFailed'));
          return;
        }
        void navigator.clipboard
          .writeText(input.value)
          .then(() => this.notify(t('copied')))
          .catch(() => {
            input.select();
            this.notify(t('copyFailed'));
          });
      };
      dialog.append(
        this.label(t('link'), link),
        button(t('copy'), () => copy(link), 'dbv-btn', 'copy'),
        this.label(t('height'), height),
        this.label(t('embed'), embed),
        button(t('copy'), () => copy(embed), 'dbv-btn', 'copy'),
      );
    }
    dialog.addEventListener('close', () => dialog.remove());
    this.root.append(dialog);
    dialog.showModal();
  }
}
function mount() {
  document.querySelectorAll<HTMLElement>('[data-dashboard]').forEach((root) => {
    if (root.dataset.dashboardMounted) return;
    const script = root.querySelector<HTMLScriptElement>('script[data-dashboard-bootstrap]');
    if (!script) return;
    try {
      const boot = JSON.parse(script.textContent || '{}') as Bootstrap;
      root.dataset.dashboardMounted = 'true';
      new Dashboard(root, boot);
    } catch (error) {
      root.append(
        el(
          'p',
          'dbv-error',
          error instanceof Error ? error.message : 'Unable to initialize dashboard.',
        ),
      );
    }
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
else mount();
