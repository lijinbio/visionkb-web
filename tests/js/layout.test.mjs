// node --test: pure layout helpers (width bounds, defaults, stored preferences, shortcut guard).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<!doctype html><html><body><input id="q"><textarea id="chat"></textarea><div contenteditable="true" id="ce"></div><button id="b"></button></body></html>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.Node = dom.window.Node;
const { document } = dom.window;
const L = await import('../../src/visionkb_web/static/js/layout.js');

test('default width follows clamp(400px, 34vw, 640px)', () => {
  assert.equal(L.defaultWidth(1000), 400);
  assert.equal(Math.round(L.defaultWidth(1366)), 464);
  assert.equal(L.defaultWidth(1920), 640);
});

test('bounds: chat >= 360, main >= 480, chat <= 55% of the viewport', () => {
  assert.deepEqual(L.bounds(1366), { min: 360, max: 751 });   // 55% binds
  assert.deepEqual(L.bounds(1920), { min: 360, max: 1056 });  // 55% binds
  assert.deepEqual(L.bounds(1000), { min: 360, max: 520 });   // vw - 480 binds
  assert.deepEqual(L.bounds(901), { min: 360, max: 421 });
  assert.equal(L.clampWidth(100, 1366), 360);
  assert.equal(L.clampWidth(5000, 1366), 751);
  assert.equal(L.clampWidth(1344, 1920), 1056);  // a 0.0.3 maximum is re-clamped
  assert.equal(L.clampWidth(700.4, 1366), 700);
  for (const vw of [901, 1024, 1366, 1600, 1920, 2560]) {
    const { max } = L.bounds(vw);
    assert.ok(vw - max >= 480 && max <= 0.55 * vw + 1e-9, String(vw));
    const d = L.defaultWidth(vw);
    assert.ok(d >= 360 && d <= max, `default within bounds at ${vw}`);
  }
});

test('full-page column: default clamp(45rem, 60vw, 60rem), bounds 35rem .. min(87.5rem, viewport - 64)', () => {
  assert.equal(L.defaultFullWidth(901), 720);
  assert.equal(L.defaultFullWidth(1366), 819.6);
  assert.equal(L.defaultFullWidth(1920), 960);
  assert.equal(L.defaultFullWidth(2560), 960);
  assert.equal(L.defaultFullWidth(1920, 20), 1152);   // 20 px base font: clamp(900, 1152, 1200)
  assert.equal(L.defaultFullWidth(2560, 20), 1200);
  assert.deepEqual(L.fullBounds(1920, 20), { min: 700, max: 1750 });
  assert.deepEqual(L.fullBounds(1366, 20), { min: 700, max: 1302 });
  assert.deepEqual(L.fullBounds(1366), { min: 560, max: 1302 });
  assert.deepEqual(L.fullBounds(1920), { min: 560, max: 1400 });
  assert.deepEqual(L.fullBounds(2560), { min: 560, max: 1400 });
  assert.deepEqual(L.fullBounds(1000), { min: 560, max: 936 });
  assert.equal(L.clampFullWidth(100, 1366), 560);
  assert.equal(L.clampFullWidth(5000, 1920), 1400);
  for (const vw of [901, 1366, 1920, 2560]) assert.ok(L.defaultFullWidth(vw) <= L.fullBounds(vw).max, String(vw));
});

test('stored preferences are validated; the v0.0.3 mode "expanded" migrates to docked', () => {
  assert.deepEqual(L.parsePrefs('{"width": 720, "fullWidth": 900, "mode": "collapsed"}'), { width: 720, fullWidth: 900, mode: 'collapsed', migrated: false });
  assert.deepEqual(L.parsePrefs('{"width": 700, "mode": "expanded"}'), { width: 700, fullWidth: null, mode: 'docked', migrated: true });
  assert.deepEqual(L.parsePrefs('{"width": "x", "mode": "page"}'), { width: null, fullWidth: null, mode: 'docked', migrated: false });
  assert.deepEqual(L.parsePrefs('not json'), { width: null, fullWidth: null, mode: 'docked', migrated: false });
  assert.deepEqual(L.parsePrefs(null), { width: null, fullWidth: null, mode: 'docked', migrated: false });
  assert.deepEqual(L.parsePrefs('42'), { width: null, fullWidth: null, mode: 'docked', migrated: false });
  assert.deepEqual(L.MODES, ['docked', 'collapsed']);
  assert.equal(L.LAYOUT_KEY, 'visionkb-web.layout');
});

test('Ctrl/Cmd+J is not taken from other inputs, only from the chat box and the page', () => {
  const $ = (id) => document.getElementById(id);
  assert.equal(L.shortcutAllowed($('chat'), $('chat')), true);
  assert.equal(L.shortcutAllowed($('b'), $('chat')), true);
  assert.equal(L.shortcutAllowed(document.body, $('chat')), true);
  assert.equal(L.shortcutAllowed($('q'), $('chat')), false);
  assert.equal(L.shortcutAllowed($('ce'), $('chat')), false);
});
