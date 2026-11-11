// Boot, access gate, release badge, hash router, evidence drawer.
import * as api from './api.js';
import { createChat } from './chat.js';
import { renderHome, renderEntity, renderRelease, renderAbout, renderEvidencePage, evidenceView, fillStats } from './pages.js';
import { h, clear, errorBox } from './ui.js';

const $ = (id) => document.getElementById(id);
const main = $('main');
const ctx = { session: null, release: null, chat: null, openEvidence, setRelease };
let started = false;
let firstRoute = true;

// ---- evidence drawer ----
let lastFocus = null;
function closeDrawer() {
  $('drawer').hidden = true;
  $('drawer-backdrop').hidden = true;
  clear($('drawer'));
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}
function openEvidence(edgeId) {
  lastFocus = document.activeElement;
  const drawer = clear($('drawer'));
  const close = h('button', { type: 'button', class: 'btn btn-ghost', 'aria-label': 'Close evidence' }, 'Close');
  close.addEventListener('click', closeDrawer);
  const body = h('div', { class: 'drawer-body' });
  drawer.append(h('div', { class: 'drawer-head' }, h('div', { class: 'small muted' }, 'Evidence'), h('span', { class: 'sr-only', id: 'drawer-title' }, `Evidence for ${edgeId}`), h('div', { class: 'topbar-right' }, close)), body);
  drawer.hidden = false;
  $('drawer-backdrop').hidden = false;
  close.focus();
  evidenceView(edgeId, body, {});
}
$('drawer-backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('drawer').hidden) { e.preventDefault(); closeDrawer(); } });
document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a[data-edge]');
  if (a && !e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); openEvidence(a.dataset.edge); }
});

// ---- release badge ----
function setRelease(env) {
  if (!env || env.status !== 'ok') return;
  ctx.release = env;
  $('release-badge').querySelector('.label').textContent = env.kg_release;
  fillStats(document.getElementById('home-stats'), env);
}
async function loadRelease() {
  const badge = $('release-badge');
  try {
    const env = await api.kg('release');
    if (env.status === 'ok') setRelease(env);
    else badge.querySelector('.label').textContent = env.error?.code || 'unavailable';
  } catch { badge.querySelector('.label').textContent = 'unavailable'; }
  try {
    const r = await api.readyz();
    badge.classList.toggle('ok', r.status === 200);
    badge.classList.toggle('err', r.status !== 200);
    badge.title = r.status === 200 ? `Ready: API ok, ${r.body?.mcp?.n_tools} tools` : 'Not ready: the API or the tool server is down';
  } catch { badge.classList.add('err'); }
}

// ---- router ----
const ROUTES = [
  [/^#\/?$/, 'home', () => renderHome(main, ctx)],
  [/^#\/entity\/(.+)$/, 'home', (m) => renderEntity(main, decodeURIComponent(m[1]), ctx)],
  [/^#\/evidence\/(.+)$/, 'home', (m) => renderEvidencePage(main, decodeURIComponent(m[1]))],
  [/^#\/release\/?$/, 'release', () => renderRelease(main, ctx)],
  [/^#\/about\/?$/, 'about', () => renderAbout(main, ctx)],
  [/^#\/chat\/?$/, 'chat', () => renderChatPage(main)],
];
function route() {
  const hash = location.hash || '#/';
  if (!$('drawer').hidden) closeDrawer();
  clear(main);
  document.title = 'VisionKB — eye knowledge graph';
  let nav = '';
  const hit = ROUTES.find(([re]) => re.test(hash));
  if (hit) {
    nav = hit[1];
    hit[2](hash.match(hit[0]));
  } else {
    main.append(h('section', { class: 'panel' }, h('h1', {}, 'Not found'), h('p', {}, h('a', { href: '#/' }, 'Back to the home page'))));
  }
  if (nav === 'chat') document.title = 'Chat — VisionKB';
  for (const a of document.querySelectorAll('[data-nav]')) {
    if (a.dataset.nav === nav && (nav !== 'home' || /^#\/?$/.test(hash))) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  if (!firstRoute) { window.scrollTo(0, 0); main.focus({ preventScroll: true }); }
  ctx.chat?.layout.onRoute(hash, { initial: firstRoute });   // after the focus move: the layout may move it again
  firstRoute = false;
}

// #/chat: the chat panel fills the page (layout.js); main keeps a short note for small screens.
function renderChatPage(target) {
  target.append(h('section', { class: 'panel' }, h('h1', {}, 'Chat'),
    h('p', {}, 'The conversation is open in the chat panel. ', h('a', { href: '#/' }, 'Back to the home page'))));
}

// ---- access gate ----
function showGate(message) {
  const gate = $('gate');
  gate.hidden = false;
  $('gate-error').textContent = message || '';
  setTimeout(() => $('gate-code').focus(), 0);
}
$('gate-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = $('gate-code').value.trim();
  $('gate-error').textContent = '';
  try {
    await api.login(code);
    $('gate-code').value = '';
    $('gate').hidden = true;
    ctx.session = await api.session();
    start();
  } catch (ex) { $('gate-error').textContent = ex.message; }
});
window.addEventListener('vkw:unauthorized', () => { if ($('gate').hidden && !ctx.session?.public) showGate('Your session ended; enter the access code again.'); });
$('logout').addEventListener('click', async () => {
  await api.logout();
  ctx.chat?.forgetKey();
  showGate('Signed out.');
});

function start() {
  if (!ctx.session?.public) $('logout').hidden = false;
  loadRelease();
  if (started) { route(); return; }
  started = true;
  ctx.chat = createChat($('chat'), ctx);
  window.addEventListener('hashchange', route);
  route();
}

async function boot() {
  try {
    ctx.session = await api.session();
  } catch {
    main.append(errorBox({ message: 'The VisionKB server is not reachable.' }));
    return;
  }
  $('footer-version').textContent = `visionkb-web ${ctx.session.version}`;
  if (ctx.session.authenticated) start();
  else showGate();
}

boot();
