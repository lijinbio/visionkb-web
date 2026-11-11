// Chat panel layout: modes docked | collapsed, and the full page #/chat (the one "Expand" control navigates there, so
// the URL, Back and bookmarks work). Resizable widths: the docked panel (left edge) and the full-page column (both
// edges, symmetric). Only UI preferences ({width, fullWidth, mode}) are kept in localStorage under LAYOUT_KEY; the
// Claude key is never stored here: it stays in sessionStorage (api.js keyStore).
import { h } from './ui.js';

export const LAYOUT_KEY = 'visionkb-web.layout';
export const MIN_CHAT = 360;
export const MIN_MAIN = 480;
export const MAX_FRACTION = 0.55;
// Full-page column, in units of the browser's base font size `base` (16 px by default; the page root is 93.75% of it,
// so base = root font px / 0.9375) so it follows the user's font size / zoom: default clamp(45, 60vw, 60) x base,
// resizable 35 .. 87.5 x base (560 .. 1400 px at 16 px) and never wider than the viewport - 64 px.
export const MIN_FULL_BASE = 35;
export const MAX_FULL_BASE = 87.5;
export const FULL_GUTTER = 64;
export const STEP = 16;
export const BIG_STEP = 64;
export const MOBILE_QUERY = '(max-width: 900px)';
export const MODES = ['docked', 'collapsed'];
const CHAT_ROUTE = /^#\/chat\/?$/;

// CSS defaults: --chat-w: clamp(400px, 34vw, 640px); --chat-full-w: clamp(45 * --u16, 60vw, 60 * --u16).
export function defaultWidth(vw) { return Math.min(640, Math.max(400, 0.34 * vw)); }
export function defaultFullWidth(vw, base = 16) { return Math.min(60 * base, Math.max(45 * base, 0.6 * vw)); }

export function bounds(vw) {
  return { min: MIN_CHAT, max: Math.floor(Math.max(MIN_CHAT, Math.min(MAX_FRACTION * vw, vw - MIN_MAIN))) };
}
export function fullBounds(vw, base = 16) {
  const min = Math.round(MIN_FULL_BASE * base);
  return { min, max: Math.floor(Math.max(min, Math.min(MAX_FULL_BASE * base, vw - FULL_GUTTER))) };
}

function clampTo(b, w) { return Math.round(Math.min(b.max, Math.max(b.min, Number(w) || 0))); }
export function clampWidth(w, vw) { return clampTo(bounds(vw), w); }
export function clampFullWidth(w, vw, base = 16) { return clampTo(fullBounds(vw, base), w); }

// v0.0.3 stored mode "expanded" (an in-place full view, now merged into #/chat) migrates to "docked".
export function parsePrefs(raw) {
  let p;
  try { p = JSON.parse(raw || '{}') || {}; } catch { p = {}; }
  if (typeof p !== 'object') p = {};
  const num = (x) => (Number.isFinite(x) && x > 0 ? Math.round(x) : null);
  return {
    width: num(p.width),
    fullWidth: num(p.fullWidth),
    mode: MODES.includes(p.mode) ? p.mode : 'docked',
    migrated: p.mode === 'expanded',
  };
}

// Ctrl/Cmd+J: not while typing in another field (the chat box itself is fine).
export function shortcutAllowed(target, chatInput) {
  if (!target || target === chatInput) return true;
  return !(target.closest && target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'));
}

const SVG = 'http://www.w3.org/2000/svg';
const ICONS = {
  expand: ['M4 9V4h5', 'M20 9V4h-5', 'M4 15v5h5', 'M20 15v5h-5'],
  restore: ['M9 4v5H4', 'M15 4v5h5', 'M9 20v-5H4', 'M15 20v-5h5'],
  collapse: ['M13 6l6 6-6 6', 'M5 6l6 6-6 6'],
  chat: ['M21 12a8 8 0 0 1-11.6 7.1L4 20l1.2-4.4A8 8 0 1 1 21 12z', 'M8.5 11h7', 'M8.5 14.5h4.5'],
};
export function icon(name) {
  const svg = document.createElementNS(SVG, 'svg');
  for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', width: '18', height: '18', fill: 'none', stroke: 'currentColor',
    'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false' })) svg.setAttribute(k, v);
  for (const d of ICONS[name]) { const p = document.createElementNS(SVG, 'path'); p.setAttribute('d', d); svg.append(p); }
  return svg;
}

function readPrefs() {
  try { return parsePrefs(window.localStorage.getItem(LAYOUT_KEY)); } catch { return parsePrefs(null); }
}
function writePrefs(prefs) {
  const { width, fullWidth, mode } = prefs;
  try { window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({ width, fullWidth, mode })); } catch { /* private mode */ }
}

// panel: the <aside id="chat">; hooks: { focusInput(), chatInput, openOverlay(bool), isOverlayOpen() }
export function createLayout(panel, hooks) {
  const root = document.documentElement;
  const body = document.body;
  const mq = window.matchMedia(MOBILE_QUERY);
  const prefs = readPrefs();
  let mode = prefs.mode;               // docked | collapsed | page (#/chat; never stored)
  let lastRoute = '#/';
  let enteredInApp = false;            // #/chat reached from another page of this tab: leaving = history.back()
  let pendingMode = null;

  const vw = () => root.clientWidth || window.innerWidth;
  const basePx = () => (parseFloat(getComputedStyle(root).fontSize) || 15) / 0.9375;   // see app.css --u16
  const mobile = () => mq.matches;
  const live = h('div', { class: 'sr-only', role: 'status', 'aria-live': 'polite', id: 'chat-layout-status' });

  // ---- header controls: Expand (to #/chat) / Dock, Collapse; restore buttons while collapsed ----
  const expandBtn = h('button', { type: 'button', class: 'btn btn-ghost btn-icon chat-mode-btn', id: 'chat-expand', 'aria-pressed': 'false', 'aria-controls': 'chat' });
  const collapseBtn = h('button', { type: 'button', class: 'btn btn-ghost btn-icon chat-mode-btn', id: 'chat-collapse', title: 'Collapse the chat (Ctrl/⌘+J)', 'aria-label': 'Collapse the chat', 'aria-expanded': 'true', 'aria-controls': 'chat' }, icon('collapse'));
  const restoreAttrs = { type: 'button', title: 'Show the chat (Ctrl/⌘+J)', 'aria-label': 'Ask VisionKB: show the chat', 'aria-controls': 'chat', 'aria-expanded': 'false' };
  const restoreBtn = h('button', { ...restoreAttrs, class: 'chat-restore', id: 'chat-restore' }, icon('chat'), h('span', {}, 'Ask VisionKB'));
  const topRestoreBtn = h('button', { ...restoreAttrs, class: 'btn btn-primary btn-sm chat-top-restore', id: 'chat-top-restore' }, icon('chat'), h('span', {}, 'Ask VisionKB'));

  // ---- widths ----
  const KINDS = {
    dock: { prop: '--chat-w', key: 'width', bounds, label: 'Resize the chat panel' },
    full: { prop: '--chat-full-w', key: 'fullWidth', bounds: (v) => fullBounds(v, basePx()), label: 'Resize the chat column' },
  };
  const handles = [];
  const width = () => Math.round(panel.getBoundingClientRect().width);
  const updateAria = () => {
    const now = width();
    for (const hd of handles) {
      const b = KINDS[hd.dataset.kind].bounds(vw());
      hd.setAttribute('aria-valuemin', String(b.min));
      hd.setAttribute('aria-valuemax', String(b.max));
      if (now) { hd.setAttribute('aria-valuenow', String(now)); hd.setAttribute('aria-valuetext', `${now} pixels`); }
    }
  };
  const applyWidths = () => {
    for (const k of Object.values(KINDS)) {
      if (prefs[k.key] === null) root.style.removeProperty(k.prop);
      else root.style.setProperty(k.prop, `${clampTo(k.bounds(vw()), prefs[k.key])}px`);
    }
    updateAria();
  };
  const setWidth = (kind, w, { persist = true } = {}) => {
    const k = KINDS[kind];
    prefs[k.key] = clampTo(k.bounds(vw()), w);
    applyWidths();
    if (persist) writePrefs(prefs);
  };
  const resetWidth = (kind) => { prefs[KINDS[kind].key] = null; applyWidths(); writePrefs(prefs); live.textContent = 'Chat width reset'; };

  // One handle: kind dock (left edge of the docked panel) or full (left/right edge of the centred column; symmetric).
  function makeHandle(kind, side) {
    const k = KINDS[kind];
    const hd = h('div', { class: `chat-resize chat-resize-${kind} chat-resize-${side}`, id: kind === 'dock' ? 'chat-resize' : `chat-resize-full-${side}`,
      role: 'separator', 'aria-orientation': 'vertical', tabindex: '0', 'aria-label': k.label, 'aria-controls': 'chat',
      title: 'Drag to resize · double-click or Enter to reset · arrow keys', dataset: { kind } }, h('span', { class: 'grip', 'aria-hidden': 'true' }));
    const widthAt = (x, start) => (kind === 'dock'
      ? vw() - (x - start.offset)
      : 2 * (Math.abs(x - start.center) - start.offset));
    let start = null;
    let pendingX = null;
    let raf = 0;
    hd.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || mobile()) return;
      e.preventDefault();
      const r = panel.getBoundingClientRect();
      const center = r.left + r.width / 2;
      start = { offset: kind === 'dock' ? e.clientX - r.left : Math.abs(e.clientX - center) - r.width / 2, center };
      hd.setPointerCapture(e.pointerId);
      body.classList.add('chat-resizing');
    });
    hd.addEventListener('pointermove', (e) => {
      if (!start) return;
      pendingX = e.clientX;
      if (!raf) raf = requestAnimationFrame(() => {   // one reflow per frame
        raf = 0;
        if (start && pendingX !== null) setWidth(kind, widthAt(pendingX, start), { persist: false });
      });
    });
    const end = (e) => {
      if (!start) return;
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      if (pendingX !== null) setWidth(kind, widthAt(pendingX, start));
      start = null;
      pendingX = null;
      body.classList.remove('chat-resizing');
      try { hd.releasePointerCapture(e.pointerId); } catch { /* released */ }
    };
    hd.addEventListener('pointerup', end);
    hd.addEventListener('pointercancel', end);
    hd.addEventListener('dblclick', () => resetWidth(kind));
    const grow = side === 'right' ? 'ArrowRight' : 'ArrowLeft';
    const shrink = side === 'right' ? 'ArrowLeft' : 'ArrowRight';
    hd.addEventListener('keydown', (e) => {
      const b = k.bounds(vw());
      const step = (e.shiftKey ? BIG_STEP : STEP) * (kind === 'full' ? 2 : 1);   // full: both edges move
      let w = null;
      if (e.key === grow) w = width() + step;
      else if (e.key === shrink) w = width() - step;
      else if (e.key === 'Home') w = b.max;
      else if (e.key === 'End') w = b.min;
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); resetWidth(kind); return; }
      if (w === null) return;
      e.preventDefault();
      setWidth(kind, w);
    });
    handles.push(hd);
    return hd;
  }

  const LABELS = { docked: 'Chat docked', collapsed: 'Chat collapsed', page: 'Chat open as a full page' };
  function render() {
    body.dataset.chat = mode;
    const page = mode === 'page';
    expandBtn.setAttribute('aria-pressed', String(page));
    const label = page ? 'Dock the chat (Esc)' : 'Expand the chat to a full page';
    expandBtn.setAttribute('aria-label', label);
    expandBtn.title = label;
    expandBtn.replaceChildren(icon(page ? 'restore' : 'expand'));
    collapseBtn.setAttribute('aria-expanded', String(mode !== 'collapsed'));
    for (const b of [restoreBtn, topRestoreBtn]) b.setAttribute('aria-expanded', String(mode !== 'collapsed'));
    requestAnimationFrame(updateAria);
  }

  function setMode(next, { focus = true, announce = true, persist = true } = {}) {
    const prev = mode;
    mode = next;
    if (persist && next !== 'page') { prefs.mode = next; writePrefs(prefs); }
    render();
    if (announce && prev !== next) live.textContent = LABELS[next];
    if (!focus) return;
    if (next === 'collapsed') restoreBtn.focus();
    else if (next === 'docked' && prev === 'page') expandBtn.focus();
    else hooks.focusInput();
  }

  // ---- routes: #/chat is the full page; any other route docks (or collapses, when asked) the chat ----
  function onRoute(hash, { initial = false } = {}) {
    if (CHAT_ROUTE.test(hash)) {
      if (mobile()) { hooks.openOverlay(true); return; }
      enteredInApp = !initial;
      if (mode !== 'page') setMode('page', { focus: !initial });
      return;
    }
    lastRoute = hash || '#/';
    if (mode === 'page') {
      setMode(pendingMode || 'docked', { focus: !initial });   // Back, Esc, an entity link: docked
    }
    pendingMode = null;
  }
  // leave #/chat: back to the page it was opened from (Back-button semantics), else the last page / home
  function leavePage(next = 'docked') {
    pendingMode = next;
    if (enteredInApp && window.history.length > 1) window.history.back();
    else location.hash = lastRoute;
  }

  expandBtn.addEventListener('click', () => {
    if (mode === 'page') leavePage('docked');
    else location.hash = '#/chat';
  });
  collapseBtn.addEventListener('click', () => (mode === 'page' ? leavePage('collapsed') : setMode('collapsed')));
  for (const b of [restoreBtn, topRestoreBtn]) b.addEventListener('click', () => setMode('docked'));

  let resizeRaf = 0;
  window.addEventListener('resize', () => {
    if (resizeRaf) return;
    resizeRaf = requestAnimationFrame(() => { resizeRaf = 0; applyWidths(); });
  });

  // ---- keyboard: Ctrl/Cmd+J toggles collapsed/docked; Esc leaves the full page ----
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'j' || e.key === 'J')) {
      if (!shortcutAllowed(e.target, hooks.chatInput)) return;
      e.preventDefault();
      if (mobile()) { hooks.openOverlay(!hooks.isOverlayOpen()); return; }
      if (mode === 'collapsed') setMode('docked');
      else if (mode === 'page') leavePage('collapsed');
      else setMode('collapsed');
      return;
    }
    if (e.key === 'Escape' && mode === 'page' && !e.defaultPrevented && !document.querySelector('dialog[open]')) {
      e.preventDefault();
      leavePage('docked');
    }
  });

  panel.prepend(makeHandle('dock', 'left'), makeHandle('full', 'left'), makeHandle('full', 'right'));
  body.append(restoreBtn, live);
  const topbarRight = document.querySelector('.topbar-right');
  if (topbarRight) topbarRight.insertBefore(topRestoreBtn, document.getElementById('logout'));
  // Stored widths above the current maximum (e.g. a 0.0.3 width under the old 70% rule; the docked max is now 55%) are re-clamped and rewritten;
  // also the migrated "expanded" mode. Not on mobile: the phone layout must not shrink the desktop preference.
  let rewrite = prefs.migrated;
  if (!mobile()) {
    for (const k of Object.values(KINDS)) {
      const max = k.bounds(vw()).max;
      if (prefs[k.key] !== null && prefs[k.key] > max) { prefs[k.key] = max; rewrite = true; }
    }
  }
  if (rewrite) writePrefs(prefs);
  applyWidths();
  setMode(mode, { focus: false, announce: false, persist: false });
  return {
    buttons: [expandBtn, collapseBtn], onRoute, setMode,
    setWidth: (w) => setWidth('dock', w), setFullWidth: (w) => setWidth('full', w),
    get mode() { return mode; },
  };
}
