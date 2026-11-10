// Routes: #/ (home), #/entity/<curie>, #/evidence/<edge_id>, #/release, #/about.
import { kg, ok } from './api.js';
import {
  h, put, clear, fmt, categoryOf, catChip, entityLink, extLink, copyButton, spinner, errorBox, table, bar, kiChip,
} from './ui.js';

export const EXAMPLES = [
  ['Expression', 'Which retinal cell types express RHO, and what is the evidence?'],
  ['Specificity', 'What genes are most specific to retinal rod cells (CL:0000604)?'],
  ['Disease', 'Is PRPF31 linked to retinitis pigmentosa in VisionKB?'],
  ['Datasets', 'Which HECA datasets cover the RPE?'],
  ['Ranking', 'Which major retinal class shows the highest LRAT expression?'],
  ['Release', 'Which KG release is served, and what are its known issues?'],
];
const QUICK = [['RHO', 'HGNC:10012'], ['retinal rod cell', 'CL:0000604'], ['retinitis pigmentosa', 'MONDO:0019200'],
  ['PRPF31', 'HGNC:15446'], ['retinal pigment epithelium', 'UBERON:0001782'], ['retina', 'UBERON:0000966']];
const SEARCH_CATS = [['', 'All'], ['biolink:Gene', 'Genes'], ['biolink:Cell', 'Cell types'], ['biolink:Disease', 'Diseases'],
  ['biolink:PhenotypicFeature', 'Phenotypes'], ['biolink:AnatomicalEntity', 'Anatomy']];

function warnings(env) {
  const w = (env && env.warnings) || [];
  return w.length ? h('p', { class: 'small muted', role: 'note' }, `Note: ${w.join(' · ')}`) : null;
}
function releaseNote(env) {
  return env && env.kg_release ? h('span', { class: 'small muted' }, `kg_release ${env.kg_release}`) : null;
}

// ---- search box with autocomplete (combobox pattern) -------------------------------------------------------
export function searchBox({ autofocus = false } = {}) {
  let category = '';
  let timer = 0;
  let ctrl = null;
  let items = [];
  let active = -1;
  const listId = 'search-suggest';
  const input = h('input', { type: 'search', id: 'search-q', placeholder: 'Search a gene, cell type, disease or tissue — e.g. RHO, rod, retinitis pigmentosa', autocomplete: 'off', spellcheck: 'false',
    role: 'combobox', 'aria-expanded': 'false', 'aria-controls': listId, 'aria-autocomplete': 'list', 'aria-label': 'Search VisionKB' });
  const list = h('ul', { class: 'suggest', id: listId, role: 'listbox', hidden: true });
  const status = h('span', { class: 'sr-only', role: 'status', 'aria-live': 'polite' });

  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; };
  const go = (item) => { if (item) { close(); location.hash = `#/entity/${item.id}`; } };
  const setActive = (i) => {
    active = i;
    [...list.children].forEach((li, j) => li.setAttribute('aria-selected', String(j === i)));
    if (i >= 0 && list.children[i]) { input.setAttribute('aria-activedescendant', list.children[i].id); list.children[i].scrollIntoView({ block: 'nearest' }); }
  };
  const show = (rows, q) => {
    items = rows;
    clear(list);
    if (!rows.length) {
      list.append(h('li', { class: 'muted', role: 'option', 'aria-disabled': 'true', id: 'sg-none' }, `No match for “${q}”.`));
    }
    rows.forEach((r, i) => {
      const li = h('li', { role: 'option', id: `sg-${i}`, 'aria-selected': 'false' },
        h('span', { class: 'name' }, r.symbol ? h('span', { class: 'sym' }, r.symbol) : null, r.symbol ? ' · ' : '', r.name || r.id),
        h('span', { class: 'right' }, h('span', { class: 'curie' }, r.id), catChip(r.category)));
      li.addEventListener('mousedown', (e) => { e.preventDefault(); go(r); });
      list.append(li);
    });
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    status.textContent = `${rows.length} suggestions`;
  };
  const search = async () => {
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    if (ctrl) ctrl.abort();
    ctrl = new AbortController();
    try {
      const env = await kg('entities/search', { q, limit: 10, category }, { signal: ctrl.signal });
      if (input.value.trim() !== q) return;
      if (env.status !== 'ok') { show([], q); return; }
      show(env.data || [], q);
    } catch (e) { if (e.name !== 'AbortError') show([], q); }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 180); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (list.hidden) search(); else setActive(Math.min(items.length - 1, active + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(Math.max(0, active - 1)); }
    else if (e.key === 'Escape') close();
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (active >= 0) go(items[active]);
      else if (items.length && !list.hidden) go(items[0]);
      else { clearTimeout(timer); search(); }
    }
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
  const cats = h('div', { class: 'search-cats', role: 'group', 'aria-label': 'Filter by category' },
    SEARCH_CATS.map(([id, label]) => {
      const b = h('button', { type: 'button', class: 'btn', 'aria-pressed': String(id === category) }, label);
      b.addEventListener('click', () => {
        category = id;
        for (const x of cats.children) x.setAttribute('aria-pressed', String(x === b));
        input.focus();
        if (input.value.trim().length >= 2) search();
      });
      return b;
    }));
  if (autofocus) setTimeout(() => input.focus(), 0);
  return h('div', { class: 'search' }, h('div', { class: 'search-row' }, h('div', { class: 'suggest-wrap' }, input, list)), cats, status);
}

// ---- home ---------------------------------------------------------------------------------------------------
export function renderHome(main, ctx) {
  const rel = ctx.release?.data;
  const nodes = rel?.counts?.nodes_by_category || {};
  const stats = rel ? [
    [fmt.int(nodes['biolink:Gene']), 'genes'],
    [fmt.int((nodes['biolink:Cell'] || 0) + (nodes['visionkb:CellState'] || 0)), 'cell types and states'],
    [fmt.int((nodes['biolink:Disease'] || 0) + (nodes['biolink:PhenotypicFeature'] || 0)), 'diseases and phenotypes'],
    [fmt.int(rel.counts?.edges_total), 'edges'],
    [fmt.int(rel.n_datasets ?? (rel.atlases || []).length), 'HECA atlases'],
  ] : [];
  put(main, 
    h('section', { class: 'hero' },
      h('h1', {}, 'The eye, as a ', h('span', { class: 'accent' }, 'knowledge graph')),
      h('p', { class: 'lead' }, 'Genes, retinal and ocular cell types and states, diseases and phenotypes, linked by typed Biolink relationships with their evidence: HECA single-cell atlas summaries and curated sources with PMIDs.'),
      searchBox({ autofocus: true }),
      h('div', { class: 'quick' }, h('span', { class: 'muted' }, 'Try:'), QUICK.map(([label, id]) => h('a', { class: 'chip', href: `#/entity/${id}` }, label)))),
    stats.length ? h('div', { class: 'stats' }, stats.map(([v, k]) => h('div', { class: 'stat' }, h('div', { class: 'v' }, v), h('div', { class: 'k' }, k)))) : null,
    h('section', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Ask a question'), h('span', { class: 'small muted' }, 'Answers come from the graph through tools, with your own Claude API key.')),
      h('div', { class: 'examples' }, EXAMPLES.map(([tag, q]) => {
        const b = h('button', { type: 'button', class: 'example' }, h('span', { class: 'tag' }, tag), q);
        b.addEventListener('click', () => ctx.chat.ask(q, { send: true }));
        return b;
      }))),
    h('section', { class: 'panel' },
      h('h2', {}, 'What is in VisionKB'),
      h('div', { class: 'grid-2' },
        h('div', {}, h('h3', {}, 'Atlas observations'), h('p', { class: 'small' }, 'expressed_in edges from the Human Eye Cell Atlas (HECA) summaries: per-group % of cells expressing, mean log1p CP10k and pseudobulk CP10k, by major class and cell type, with donor support. knowledge_level = observation.')),
        h('div', {}, h('h3', {}, 'Curated claims'), h('p', { class: 'small' }, 'Gene–disease and disease–phenotype edges with sources and PMIDs (knowledge_level = knowledge_assertion), on CL, UBERON, MONDO, HP and HGNC identifiers.')),
        h('div', {}, h('h3', {}, 'Every claim has evidence'), h('p', { class: 'small' }, 'Each edge has an edge_id; its evidence lists the StudyResults (dataset, group, cells, values) and publications. Open it from any table or chat answer.')))),
  );
}

// ---- entity ---------------------------------------------------------------------------------------------------
function tabs(defs) {
  const bar_ = h('div', { class: 'tabs', role: 'tablist' });
  const panels = h('div');
  const buttons = defs.map((d, i) => {
    const b = h('button', { type: 'button', role: 'tab', id: `tab-${i}`, 'aria-selected': 'false', 'aria-controls': `tabp-${i}` }, d.label);
    const p = h('div', { role: 'tabpanel', id: `tabp-${i}`, 'aria-labelledby': `tab-${i}`, hidden: true });
    let loaded = false;
    b.addEventListener('click', () => {
      buttons.forEach((x, j) => { x.setAttribute('aria-selected', String(j === i)); panels.children[j].hidden = j !== i; });
      if (!loaded) { loaded = true; d.render(p); }
    });
    b.addEventListener('keydown', (e) => {
      const n = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (n) { const t = buttons[(i + n + buttons.length) % buttons.length]; t.focus(); t.click(); }
    });
    bar_.append(b);
    panels.append(p);
    return b;
  });
  if (buttons.length) buttons[0].click();
  return h('div', {}, bar_, panels);
}

function relationshipsPanel(curie, degree, ctx) {
  const preds = Object.keys(degree || {});
  const outN = preds.reduce((s, p) => s + (degree[p].out || 0), 0);
  const inN = preds.reduce((s, p) => s + (degree[p].in || 0), 0);
  const state = { dir: outN >= inN ? 'subject' : 'object', predicate: '', offset: 0, limit: 25, history: [] };
  const dirSel = h('select', { 'aria-label': 'Direction' },
    h('option', { value: 'subject', selected: state.dir === 'subject' }, `outgoing (this is the subject) · ${fmt.int(outN)}`),
    h('option', { value: 'object', selected: state.dir === 'object' }, `incoming (this is the object) · ${fmt.int(inN)}`));
  const predSel = h('select', { 'aria-label': 'Predicate' }, h('option', { value: '' }, 'all predicates'),
    preds.map((p) => h('option', { value: p }, `${fmt.pred(p)} (${fmt.int(degree[p].out)} out / ${fmt.int(degree[p].in)} in)`)));
  const out = h('div');
  const load = async () => {
    put(clear(out), spinner());
    const params = { [state.dir]: curie, predicate: state.predicate, limit: state.limit, offset: state.offset };
    try {
      const env = await kg('relationships', params);
      clear(out);
      if (env.status !== 'ok') { put(out, errorBox(env.error)); return; }
      const rows = env.data || [];
      put(out, table([
        { label: 'Subject', render: (r) => entityLink(r.subject, { showId: false }) },
        { label: 'Predicate', render: (r) => h('span', { class: 'mono small' }, fmt.pred(r.predicate)) },
        { label: 'Object', render: (r) => entityLink(r.object, { showId: false }) },
        { label: 'Level', render: (r) => h('span', { class: 'small' }, (r.knowledge_level || '').replaceAll('_', ' ')) },
        { label: 'Source', render: (r) => h('span', { class: 'mono small' }, (r.primary_knowledge_source || '').replace('infores:', '')) },
        { label: 'Max % expr.', num: true, render: (r) => (r.summary?.max_pct_expressing !== undefined ? fmt.pct(r.summary.max_pct_expressing) : '–') },
        { label: 'Evidence', num: true, render: (r) => evidenceButton(r.edge_id, `${fmt.int(r.evidence_count)}${(r.publications || []).length ? ` · ${r.publications.length} PMID` : ''}`, ctx) },
      ], rows, { empty: 'No relationships for this filter.' }));
      const total = env.page?.total;
      const next = rows.length && (total === null || total === undefined || state.offset + rows.length < total) ? state.offset + rows.length : null;
      const prev = h('button', { type: 'button', class: 'btn btn-sm', disabled: !state.history.length }, '← Previous');
      const nextB = h('button', { type: 'button', class: 'btn btn-sm', disabled: next === null }, 'Next →');
      prev.addEventListener('click', () => { state.offset = state.history.pop() || 0; load(); });
      nextB.addEventListener('click', () => { state.history.push(state.offset); state.offset = next; load(); });
      put(out, h('div', { class: 'pager' }, prev, nextB,
        h('span', { class: 'small muted' }, rows.length ? `rows ${fmt.int(state.offset + 1)}–${fmt.int(state.offset + rows.length)} of ${fmt.int(total)}` : ''), releaseNote(env)), warnings(env));
    } catch (e) { put(clear(out), errorBox(e)); }
  };
  const reset = () => { state.offset = 0; state.history = []; load(); };
  dirSel.addEventListener('change', () => { state.dir = dirSel.value; reset(); });
  predSel.addEventListener('change', () => { state.predicate = predSel.value; reset(); });
  return (panel) => { put(panel, h('div', { class: 'controls' }, h('label', {}, 'Direction ', dirSel), h('label', {}, 'Predicate ', predSel)), out); load(); };
}

function evidenceButton(edgeId, label, ctx) {
  if (!edgeId) return document.createTextNode(label || '–');
  const b = h('button', { type: 'button', class: 'btn btn-sm', title: edgeId, 'aria-label': `Evidence for ${edgeId}` }, label || 'Evidence');
  b.addEventListener('click', () => ctx.openEvidence(edgeId));
  return b;
}

function atlasPanel(node) {
  const out = h('div');
  const level = h('select', { 'aria-label': 'Annotation level' }, h('option', { value: 'majorclass' }, 'major class'), h('option', { value: 'celltype' }, 'cell type'));
  const top = 8;
  const load = async () => {
    put(clear(out), spinner('Loading atlas summaries…'));
    try {
      const env = await kg('atlas/expression', { genes: node.id, level: level.value, limit: 200 });
      clear(out);
      if (env.status !== 'ok') { put(out, errorBox(env.error)); return; }
      const byDs = new Map();
      for (const r of env.data || []) { if (!byDs.has(r.dataset_id)) byDs.set(r.dataset_id, []); byDs.get(r.dataset_id).push(r); }
      if (!byDs.size) { put(out, h('p', { class: 'empty' }, 'No atlas summary rows for this gene at this level.')); return; }
      const ds = [...byDs.entries()].map(([id, rows]) => {
        rows.sort((a, b) => (b.pseudobulk_cp10k || 0) - (a.pseudobulk_cp10k || 0));
        return { id, rows, max: rows[0]?.pseudobulk_cp10k || 0 };
      }).sort((a, b) => b.max - a.max);
      put(out, h('p', { class: 'small muted' }, `Top ${top} groups per dataset by pseudobulk CP10k (${fmt.int(env.data.length)} rows of ${fmt.int(env.page?.total)}; all genes × groups are summarised, no threshold). Bars are relative to the dataset’s top group.`));
      for (const d of ds) {
        put(out, h('div', { class: 'atlas-ds' },
          h('h3', {}, h('span', { class: 'mono' }, d.id.replace('visionkb:', '')), h('span', { class: 'small muted' }, `${d.rows[0]?.dataset_version || ''} · ${d.rows.length} groups`)),
          table([
            { label: 'Group', render: (r) => h('span', {}, r.cell_type_id ? h('a', { href: `#/entity/${r.cell_type_id}` }, r.group_label) : r.group_label, ' ', kiChip(r.dataset_id, r.group_label)) },
            { label: 'Pseudobulk CP10k', render: (r) => h('div', { class: 'controls' }, bar(d.max ? r.pseudobulk_cp10k / d.max : 0, `${fmt.num(r.pseudobulk_cp10k)} CP10k`), h('span', { class: 'mono small' }, fmt.num(r.pseudobulk_cp10k))) },
            { label: '% expressing', num: true, render: (r) => fmt.pct(r.pct_expressing) },
            { label: 'Mean log1p', num: true, render: (r) => fmt.num(r.mean_log1p_cp10k) },
            { label: 'Cells', num: true, render: (r) => fmt.int(r.n_cells) },
            { label: 'Donors expr.', num: true, render: (r) => (r.n_donors_expressing === null || r.n_donors_expressing === undefined ? '–' : `${fmt.int(r.n_donors_expressing)}/${fmt.int(r.n_donors)}`) },
          ], d.rows.slice(0, top))));
      }
      put(out, warnings(env), releaseNote(env));
    } catch (e) { put(clear(out), errorBox(e)); }
  };
  level.addEventListener('change', load);
  return (panel) => { put(panel, h('div', { class: 'controls' }, h('label', {}, 'Level ', level)), out); load(); };
}

function geneSetPanel(node, kind, ctx) {
  const out = h('div');
  const state = { offset: 0, history: [], limit: 25 };
  const load = async () => {
    put(clear(out), spinner());
    try {
      const env = await kg('gene-sets', { entity: node.id, kind, limit: state.limit, offset: state.offset });
      clear(out);
      if (env.status !== 'ok') { put(out, errorBox(env.error)); return; }
      const rows = env.data || [];
      put(out, h('p', { class: 'small muted' }, kind === 'expressed'
        ? 'Genes with expressed_in edges to this cell type, ranked by specificity (pseudobulk in the target group over the highest other group of the same dataset).'
        : 'Genes linked to this condition by curated edges.'));
      put(out, table([
        { label: '#', num: true, render: (r) => fmt.int(state.offset + rows.indexOf(r) + 1) },
        { label: 'Gene', render: (r) => h('span', {}, h('a', { href: `#/entity/${r.gene_id}` }, r.symbol || r.gene_id), ' ', h('span', { class: 'small muted' }, fmt.short(r.name, 42))) },
        { label: kind === 'expressed' ? 'Specificity' : 'Score', num: true, render: (r) => fmt.num(r.score) },
        { label: '% expressing', num: true, render: (r) => (r.pct_expressing === undefined ? '–' : fmt.pct(r.pct_expressing)) },
        { label: 'Best group (dataset)', render: (r) => { const b = r.best_study_result; return b ? h('span', { class: 'small' }, `${b.group_label} · ${String(b.dataset_id).replace('visionkb:', '')} · ${fmt.num(b.pseudobulk_cp10k)} vs ${fmt.num(b.other_max_pseudobulk_cp10k)} (${b.other_max_group})`, ' ', kiChip(b.dataset_id, b.group_label)) : '–'; } },
        { label: 'Evidence', render: (r) => h('span', { class: 'controls' }, (r.evidence || []).slice(0, 3).map((e) => evidenceButton(e.edge_id, fmt.pred(e.predicate) || 'edge', ctx))) },
      ], rows, { empty: 'No genes recorded.' }));
      const total = env.page?.total;
      const next = rows.length && (total === null || total === undefined || state.offset + rows.length < total) ? state.offset + rows.length : null;
      const prev = h('button', { type: 'button', class: 'btn btn-sm', disabled: !state.history.length }, '← Previous');
      const nextB = h('button', { type: 'button', class: 'btn btn-sm', disabled: next === null }, 'Next →');
      prev.addEventListener('click', () => { state.offset = state.history.pop() || 0; load(); });
      nextB.addEventListener('click', () => { state.history.push(state.offset); state.offset = next; load(); });
      put(out, h('div', { class: 'pager' }, prev, nextB, h('span', { class: 'small muted' }, `${fmt.int(total)} genes`), releaseNote(env)), warnings(env));
    } catch (e) { put(clear(out), errorBox(e)); }
  };
  return (panel) => { put(panel, out); load(); };
}

function datasetsPanel(params) {
  return async (panel) => {
    put(panel, spinner());
    try {
      const env = await kg('datasets', { ...params, limit: 50 });
      clear(panel);
      if (env.status !== 'ok') { put(panel, errorBox(env.error)); return; }
      put(panel, datasetsTable(env.data || []), warnings(env), releaseNote(env));
    } catch (e) { put(clear(panel), errorBox(e)); }
  };
}

function datasetsTable(rows) {
  return table([
    { label: 'Dataset', render: (r) => h('span', {}, h('strong', {}, r.title || r.id), h('br'), h('span', { class: 'curie' }, r.id)) },
    { label: 'Tissue', render: (r) => h('span', { class: 'controls' }, (r.tissue || []).map((t) => h('a', { class: 'curie', href: `#/entity/${t}` }, t))) },
    { label: 'Assay', render: (r) => (r.assay ? extLink(r.assay) : '–') },
    { label: 'Cells', num: true, render: (r) => fmt.int(r.n_cells) },
    { label: 'Donors', num: true, render: (r) => fmt.int(r.n_donors) },
    { label: 'Levels', render: (r) => h('span', { class: 'small' }, (r.levels || []).join(', ')) },
    { label: 'Version', render: (r) => h('span', { class: 'mono small' }, r.version || '–') },
    { label: 'Access', render: (r) => h('span', { class: 'chip' }, r.access_level || '–') },
  ], rows, { empty: 'No datasets.' });
}

export async function renderEntity(main, curie, ctx) {
  put(main, spinner());
  let env;
  try { env = await kg(`entities/${curie}`); } catch (e) { put(clear(main), errorBox(e)); return; }
  clear(main);
  if (env.status !== 'ok') {
    put(main, h('div', { class: 'panel' }, h('h1', {}, curie), errorBox(env.error), h('p', {}, h('a', { href: '#/' }, '← Back to search'))));
    return;
  }
  const node = env.data.node || {};
  const degree = env.data.degree_by_predicate || {};
  const cat = categoryOf(node.category);
  document.title = `${node.symbol || node.name || curie} — VisionKB`;
  const syn = [...new Set([...(node.synonym || []), ...(node.synonyms || [])])];
  const ask = h('button', { type: 'button', class: 'btn btn-primary' }, 'Ask about this');
  ask.addEventListener('click', () => ctx.chat.ask(`What does VisionKB record about ${node.symbol || node.name} (${node.id})? Cite the evidence.`, { send: false }));
  const ext = extLink(node.id, 'external page');
  const card = h('section', { class: 'panel' },
    h('div', { class: 'entity-head' },
      h('div', {},
        h('div', { class: 'entity-meta' }, catChip(node.category), h('span', { class: 'curie' }, node.id), copyButton(node.id), ext.tagName === 'A' ? ext : null),
        h('h1', {}, node.symbol ? `${node.symbol} · ${node.name}` : node.name || node.id),
        node.description ? h('p', { class: 'entity-desc' }, node.description) : null),
      ask),
    h('dl', { class: 'kv' },
      syn.length ? [h('dt', {}, 'Synonyms'), h('dd', {}, h('div', { class: 'syn' }, syn.slice(0, 30).map((s) => h('span', { class: 'chip cat-other' }, s))))] : null,
      (node.xref || []).length ? [h('dt', {}, 'Cross-references'), h('dd', {}, h('div', { class: 'syn' }, node.xref.map((x) => extLink(x))))] : null,
      node.locus_type ? [h('dt', {}, 'Locus type'), h('dd', {}, node.locus_type)] : null,
      node.in_taxon ? [h('dt', {}, 'Taxon'), h('dd', {}, h('span', { class: 'curie' }, node.in_taxon))] : null,
      (node.provided_by || []).length ? [h('dt', {}, 'Provided by'), h('dd', { class: 'mono small' }, node.provided_by.join(', '))] : null,
      h('dt', {}, 'Edges'), h('dd', {}, Object.keys(degree).length ? h('span', { class: 'syn' }, Object.entries(degree).map(([p, d]) => h('span', { class: 'chip' }, `${fmt.pred(p)}: ${fmt.int(d.out)} out · ${fmt.int(d.in)} in`))) : 'none'),
      h('dt', {}, 'Release'), h('dd', { class: 'mono small' }, env.kg_release || '–')));
  const defs = [];
  if (cat.kind === 'gene') defs.push({ label: 'Atlas expression', render: atlasPanel(node) });
  if (cat.kind === 'cell') defs.push({ label: 'Specific genes', render: geneSetPanel(node, 'expressed', ctx) });
  if (cat.kind === 'disease' || cat.kind === 'phenotype') defs.push({ label: 'Genes', render: geneSetPanel(node, 'disease_genes', ctx) });
  defs.push({ label: 'Relationships', render: relationshipsPanel(node.id, degree, ctx) });
  if (cat.kind === 'anatomy') defs.push({ label: 'Datasets', render: datasetsPanel({ tissue: node.id }) });
  if (cat.kind === 'cell') defs.push({ label: 'Datasets', render: datasetsPanel({ entities: node.id }) });
  put(main, h('nav', { class: 'small', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/' }, 'Home'), ' / ', cat.label), card, h('section', { class: 'panel' }, tabs(defs)));
}

// ---- evidence ---------------------------------------------------------------------------------------------------
export async function evidenceView(edgeId, container, { titleId } = {}) {
  put(container, spinner('Loading evidence…'));
  const state = { offset: 0, limit: 50 };
  const load = async () => {
    let env;
    try { env = await kg(`evidence/${edgeId}`, { limit: state.limit, offset: state.offset }); } catch (e) { put(clear(container), errorBox(e)); return; }
    clear(container);
    if (env.status !== 'ok') { put(container, h('h2', { id: titleId }, edgeId), errorBox(env.error)); return; }
    const { edge = {}, study_results: srs = [], publications: pubs = [] } = env.data || {};
    put(container, 
      h('h2', { id: titleId, class: 'edge-line' }, entityLink(edge.subject, { showId: false }), h('span', { class: 'pred' }, fmt.pred(edge.predicate)), entityLink(edge.object, { showId: false })),
      h('dl', { class: 'kv' },
        h('dt', {}, 'Edge'), h('dd', {}, h('span', { class: 'curie' }, edge.edge_id || edgeId), copyButton(edge.edge_id || edgeId)),
        h('dt', {}, 'Knowledge level'), h('dd', {}, `${(edge.knowledge_level || '–').replaceAll('_', ' ')} · ${(edge.agent_type || '').replaceAll('_', ' ')}`),
        h('dt', {}, 'Source'), h('dd', { class: 'mono small' }, edge.primary_knowledge_source || '–'),
        edge.qualifiers && Object.keys(edge.qualifiers).length ? [h('dt', {}, 'Qualifiers'), h('dd', { class: 'syn' }, Object.entries(edge.qualifiers).map(([k, v]) => h('span', { class: 'chip cat-other' }, `${k.replace('_qualifier', '')}: ${[].concat(v).join(', ')}`)))] : null,
        edge.summary ? [h('dt', {}, 'Summary'), h('dd', {}, `max ${fmt.pct(edge.summary.max_pct_expressing)} expressing · max mean log1p ${fmt.num(edge.summary.max_mean_log1p_cp10k)} · ${fmt.int(edge.summary.n_datasets)} datasets`)] : null,
        h('dt', {}, 'Status'), h('dd', {}, `${edge.status || '–'}${edge.visibility ? ` · visibility ${edge.visibility}` : ''}`),
        h('dt', {}, 'Release'), h('dd', { class: 'mono small' }, env.kg_release || '–')),
      h('h3', {}, `Study results (${fmt.int(env.page?.total ?? srs.length)})`),
      table([
        { label: 'Dataset', render: (r) => h('span', { class: 'mono small' }, String(r.dataset_id || (r.supporting_data_set || [])[0] || '–').replace('visionkb:', '')) },
        { label: 'Level', render: (r) => r.level || '–' },
        { label: 'Group', render: (r) => h('span', {}, r.group_label || '–', ' ', kiChip(r.dataset_id, r.group_label)) },
        { label: 'Cells', num: true, render: (r) => fmt.int(r.n_cells) },
        { label: '% expressing', num: true, render: (r) => fmt.pct(r.pct_expressing) },
        { label: 'Mean log1p', num: true, render: (r) => fmt.num(r.mean_log1p_cp10k) },
        { label: 'Pseudobulk CP10k', num: true, render: (r) => fmt.num(r.pseudobulk_cp10k) },
        { label: 'Donors expr.', num: true, render: (r) => fmt.int(r.n_donors_expressing) },
        { label: 'Atlas', render: (r) => h('span', { class: 'mono small' }, r.atlas_version || '–') },
      ], srs, { empty: 'No study results (curated edge).' }),
      srs[0]?.method ? h('p', { class: 'small muted' }, `Method: ${srs[0].method}`) : null,
      h('h3', {}, `Publications (${pubs.length})`),
      pubs.length ? h('ul', {}, pubs.map((p) => {
        const id = typeof p === 'string' ? p : p.id || p.pmid || '';
        return h('li', {}, extLink(id), typeof p === 'object' && p.title ? ` — ${p.title}` : '');
      })) : h('p', { class: 'empty' }, 'None recorded.'),
      warnings(env));
    const total = env.page?.total;
    if (total && total > srs.length) {
      const prev = h('button', { type: 'button', class: 'btn btn-sm', disabled: state.offset === 0 }, '← Previous');
      const next = h('button', { type: 'button', class: 'btn btn-sm', disabled: state.offset + srs.length >= total }, 'Next →');
      prev.addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
      next.addEventListener('click', () => { state.offset += srs.length; load(); });
      put(container, h('div', { class: 'pager' }, prev, next, h('span', { class: 'small muted' }, `study results ${state.offset + 1}–${state.offset + srs.length} of ${total}`)));
    }
  };
  await load();
}

export async function renderEvidencePage(main, edgeId) {
  const box = h('section', { class: 'panel' });
  put(main, h('nav', { class: 'small', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/' }, 'Home'), ' / Evidence'), box);
  await evidenceView(edgeId, box);
}

// ---- release ----------------------------------------------------------------------------------------------------
export async function renderRelease(main, ctx) {
  put(main, spinner());
  let env;
  try { env = await ok('release'); } catch (e) { put(clear(main), errorBox(e)); return; }
  clear(main);
  const r = env.data;
  const nodes = Object.entries(r.counts?.nodes_by_category || {}).sort((a, b) => b[1] - a[1]);
  const edges = Object.entries(r.counts?.edges_by_predicate || {}).sort((a, b) => b[1] - a[1]);
  put(main, 
    h('section', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h1', {}, r.kg_release), h('span', { class: `chip ${r.validation?.status === 'pass' ? 'ok' : ''}` }, `validation ${r.validation?.status || '–'}`)),
      h('dl', { class: 'kv' },
        h('dt', {}, 'Created'), h('dd', {}, fmt.date(r.created_utc)),
        h('dt', {}, 'Biolink'), h('dd', {}, r.biolink_version || '–'),
        h('dt', {}, 'Schema'), h('dd', {}, r.schema_version || '–'),
        h('dt', {}, 'Edges'), h('dd', {}, fmt.int(r.counts?.edges_total)),
        h('dt', {}, 'Datasets'), h('dd', {}, fmt.int(r.n_datasets)),
        h('dt', {}, 'Code'), h('dd', { class: 'small mono' }, Object.entries(r.code || {}).map(([k, v]) => `${k} ${v.version || ''} (${String(v.git_sha || '').slice(0, 7)})`).join(' · ')))),
    h('section', { class: 'panel' }, h('h2', {}, 'Known issues'),
      (r.known_issues || []).length ? (r.known_issues || []).map((ki) => h('div', { class: 'ki-banner' },
        h('div', {},
          h('p', {}, h('strong', {}, `${ki.id}: ${ki.title}`), ` — ${ki.status || ''}`),
          ki.id === 'KI-1' ? h('p', { class: 'small' }, 'Small HRCA snRNA amacrine subtypes carry a rod program (likely doublets or ambient RNA), so rod genes such as RHO and PDE6A have expressed_in edges to them. The edges are reported, not removed. Groups are marked with a KI-1 chip in atlas and evidence tables.') : null,
          h('p', { class: 'small' }, `${fmt.int(ki.n_groups)} groups · ${fmt.int(ki.n_pairs)} pairs · ${fmt.int(ki.n_study_results)} study results${ki.rod_program_study_results ? ` · ${fmt.int(ki.rod_program_study_results)} with a rod program` : ''}`),
          (ki.rod_program_groups || []).length ? h('p', { class: 'small mono' }, `Rod-program groups: ${ki.rod_program_groups.map((g) => g.replace('visionkb:', '')).join(', ')}`) : null))) : h('p', { class: 'empty' }, 'None recorded.')),
    h('section', { class: 'panel' }, h('h2', {}, 'Expression edge rule'), h('p', {}, r.expression_edge_rule_text || '–'),
      r.expression_edge_rule?.decision ? h('p', { class: 'small muted' }, `Decision ${r.expression_edge_rule.decision}; levels ${(r.expression_edge_rule.levels || []).join(', ')}.`) : null),
    h('div', { class: 'grid-2' },
      h('section', { class: 'panel' }, h('h2', {}, 'Nodes by category'), table([{ label: 'Category', render: ([k]) => h('span', { class: 'mono small' }, k) }, { label: 'Nodes', num: true, render: ([, v]) => fmt.int(v) }], nodes)),
      h('section', { class: 'panel' }, h('h2', {}, 'Edges by predicate'), table([{ label: 'Predicate', render: ([k]) => h('span', { class: 'mono small' }, k) }, { label: 'Edges', num: true, render: ([, v]) => fmt.int(v) }], edges))),
    h('section', { class: 'panel' }, h('h2', {}, 'Sources'), table([
      { label: 'Source', render: (s) => s.name },
      { label: 'infores', render: (s) => h('span', { class: 'mono small' }, s.infores || '–') },
      { label: 'Version', render: (s) => h('span', { class: 'mono small' }, s.version || '–') },
      { label: 'License', render: (s) => s.license || '–' },
    ], r.sources || [])),
  );
  const dsPanel = h('section', { class: 'panel', id: 'datasets' }, h('h2', {}, 'Datasets'));
  put(main, dsPanel);
  await datasetsPanel({})(dsPanel);
  ctx.setRelease?.(env);
}

// ---- about ----------------------------------------------------------------------------------------------------
export function renderAbout(main, ctx) {
  const s = ctx.session || {};
  const lim = s.limits || {};
  put(main, 
    h('section', { class: 'panel' }, h('h1', {}, 'About VisionKB'),
      h('p', {}, 'VisionKB is a knowledge graph of the eye built by the Rui Chen Lab: genes (HGNC), retinal and ocular cell types and states (CL), anatomy (UBERON), diseases (MONDO) and phenotypes (HP), linked by Biolink 4.4.6 relationships. Expression edges come from Human Eye Cell Atlas (HECA) summaries; disease edges from curated sources with PMIDs. Every edge carries an edge_id, a knowledge level and its evidence.'),
      h('p', {}, 'This page reads the graph through a read-only proxy to the VisionKB API; the browser never sees the API token.')),
    h('section', { class: 'panel' }, h('h2', {}, 'How the chat works'),
      h('ol', {},
        h('li', {}, 'Your question and this tab’s chat history go to this server, with your Claude API key in one request header.'),
        h('li', {}, 'The server calls the Anthropic Messages API with your key. Claude may call the eight read-only VisionKB tools (search, entity, relationships, evidence, gene sets, atlas expression, datasets, release); the server runs them against the graph and returns the results to Claude.'),
        h('li', {}, 'The answer streams back with a trace of every tool call (tool, arguments, rows, release). Identifiers in the answer link to entity pages and evidence.'))),
    h('section', { class: 'panel' }, h('h2', {}, 'What is sent to Anthropic'),
      h('ul', {},
        h('li', {}, 'Your questions and the chat history of this tab.'),
        h('li', {}, 'Tool results: VisionKB facts and HECA atlas summary values. HECA data are lab-access (access_level = lab): use the chat only if you may share them with Anthropic under your account’s terms.'),
        h('li', {}, 'Fixed instructions: a short preamble and the AiScientist skill answer-eye-questions-with-visionkb-kg.')),
      h('p', {}, 'Not sent: the VisionKB API token, the access code, other users’ chats. Calls are billed to your Anthropic account.')),
    h('section', { class: 'panel' }, h('h2', {}, 'Your API key'),
      h('ul', {},
        h('li', {}, 'Kept only in this tab’s sessionStorage (cleared when the tab closes; “Forget key” clears it at once). Never in cookies, localStorage, URLs or the chat history.'),
        h('li', {}, 'Sent only to this server, in the X-Anthropic-Key header of the models and chat requests, and used for that one call to Anthropic. The server does not store, cache or log it, and does not pass it to the tool process.'),
        h('li', {}, 'Use a key with a spend limit, and rotate it if you think it was exposed.'))),
    h('section', { class: 'panel' }, h('h2', {}, 'Limits'),
      h('ul', {},
        h('li', {}, `${lim.chat_per_window ?? 20} questions per ${Math.round((lim.chat_window_s ?? 600) / 60)} minutes and one question at a time per session.`),
        h('li', {}, `A question may have up to ${fmt.int(lim.max_message_chars ?? 8000)} characters; up to ${lim.max_tool_calls ?? 16} tool calls per answer.`),
        h('li', {}, 'Older turns are dropped from long conversations before they are sent.'))),
    h('section', { class: 'panel' }, h('h2', {}, 'Versions'),
      h('dl', { class: 'kv' },
        h('dt', {}, 'visionkb-web'), h('dd', { class: 'mono' }, s.version || '–'),
        h('dt', {}, 'Skill'), h('dd', { class: 'mono' }, `${s.skill?.name || '–'} ${s.skill?.version || ''}`),
        h('dt', {}, 'KG release'), h('dd', { class: 'mono' }, ctx.release?.kg_release || '–'),
        h('dt', {}, 'Source'), h('dd', {}, h('a', { href: 'https://github.com/lijinbio/visionkb-web', target: '_blank', rel: 'noopener noreferrer' }, 'github.com/lijinbio/visionkb-web')))),
  );
}
