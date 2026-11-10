// Small DOM and formatting helpers (no framework). Text is always set with textContent, never innerHTML.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// Element.append() with null/false children skipped (append(null) would insert the text "null").
export function put(el, ...children) {
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

export function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }

export const fmt = {
  int: (n) => (n === null || n === undefined ? '–' : Number(n).toLocaleString('en-US')),
  pct: (x) => (x === null || x === undefined ? '–' : `${(100 * Number(x)).toFixed(Number(x) >= 0.995 || Number(x) < 0.1 ? 1 : 0)}%`),
  num: (x, d = 2) => {
    if (x === null || x === undefined || Number.isNaN(Number(x))) return '–';
    const v = Number(x);
    if (v !== 0 && Math.abs(v) < 0.01) return v.toExponential(1);
    return v.toLocaleString('en-US', { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : d });
  },
  date: (s) => (s ? String(s).replace('T', ' ').replace(/:\d\dZ$/, ' UTC').replace(/Z$/, ' UTC') : '–'),
  short: (s, n = 80) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || ''),
  pred: (p) => String(p || '').replace(/^biolink:/, '').replaceAll('_', ' '),
};

const CATS = [
  ['biolink:Gene', 'gene', 'Gene'],
  ['biolink:Cell', 'cell', 'Cell type'],
  ['visionkb:CellState', 'cell', 'Cell state'],
  ['biolink:Disease', 'disease', 'Disease'],
  ['biolink:PhenotypicFeature', 'phenotype', 'Phenotype'],
  ['biolink:AnatomicalEntity', 'anatomy', 'Anatomy'],
  ['biolink:Dataset', 'other', 'Dataset'],
  ['biolink:OrganismTaxon', 'other', 'Taxon'],
];

export function categoryOf(cats) {
  const list = Array.isArray(cats) ? cats : [cats];
  for (const [id, kind, label] of CATS) if (list.includes(id)) return { id, kind, label };
  const first = list.find(Boolean) || 'biolink:NamedThing';
  return { id: first, kind: 'other', label: first.replace(/^[^:]+:/, '') };
}

export function catChip(cats) {
  const c = categoryOf(cats);
  return h('span', { class: `chip cat-${c.kind}`, title: c.id }, c.label);
}

export function entityLink(node, { showId = true } = {}) {
  if (!node || !node.id) return document.createTextNode('–');
  const a = h('a', { href: `#/entity/${node.id}` }, node.name || node.symbol || node.id);
  if (!showId || !node.name) return a;
  return h('span', {}, a, ' ', h('span', { class: 'curie' }, node.id));
}

const OBO = new Set(['CL', 'UBERON', 'MONDO', 'HP', 'GO', 'EFO', 'CHEBI', 'PR', 'BTO', 'ZFA', 'FMA', 'NCBITaxon', 'DOID', 'ORPHA']);

// External page for a CURIE, or null. Only well-known resolvers.
export function externalUrl(curie) {
  const m = /^([A-Za-z][A-Za-z0-9_.-]*):(.+)$/.exec(String(curie || ''));
  if (!m) return null;
  const [, pfx, local] = m;
  const enc = encodeURIComponent(local);
  switch (pfx) {
    case 'HGNC': return `https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:${enc}`;
    case 'NCBIGene': return `https://www.ncbi.nlm.nih.gov/gene/${enc}`;
    case 'ENSEMBL': return `https://www.ensembl.org/id/${enc}`;
    case 'OMIM': return `https://omim.org/entry/${enc}`;
    case 'UniProtKB': return `https://www.uniprot.org/uniprotkb/${enc}`;
    case 'PMID': return `https://pubmed.ncbi.nlm.nih.gov/${enc}/`;
    case 'CALOHA': return null;
    default:
      if (pfx === 'ORPHA') return `https://www.orpha.net/en/disease/detail/${enc}`;
      return OBO.has(pfx) ? `https://purl.obolibrary.org/obo/${pfx}_${enc}` : null;
  }
}

export function extLink(curie, text) {
  const url = externalUrl(curie);
  if (!url) return h('span', { class: 'curie' }, text || curie);
  return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', class: 'curie' }, text || curie);
}

export function copyButton(value, label = 'Copy') {
  const b = h('button', { type: 'button', class: 'btn btn-ghost btn-sm copy', title: `Copy ${value}`, 'aria-label': `Copy ${value}` }, label);
  b.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(value); b.textContent = 'Copied'; } catch { b.textContent = 'Copy failed'; }
    setTimeout(() => { b.textContent = label; }, 1400);
  });
  return b;
}

export function spinner(text = 'Loading…') {
  return h('p', { class: 'muted', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), ' ', text);
}

export function errorBox(err) {
  const code = err && err.code ? ` (${err.code})` : '';
  return h('div', { class: 'error-box', role: 'alert' }, `${(err && err.message) || 'Something went wrong'}${code}`);
}

export function table(columns, rows, { empty = 'No rows.', caption } = {}) {
  if (!rows.length) return h('p', { class: 'empty' }, empty);
  const thead = h('thead', {}, h('tr', {}, columns.map((c) => h('th', { scope: 'col', class: c.num ? 'num' : null }, c.label))));
  const tbody = h('tbody', {}, rows.map((r) => h('tr', {}, columns.map((c) => {
    const v = c.render ? c.render(r) : r[c.key];
    return h('td', { class: c.num ? 'num' : (c.nowrap ? 'nowrap' : null) }, v instanceof Node ? v : (v === null || v === undefined ? '–' : String(v)));
  }))));
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, caption ? h('caption', { class: 'sr-only' }, caption) : null, thead, tbody));
}

export function bar(fraction, title) {
  const span = h('span');
  span.style.width = `${Math.max(1, Math.min(100, 100 * (Number(fraction) || 0)))}%`;
  return h('div', { class: 'bar', title: title || '' , role: 'img', 'aria-label': title || '' }, span);
}
