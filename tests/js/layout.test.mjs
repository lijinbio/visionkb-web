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

test('bounds: chat >= 360, main >= 480, chat <= 70% of the viewport', () => {
  assert.deepEqual(L.bounds(1366), { min: 360, max: 886 });   // vw - 480 binds
  assert.deepEqual(L.bounds(1920), { min: 360, max: 1344 });  // 70% binds
  assert.deepEqual(L.bounds(901), { min: 360, max: 421 });
  assert.equal(L.clampWidth(100, 1366), 360);
  assert.equal(L.clampWidth(5000, 1366), 886);
  assert.equal(L.clampWidth(700.4, 1366), 700);
  for (const vw of [901, 1024, 1366, 1600, 1920, 2560]) {
    const { max } = L.bounds(vw);
    assert.ok(vw - max >= 480 && max <= 0.7 * vw + 1e-9, String(vw));
    const d = L.defaultWidth(vw);
    assert.ok(d >= 360 && d <= max, `default within bounds at ${vw}`);
  }
});

test('stored preferences are validated', () => {
  assert.deepEqual(L.parsePrefs('{"width": 720, "mode": "collapsed"}'), { width: 720, mode: 'collapsed' });
  assert.deepEqual(L.parsePrefs('{"width": "x", "mode": "page"}'), { width: null, mode: 'docked' });
  assert.deepEqual(L.parsePrefs('not json'), { width: null, mode: 'docked' });
  assert.deepEqual(L.parsePrefs(null), { width: null, mode: 'docked' });
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
