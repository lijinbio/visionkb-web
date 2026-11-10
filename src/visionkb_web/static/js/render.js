// Model output -> Markdown (marked; raw HTML escaped) -> sanitised HTML (DOMPurify) -> identifiers turned into in-page links.
// Links may only point to #/ routes or http(s); no images, styles, frames, forms or event handlers survive.
import { marked } from './vendor/marked.esm.js';
import DOMPurify from './vendor/purify.es.js';

const ALLOWED_TAGS = ['a', 'b', 'strong', 'i', 'em', 'code', 'pre', 'p', 'br', 'hr', 'ul', 'ol', 'li', 'blockquote',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'del', 's', 'sup', 'sub', 'span'];
const PURIFY = {
  ALLOWED_TAGS,
  ALLOWED_ATTR: ['href', 'title', 'colspan', 'rowspan', 'align'],
  ALLOWED_URI_REGEXP: /^(?:https?:\/\/|#\/)/i,
  ALLOW_DATA_ATTR: false,
  KEEP_CONTENT: true,
};

// Raw HTML in model output is shown as text, never parsed as markup (the preamble asks for Markdown only).
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escapeHtml = (t) => String(t).replace(/[&<>"']/g, (c) => ESC[c]);
marked.use({ renderer: { html: (token) => escapeHtml(token.text ?? token.raw ?? '') } });

let hooked = false;
function hook() {
  if (hooked) return;
  hooked = true;
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
      const href = node.getAttribute('href') || '';
      if (!/^(?:https?:\/\/|#\/)/i.test(href)) node.removeAttribute('href');
      else if (/^https?:/i.test(href)) {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer nofollow');
      }
    }
  });
}

// Order matters: edges and datasets before generic CURIEs.
const ID_RE = /\b(visionkb:e-[0-9a-f]{8,64})\b|\b(visionkb:ds-[a-z0-9][a-z0-9-]*)\b|\bPMID:\s?(\d{4,9})\b|\b((?:HGNC|CL|UBERON|MONDO|HP|NCBITaxon|EFO|NCBIGene|GO|CHEBI|PR|ORPHA|OMIM):[A-Za-z0-9_]+|visionkb:(?!e-|ds-)[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9])\b/g;

function linkifyText(doc, text) {
  const frag = doc.createDocumentFragment();
  let last = 0;
  let found = false;
  ID_RE.lastIndex = 0;
  for (let m = ID_RE.exec(text); m; m = ID_RE.exec(text)) {
    found = true;
    if (m.index > last) frag.append(doc.createTextNode(text.slice(last, m.index)));
    const a = doc.createElement('a');
    a.className = 'kg-link';
    a.textContent = m[0];
    if (m[1]) { a.setAttribute('href', `#/evidence/${m[1]}`); a.dataset.edge = m[1]; a.title = 'Open the evidence for this edge'; }
    else if (m[2]) { a.setAttribute('href', '#/release'); a.title = 'Datasets of this release'; }
    else if (m[3]) { a.setAttribute('href', `https://pubmed.ncbi.nlm.nih.gov/${m[3]}/`); a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    else { a.setAttribute('href', `#/entity/${m[4]}`); a.title = 'Open the entity page'; }
    frag.append(a);
    last = m.index + m[0].length;
  }
  if (!found) return null;
  if (last < text.length) frag.append(doc.createTextNode(text.slice(last)));
  return frag;
}

export function linkify(root) {
  const doc = root.ownerDocument;
  const walker = doc.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
  const nodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.parentElement && n.parentElement.closest('a, pre')) continue;
    nodes.push(n);
  }
  for (const n of nodes) {
    const frag = linkifyText(doc, n.nodeValue);
    if (frag) n.replaceWith(frag);
  }
  return root;
}

export function sanitize(html) {
  hook();
  return DOMPurify.sanitize(html, PURIFY);
}

// Render Markdown into `target` (an element). Returns the element.
export function renderMarkdown(md, target) {
  const doc = target.ownerDocument;
  const html = sanitize(marked.parse(String(md || ''), { gfm: true, breaks: false, async: false }));
  const tpl = doc.createElement('template');
  tpl.innerHTML = html; // sanitised above; parsed inert in a template
  const body = tpl.content;
  for (const t of body.querySelectorAll('table')) {
    const wrap = doc.createElement('div');
    wrap.className = 'table-wrap';
    t.replaceWith(wrap);
    wrap.append(t);
  }
  linkify(body);
  target.replaceChildren(body);
  return target;
}
