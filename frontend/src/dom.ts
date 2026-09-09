export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls = '',
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
export function button(
  label: string,
  onClick: () => void,
  cls = 'dbv-btn',
  iconName?: string,
): HTMLButtonElement {
  const node = el('button', cls);
  node.type = 'button';
  node.title = label;
  node.setAttribute('aria-label', label);
  if (iconName) node.append(icon(iconName));
  if (!cls.includes('dbv-icon-only')) node.append(document.createTextNode(label));
  node.addEventListener('click', onClick);
  return node;
}
const paths: Record<string, string> = {
  plus: 'M12 5v14M5 12h14',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  data: 'M4 5c0-4 16-4 16 0v14c0 4-16 4-16 0V5M4 5c0 4 16 4 16 0M4 12c0 4 16 4 16 0',
  kpi: 'M4 19V9m8 10V4m8 15v-7',
  bar: 'M4 20V4m0 16h16M8 16v-5m5 5V7m5 9v-8',
  line: 'M3 19V5m0 14h18M6 15l4-6 5 3 5-8',
  area: 'M3 19h18M4 18v-6l5-5 5 4 6-7v14',
  doughnut: 'M11 3a9 9 0 1 0 10 10H11V3zM14 3v7h7a8 8 0 0 0-7-7z',
  scatter: 'M3 19V4m0 15h18M7 14h.01M10 8h.01M13 12h.01M17 5h.01M19 9h.01',
  histogram: 'M3 20V4m0 16h18M6 19v-6h4v6m0 0V7h4v12m0 0V4h4v15',
  table: 'M3 4h18v16H3zM3 9h18M9 4v16M3 14h18',
  map: 'm3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6zM9 3v15m6-12v15',
  text: 'M4 5h16M12 5v15M8 20h8',
  undo: 'M9 4 4 9l5 5M4 9h9a7 7 0 0 1 7 7v3',
  redo: 'm15 4 5 5-5 5m5-5h-9a7 7 0 0 0-7 7v3',
  save: 'M5 3h13l3 3v15H3V3h2zM7 3v6h10V3M7 21v-8h10v8',
  share: 'M15 4h6v6m0-6L10 15M11 4H4v17h17v-7',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  phone: 'M7 2h10v20H7zM10 18h4',
  desktop: 'M3 3h18v13H3zM12 16v5m-5 0h10',
  download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
  refresh: 'M20 7a9 9 0 1 0 1 8M20 3v5h-5',
  close: 'm6 6 12 12M6 18 18 6',
  copy: 'M9 9h12v12H9zM15 9V3H3v12h6',
  trash: 'M3 6h18M8 6V3h8v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  grip: 'M8 5h.01M16 5h.01M8 12h.01M16 12h.01M8 19h.01M16 19h.01',
  check: 'm4 12 5 5L20 6',
  filter: 'M3 4h18l-7 8v8l-4-2v-6L3 4z',
  left: 'm15 5-7 7 7 7',
  right: 'm9 5 7 7-7 7',
  up: 'm5 15 7-7 7 7',
  down: 'm5 9 7 7 7-7',
  settings: 'M4 7h16M4 17h16M8 4v6m8 4v6',
  info: 'M12 11v6m0-10h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
};
export function icon(name: string): SVGSVGElement {
  const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  node.setAttribute('viewBox', '0 0 24 24');
  node.setAttribute('fill', 'none');
  node.setAttribute('stroke', 'currentColor');
  node.setAttribute('stroke-width', '1.7');
  node.setAttribute('stroke-linecap', 'round');
  node.setAttribute('stroke-linejoin', 'round');
  node.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(node.namespaceURI, 'path');
  path.setAttribute('d', paths[name] ?? paths.grid);
  node.append(path);
  return node;
}
export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = el('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
