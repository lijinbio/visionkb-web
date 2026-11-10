// node --test: Markdown rendering and sanitising of hostile model output (DOMPurify in jsdom).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'https://visionkb.example/' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.Node = dom.window.Node;
const { window } = dom;
const { document } = dom.window;
const { renderMarkdown, sanitize } = await import('../../src/visionkb_web/static/js/render.js');

const HOSTILE = [
  'Answer <script>window.__pwned=1</script> <img src=x onerror="window.__pwned=2">',
  '[click](javascript:window.__pwned=3) [data](data:text/html,<script>alert(1)</script>) <a href="vbscript:x">v</a>',
  '<iframe src="https://evil.example"></iframe><object data="x"></object><embed src="x"><form action="https://evil.example"><input name=a></form>',
  '<svg onload="window.__pwned=4"><circle/></svg><math><mi xlink:href="javascript:alert(1)">x</mi></math>',
  '<style>body{display:none}</style><p style="color:red" onclick="x()" id="chat">styled</p><a href="#/entity/HGNC:1" onmouseover="x()">ok</a>',
  '<details open ontoggle="window.__pwned=5"><summary>s</summary></details> <base href="https://evil.example/">',
  '<meta http-equiv="refresh" content="0;url=https://evil.example"><link rel=stylesheet href="https://evil.example/x.css">',
  '**bold** `HGNC:10012` visionkb:e-0123456789abcdef0123456789abcdef01234567 in visionkb:ds-hrca-snrna, PMID:12345678, CL:0000604.',
  '[ext](https://www.ncbi.nlm.nih.gov/gene/6010) [route](#/release) [rel](/api/kg/proposals) [proto](//evil.example)',
].join('\n\n');

test('hostile answer is sanitised', () => {
  const el = document.createElement('div');
  renderMarkdown(HOSTILE, el);
  const html = el.innerHTML;
  for (const bad of ['<script', '<img', '<iframe', '<object', '<embed', '<form', '<input', '<svg', '<math', '<style', '<meta', '<link', '<base', '<details']) {
    assert.ok(!html.toLowerCase().includes(bad), `${bad} survived`);
  }
  for (const el2 of el.querySelectorAll('*')) {
    for (const attr of el2.getAttributeNames()) {
      assert.ok(!/^on/i.test(attr), `event handler ${attr} on ${el2.tagName}`);
      assert.ok(!['style', 'id', 'class'].includes(attr) || (attr === 'class' && el2.className === 'kg-link') || (attr === 'class' && el2.className === 'table-wrap'), `${attr} on ${el2.tagName}`);
    }
  }
  for (const a of el.querySelectorAll('a[href]')) {
    assert.match(a.getAttribute('href'), /^(https?:\/\/|#\/)/, `bad href ${a.getAttribute('href')}`);
  }
  assert.equal(window.__pwned, undefined);
  assert.ok(!/javascript:|vbscript:|data:text/i.test(html.replace(/>[^<]*</g, '><')), 'dangerous URL in markup');
  assert.ok(el.querySelector('strong'), 'Markdown still renders');
});

test('raw HTML from the model is shown as text', () => {
  const el = document.createElement('div');
  renderMarkdown('before <b onclick="x()">bold?</b> <script>alert(1)</script> after', el);
  assert.equal(el.querySelector('b'), null);
  assert.ok(el.textContent.includes('<script>alert(1)</script>'));
  assert.ok(el.textContent.includes('<b onclick="x()">'));
});

test('identifiers become in-page links', () => {
  const el = document.createElement('div');
  renderMarkdown('`HGNC:10012` expressed in CL:0000604: visionkb:e-0123456789abcdef0123456789abcdef01234567 (visionkb:ds-hrca-snrna, PMID:12345678)', el);
  const links = [...el.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href'), a.dataset.edge || null]);
  assert.deepEqual(links, [
    ['HGNC:10012', '#/entity/HGNC:10012', null],
    ['CL:0000604', '#/entity/CL:0000604', null],
    ['visionkb:e-0123456789abcdef0123456789abcdef01234567', '#/evidence/visionkb:e-0123456789abcdef0123456789abcdef01234567', 'visionkb:e-0123456789abcdef0123456789abcdef01234567'],
    ['visionkb:ds-hrca-snrna', '#/release', null],
    ['PMID:12345678', 'https://pubmed.ncbi.nlm.nih.gov/12345678/', null],
  ]);
});

test('external links open safely; relative and protocol-relative links lose href', () => {
  const el = document.createElement('div');
  renderMarkdown('[a](https://example.org) [b](/api/kg/proposals) [c](//evil.example) [d](#/about)', el);
  const [a, b, c, d] = el.querySelectorAll('a');
  assert.equal(a.getAttribute('target'), '_blank');
  assert.match(a.getAttribute('rel'), /noopener/);
  assert.equal(b.getAttribute('href'), null);
  assert.equal(c.getAttribute('href'), null);
  assert.equal(d.getAttribute('href'), '#/about');
});

test('tables are wrapped for horizontal scrolling and code blocks are not linkified', () => {
  const el = document.createElement('div');
  renderMarkdown('| a | b |\n|---|---|\n| HGNC:1 | 2 |\n\n```\nHGNC:10012\n```', el);
  assert.ok(el.querySelector('div.table-wrap > table'));
  assert.equal(el.querySelector('pre a'), null);
  assert.equal(sanitize('<a href="javascript:alert(1)">x</a>'), '<a>x</a>');
});
