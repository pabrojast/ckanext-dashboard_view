// Development only: reuse the real Python engine and its synthetic dataset.
// This entry point is excluded from the production bundle.
import { el } from './dom';
const mount = document.querySelector<HTMLElement>('#demo')!;
try {
  const params = new URLSearchParams(location.search);
  const response = await fetch(`/__demo_page?lang=${params.get('lang') || 'es'}`);
  if (!response.ok) throw Error('Start scripts/dev_server.py on port 5188 before npm run dev.');
  const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
  const boot = JSON.parse(doc.querySelector('[data-dashboard-bootstrap]')?.textContent || '{}');
  if (params.get('empty') === '1')
    boot.config = {
      schema_version: 1,
      source: { kind: 'file', types: {} },
      widgets: [],
      filters: [],
      style: { accent: '#0069b4' },
    };
  if (params.get('mode') === 'view') boot.mode = 'view';
  boot.view_url = new URL(boot.view_url, 'http://127.0.0.1:5188').href;
  boot.embed_url = new URL(boot.embed_url, 'http://127.0.0.1:5188').href;
  if (params.get('empty') === '1') boot.view_id = null;
  const form = el('form');
  form.method = 'post';
  form.action = 'http://127.0.0.1:5188/save';
  const title = el('input', 'dev-title');
  title.name = 'title';
  title.value = boot.title;
  title.setAttribute('aria-label', 'Dashboard title');
  const root = el('div');
  root.dataset.dashboard = '';
  const script = el('script');
  script.type = 'application/json';
  script.dataset.dashboardBootstrap = '';
  script.textContent = JSON.stringify(boot);
  root.append(script);
  const note = el(
    'p',
    'dev-note',
    'Local development · real DuckDB engine · synthetic citizen science data',
  );
  mount.replaceChildren(note);
  if (boot.mode === 'editor') {
    form.append(title, root);
    mount.append(form);
  } else mount.append(root);
  await import('./main');
} catch (error) {
  mount.textContent =
    error instanceof Error ? error.message : 'Unable to connect to the local engine.';
}
