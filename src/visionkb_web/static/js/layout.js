// Chat panel layout: width (drag or keyboard resize), modes docked | expanded | collapsed, and the #/chat page.
// Only UI preferences ({width, mode}) are kept in localStorage under LAYOUT_KEY. The Claude key is never stored
// here: it stays in sessionStorage (api.js keyStore).
import { h } from './ui.js';

export const LAYOUT_KEY = 'visionkb-web.layout';
export const MIN_CHAT = 360;
export const MIN_MAIN = 480;
export const MAX_FRACTION = 0.7;
export const STEP = 16;
export const BIG_STEP = 64;
export const MOBILE_QUERY = '(max-width: 900px)';
export const MODES = ['docked', 'expanded', 'collapsed'];

// CSS default: --chat-w: clamp(400px, 34vw, 640px)
export function defaultWidth(vw) { return Math.min(640, Math.max(400, 0.34 * vw)); }

export function bounds(vw) {
  const max = Math.floor(Math.max(MIN_CHAT, Math.min(MAX_FRACTION * vw, vw - MIN_MAIN)));
  return { min: MIN_CHAT, max };
}

export function clampWidth(w, vw) {
  const { min, max } = bounds(vw);
  return Math.round(Math.min(max, Math.max(min, Number(w) || 0)));
}

export function parsePrefs(raw) {
  try {
    const p = JSON.parse(raw || '{}');
    return {
      width: Number.isFinite(p.width) && p.width > 0 ? Math.round(p.width) : null,
      mode: MODES.includes(p.mode) ? p.mode : 'docked',
    };
  } catch { return { width: null, mode: 'docked' }; }
}

// Ctrl/Cmd+J: not while typing in another field (the chat box itself is fine).
export function shortcutAllowed(target, chatInput) {
  if (!target || target === chatInput) return true;
  return !(target.closest && target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'));
}

const SVG = 'http://www.w3.org/2000/svg';
const ICONS = {
  page: ['M14 4h6v6', 'M20 4l-8 8', 'M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5'],
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
  try { window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({ width: prefs.width, mode: prefs.mode })); } catch { /* private mode */ }
}

// panel: the <aside id="chat">; hooks: { focusInput(), chatInput, openOverlay(bool), isOverlayOpen() }
export function createLayout(panel, hooks) {
  const root = document.documentElement;
  const body = document.body;
  const mq = window.matchMedia(MOBILE_QUERY);
  const prefs = readPrefs();
  let mode = prefs.mode;
  let lastRoute = '#/';
  let pendingMode = null;
  let raf = 0;

  const vw = () => root.clientWidth || window.innerWidth;
  const mobile = () => mq.matches;
  const live = h('div', { class: 'sr-only', role: 'status', 'aria-live': 'polite', id: 'chat-layout-status' });

  // ---- header controls ----
  const pageLink = h('a', { href: '#/chat', class: 'btn btn-ghost btn-icon chat-mode-btn chat-page-link', title: 'Open the chat as a full page', 'aria-label': 'Open the chat as a full page' }, icon('page'));
  const expandBtn = h('button', { type: 'button', class: 'btn btn-ghost btn-icon chat-mode-btn', id: 'chat-expand', 'aria-pressed': 'false', 'aria-controls': 'chat' });
  const collapseBtn = h('button', { type: 'button', class: 'btn btn-ghost btn-icon chat-mode-btn', id: 'chat-collapse', title: 'Collapse the chat (Ctrl/⌘+J)', 'aria-label': 'Collapse the chat', 'aria-expanded': 'true', 'aria-controls': 'chat' }, icon('collapse'));
  // shown only while the chat is collapsed (desktop): a floating pill at the bottom right and a top-bar button
  const restoreAttrs = { type: 'button', title: 'Show the chat (Ctrl/⌘+J)', 'aria-label': 'Ask VisionKB: show the chat', 'aria-controls': 'chat', 'aria-expanded': 'false' };
  const restoreBtn = h('button', { ...restoreAttrs, class: 'chat-restore', id: 'chat-restore' }, icon('chat'), h('span', {}, 'Ask VisionKB'));
  const topRestoreBtn = h('button', { ...restoreAttrs, class: 'btn btn-primary btn-sm chat-top-restore', id: 'chat-top-restore' }, icon('chat'), h('span', {}, 'Ask VisionKB'));
  const handle = h('div', { class: 'chat-resize', id: 'chat-resize', role: 'separator', 'aria-orientation': 'vertical', tabindex: '0',
    'aria-label': 'Resize the chat panel', 'aria-controls': 'chat', title: 'Drag to resize · double-click to reset · arrow keys' }, h('span', { class: 'grip', 'aria-hidden': 'true' }));

  const width = () => Math.round(panel.getBoundingClientRect().width);
  const updateAria = () => {
    const b = bounds(vw());
    handle.setAttribute('aria-valuemin', String(b.min));
    handle.setAttribute('aria-valuemax', String(b.max));
    const now = width();
    if (now) { handle.setAttribute('aria-valuenow', String(now)); handle.setAttribute('aria-valuetext', `${now} pixels`); }
  };
  const applyWidth = () => {
    if (prefs.width === null) root.style.removeProperty('--chat-w');
    else root.style.setProperty('--chat-w', `${clampWidth(prefs.width, vw())}px`);
    updateAria();
  };
  const setWidth = (w, { persist = true } = {}) => {
    prefs.width = clampWidth(w, vw());
    applyWidth();
    if (persist) writePrefs({ width: prefs.width, mode: prefs.mode });
  };
  const resetWidth = () => { prefs.width = null; applyWidth(); writePrefs(prefs); live.textContent = 'Chat width reset'; };

  const LABELS = { docked: 'Chat docked', expanded: 'Chat expanded', collapsed: 'Chat collapsed', page: 'Chat open as a full page' };
  function render() {
    body.dataset.chat = mode;
    const big = mode === 'expanded' || mode === 'page';
    expandBtn.setAttribute('aria-pressed', String(big));
    const label = mode === 'page' ? 'Dock the chat (leave the full page)' : big ? 'Restore the docked chat (Esc)' : 'Expand the chat';
    expandBtn.setAttribute('aria-label', label);
    expandBtn.title = label;
    expandBtn.replaceChildren(icon(big ? 'restore' : 'expand'));
    collapseBtn.setAttribute('aria-expanded', String(mode !== 'collapsed'));
    for (const b of [restoreBtn, topRestoreBtn]) b.setAttribute('aria-expanded', String(mode !== 'collapsed'));
    requestAnimationFrame(updateAria);
  }

  function setMode(next, { focus = true, persist = true, announce = true } = {}) {
    const prev = mode;
    mode = next;
    if (persist && next !== 'page') { prefs.mode = next; writePrefs(prefs); }
    render();
    if (announce && prev !== next) live.textContent = LABELS[next];
    if (!focus) return;
    if (next === 'collapsed') restoreBtn.focus();
    else if (next === 'docked' && (prev === 'expanded' || prev === 'page')) expandBtn.focus();
    else hooks.focusInput();
  }

  // ---- route hook (#/chat page; leaving an expanded chat by following a link docks it) ----
  function onRoute(hash, { initial = false } = {}) {
    if (/^#\/chat\/?$/.test(hash)) {
      if (mobile()) { hooks.openOverlay(true); return; }
      setMode('page', { persist: false, focus: !initial });
      return;
    }
    lastRoute = hash || '#/';
    const next = pendingMode || 'docked';
    pendingMode = null;
    if (!initial && (mode === 'page' || mode === 'expanded')) setMode(next, { focus: next === 'collapsed' });
  }

  // leave #/chat for the last page; the chat then takes mode `next`
  function leavePage(next = 'docked') {
    pendingMode = next;
    if (location.hash === lastRoute) onRoute(lastRoute);
    else location.hash = lastRoute;
  }

  expandBtn.addEventListener('click', () => {
    if (mode === 'page') leavePage();
    else setMode(mode === 'expanded' ? 'docked' : 'expanded');
  });
  collapseBtn.addEventListener('click', () => {
    if (mode === 'page') leavePage('collapsed');
    else setMode('collapsed');
  });
  for (const b of [restoreBtn, topRestoreBtn]) b.addEventListener('click', () => setMode('docked'));

  // ---- pointer resize (rAF-throttled; the main column reflows once per frame) ----
  let dragging = false;
  let offset = 0;
  let pendingX = null;
  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || mobile()) return;
    e.preventDefault();
    dragging = true;
    offset = e.clientX - panel.getBoundingClientRect().left;
    handle.setPointerCapture(e.pointerId);
    body.classList.add('chat-resizing');
  });
  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    pendingX = e.clientX;
    if (!raf) raf = requestAnimationFrame(() => {
      raf = 0;
      if (pendingX !== null) setWidth(vw() - (pendingX - offset), { persist: false });
    });
  });
  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    body.classList.remove('chat-resizing');
    try { handle.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    if (pendingX !== null) setWidth(vw() - (pendingX - offset));
    pendingX = null;
  };
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('dblclick', resetWidth);
  handle.addEventListener('keydown', (e) => {
    const b = bounds(vw());
    const step = e.shiftKey ? BIG_STEP : STEP;
    let w = null;
    if (e.key === 'ArrowLeft') w = width() + step;
    else if (e.key === 'ArrowRight') w = width() - step;
    else if (e.key === 'Home') w = b.max;
    else if (e.key === 'End') w = b.min;
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); resetWidth(); return; }
    if (w === null) return;
    e.preventDefault();
    setWidth(w);
  });
  let resizeRaf = 0;
  window.addEventListener('resize', () => {
    if (resizeRaf) return;
    resizeRaf = requestAnimationFrame(() => { resizeRaf = 0; applyWidth(); });
  });

  // ---- keyboard: Ctrl/Cmd+J toggles collapsed/docked; Esc leaves the expanded mode ----
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
    if (e.key === 'Escape' && mode === 'expanded' && !e.defaultPrevented && !document.querySelector('dialog[open]')) {
      e.preventDefault();
      setMode('docked');
    }
  });

  panel.prepend(handle);
  body.append(restoreBtn, live);
  const topbarRight = document.querySelector('.topbar-right');
  if (topbarRight) topbarRight.insertBefore(topRestoreBtn, document.getElementById('logout'));
  applyWidth();
  setMode(mode, { focus: false, persist: false, announce: false });
  return { buttons: [pageLink, expandBtn, collapseBtn], onRoute, setMode, setWidth, resetWidth, get mode() { return mode; } };
}
