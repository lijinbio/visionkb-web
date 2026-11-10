// Chat panel: key entry (sessionStorage only), model picker (/api/models), streamed answers with tool traces.
import { keyStore, models as listModels, chat as postChat } from './api.js';
import { renderMarkdown } from './render.js';
import { h, clear, fmt } from './ui.js';
import { EXAMPLES } from './pages.js';

const HISTORY = 'vkw.chat';
const MODEL = 'vkw.model';
const NOTICE = 'vkw.notice_ack';

function loadHistory() {
  try { return JSON.parse(sessionStorage.getItem(HISTORY) || '[]'); } catch { return []; }
}

export function createChat(panel, ctx) {
  let history = loadHistory();
  let modelList = [];
  let busy = null; // AbortController of the running answer
  const maxChars = ctx.session?.limits?.max_message_chars || 8000;

  const save = () => {
    try { sessionStorage.setItem(HISTORY, JSON.stringify(history.slice(-60))); } catch { /* quota: keep in memory */ }
  };

  // ---- header ----
  const newBtn = h('button', { type: 'button', class: 'btn btn-ghost btn-sm', title: 'Start a new conversation' }, 'New chat');
  const closeBtn = h('button', { type: 'button', class: 'btn btn-ghost btn-sm chat-toggle', 'aria-label': 'Close chat' }, 'Close');
  const head = h('div', { class: 'chat-head' },
    h('div', {}, h('h2', {}, 'Ask VisionKB'), h('div', { class: 'sub' }, 'Answers from the KG tools · your own Claude key')),
    h('div', { class: 'actions' }, newBtn, closeBtn));

  // ---- key + model ----
  const keyBox = h('div', { class: 'chat-key' });
  const modelSel = h('select', { id: 'chat-model', 'aria-label': 'Claude model' });
  modelSel.addEventListener('change', () => sessionStorage.setItem(MODEL, modelSel.value));

  const ensureNotice = () => new Promise((resolve) => {
    if (sessionStorage.getItem(NOTICE) === '1') { resolve(true); return; }
    const dlg = document.getElementById('notice');
    const onClose = () => {
      dlg.removeEventListener('close', onClose);
      const okd = dlg.returnValue === 'ok';
      if (okd) sessionStorage.setItem(NOTICE, '1');
      resolve(okd);
    };
    dlg.addEventListener('close', onClose);
    dlg.returnValue = '';
    dlg.showModal();
  });

  const fillModels = (data, preferred) => {
    modelList = data.data || [];
    clear(modelSel);
    for (const m of modelList) modelSel.append(h('option', { value: m.id }, m.display_name && m.display_name !== m.id ? `${m.display_name} (${m.id})` : m.id));
    const stored = sessionStorage.getItem(MODEL);
    const pick = [preferred, stored, data.default_model].find((x) => x && modelList.some((m) => m.id === x));
    if (pick) modelSel.value = pick;
    sessionStorage.setItem(MODEL, modelSel.value);
  };

  const renderKey = async (message) => {
    clear(keyBox);
    const key = keyStore.get();
    if (!key) {
      const input = h('input', { type: 'password', id: 'chat-key', placeholder: 'sk-ant-…', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'chat-key-help' });
      const err = h('p', { class: 'form-error', role: 'alert' }, message || '');
      const form = h('form', { autocomplete: 'off' },
        h('label', { for: 'chat-key' }, 'Your Claude API key'),
        h('div', { class: 'row' }, input, h('button', { type: 'submit', class: 'btn btn-primary' }, 'Use key')), err,
        h('p', { class: 'small muted', id: 'chat-key-help' }, 'Kept in this tab only and sent to this server for each call to Anthropic; never stored there. Create one at ',
          h('a', { href: 'https://console.anthropic.com/settings/keys', target: '_blank', rel: 'noopener noreferrer' }, 'console.anthropic.com'), '.'));
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const k = input.value.trim();
        if (!k) { err.textContent = 'Paste a key first.'; return; }
        if (!(await ensureNotice())) { err.textContent = 'The chat needs the notice to be acknowledged.'; return; }
        err.textContent = 'Checking the key…';
        try {
          const data = await listModels(k);
          keyStore.set(k);
          input.value = '';
          renderKey();
          fillModels(data);
        } catch (ex) { err.textContent = `${ex.message}${ex.code ? ` (${ex.code})` : ''}`; }
      });
      keyBox.append(form);
      return;
    }
    const forget = h('button', { type: 'button', class: 'btn btn-sm' }, 'Forget key');
    forget.addEventListener('click', () => { keyStore.forget(); sessionStorage.removeItem(MODEL); renderKey('Key forgotten.'); });
    const status = h('span', { class: 'small muted' }, 'loading models…');
    keyBox.append(
      h('div', { class: 'row' }, h('span', { class: 'key-ok' }, 'Key set for this tab'), forget),
      h('div', { class: 'row' }, h('label', { for: 'chat-model', class: 'small' }, 'Model'), modelSel), status);
    if (modelList.length) { status.remove(); return; }
    try {
      fillModels(await listModels(key));
      status.remove();
    } catch (ex) {
      if (ex.code === 'invalid_key') { keyStore.forget(); renderKey(`The key was rejected: ${ex.message}`); return; }
      status.textContent = `Could not list models: ${ex.message}`;
    }
  };

  // ---- log ----
  const log = h('div', { class: 'chat-log', role: 'log', 'aria-live': 'polite', 'aria-relevant': 'additions', tabindex: '0', 'aria-label': 'Conversation' });
  const live = h('span', { class: 'sr-only', role: 'status', 'aria-live': 'polite' });

  const traceEl = (msg) => {
    const calls = msg.trace || [];
    if (!calls.length) return null;
    const rel = [...new Set(calls.map((c) => c.kg_release).filter(Boolean))];
    const d = h('details', { class: 'trace' },
      h('summary', {}, `${calls.length} tool call${calls.length === 1 ? '' : 's'}${rel.length ? ` · ${rel.join(', ')}` : ''}${calls.some((c) => c.status === 'running') ? ' · running…' : ''}`),
      h('ol', {}, calls.map((c) => h('li', {},
        h('span', { class: 'tname' }, c.name), ' ',
        h('span', { class: c.status === 'ok' ? 'status-ok' : c.status === 'error' ? 'status-error' : 'status-run' },
          c.status === 'running' ? 'running…' : c.status),
        c.returned !== undefined && c.returned !== null ? ` · ${fmt.int(c.returned)} row${c.returned === 1 ? '' : 's'}${c.total !== null && c.total !== undefined ? ` of ${fmt.int(c.total)}` : ''}` : '',
        c.error_code ? ` · ${c.error_code}` : '',
        c.kg_release ? h('span', { class: 'muted' }, ` · ${c.kg_release}`) : '',
        h('code', { class: 'targs' }, JSON.stringify(c.input))))));
    if (msg.traceOpen) d.open = true;
    d.addEventListener('toggle', () => { msg.traceOpen = d.open; });
    return d;
  };

  const metaEl = (msg) => {
    if (!msg.meta) return null;
    const u = msg.meta.usage || {};
    const copy = h('button', { type: 'button', class: 'btn btn-ghost btn-sm' }, 'Copy');
    copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(msg.content); copy.textContent = 'Copied'; } catch { copy.textContent = 'Copy failed'; } });
    return h('div', { class: 'meta' },
      h('span', {}, msg.meta.model || ''),
      h('span', { title: 'input / output tokens (cache read)' }, `${fmt.int(u.input_tokens)} in · ${fmt.int(u.output_tokens)} out${u.cache_read_input_tokens ? ` · ${fmt.int(u.cache_read_input_tokens)} cached` : ''}`),
      msg.meta.elapsed_s !== undefined ? h('span', {}, `${msg.meta.elapsed_s} s`) : null,
      msg.meta.history_dropped ? h('span', {}, `${msg.meta.history_dropped} old turns not sent`) : null,
      msg.meta.stop_reason && msg.meta.stop_reason !== 'end_turn' ? h('span', {}, `stop: ${msg.meta.stop_reason}`) : null,
      copy);
  };

  const msgEl = (msg) => {
    if (msg.role === 'user') return h('div', { class: 'msg user' }, msg.content);
    const md = h('div', { class: 'md' });
    if (msg.content) renderMarkdown(msg.content, md);
    else if (msg.streaming && !(msg.trace || []).length) md.append(h('span', { class: 'muted' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), ' Thinking…'));
    if (msg.streaming) md.classList.add('cursor');
    const el = h('div', { class: `msg assistant${msg.error ? ' error' : ''}` }, traceEl(msg), md,
      msg.error ? h('p', { role: 'alert' }, `${msg.error.message}${msg.error.code ? ` (${msg.error.code})` : ''}`) : null, metaEl(msg));
    msg.el = el;
    return el;
  };

  const renderEmpty = () => {
    const box = h('div', { class: 'chat-empty' },
      h('p', {}, 'Ask in plain language. The assistant looks things up in VisionKB with tools and cites the release and the evidence (edge ids, datasets).'),
      h('ul', {}, EXAMPLES.slice(0, 4).map(([, q]) => {
        const b = h('button', { type: 'button' }, q);
        b.addEventListener('click', () => ask(q, { send: true }));
        return h('li', {}, b);
      })));
    log.append(box);
  };

  const renderLog = () => {
    clear(log);
    if (!history.length) renderEmpty();
    for (const m of history) log.append(msgEl(m));
    log.scrollTop = log.scrollHeight;
  };

  let pending = 0;
  const refresh = (msg) => {
    if (pending) return;
    pending = requestAnimationFrame(() => {
      pending = 0;
      const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
      const old = msg.el;
      const el = msgEl(msg);
      if (old && old.parentNode) old.replaceWith(el); else log.append(el);
      if (nearBottom) log.scrollTop = log.scrollHeight;
    });
  };

  // ---- input ----
  const ta = h('textarea', { id: 'chat-input', rows: '2', maxlength: String(maxChars), placeholder: 'Ask about a gene, cell type, disease or dataset…', 'aria-label': 'Your question' });
  const count = h('span', { class: 'count' }, '');
  const sendBtn = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Send');
  const form = h('form', { class: 'chat-input' }, ta, h('div', { class: 'row' }, count, sendBtn));
  const updateCount = () => {
    count.textContent = ta.value.length > maxChars * 0.8 ? `${ta.value.length}/${maxChars}` : 'Enter to send · Shift+Enter for a new line';
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight + 2, 192)}px`;
  };
  ta.addEventListener('input', updateCount);
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener('submit', (e) => { e.preventDefault(); if (busy) { busy.abort(); return; } send(ta.value.trim()); });

  const setBusy = (ctrl) => {
    busy = ctrl;
    sendBtn.textContent = ctrl ? 'Stop' : 'Send';
    sendBtn.classList.toggle('btn-primary', !ctrl);
    ta.disabled = !!ctrl;
    newBtn.disabled = !!ctrl;
  };

  async function send(text) {
    if (!text) return;
    const key = keyStore.get();
    if (!key) { renderKey('Enter your Claude API key to ask questions.'); keyBox.querySelector('input')?.focus(); return; }
    if (!(await ensureNotice())) return;
    if (!modelSel.value) { live.textContent = 'No model selected.'; return; }
    if (text.length > maxChars) { live.textContent = `At most ${maxChars} characters.`; return; }
    if (!history.length) clear(log);
    const user = { role: 'user', content: text };
    history.push(user);
    log.append(msgEl(user));
    const msg = { role: 'assistant', content: '', trace: [], streaming: true };
    history.push(msg);
    log.append(msgEl(msg));
    log.scrollTop = log.scrollHeight;
    ta.value = '';
    updateCount();
    const sent = history.filter((m) => !m.error && m.content && m !== msg).map((m) => ({ role: m.role, content: m.content }));
    const ctrl = new AbortController();
    setBusy(ctrl);
    live.textContent = 'Answering…';
    try {
      await postChat({
        key, model: modelSel.value, messages: sent, signal: ctrl.signal,
        onEvent: (ev, data) => {
          if (ev === 'text') msg.content += data.delta;
          else if (ev === 'tool_call') msg.trace.push({ ...data, status: 'running' });
          else if (ev === 'tool_result') { const c = msg.trace.find((t) => t.id === data.id); if (c) Object.assign(c, data); }
          else if (ev === 'done') msg.meta = data;
          else if (ev === 'error') msg.error = data;
          refresh(msg);
        },
      });
      if (!msg.meta && !msg.error) msg.error = { code: 'incomplete', message: 'The answer stream ended early.' };
    } catch (ex) {
      if (ex.name === 'AbortError') msg.error = { code: 'stopped', message: 'Stopped.' };
      else msg.error = { code: ex.code, message: ex.message };
      if (ex.code === 'invalid_key') { keyStore.forget(); renderKey('The key was rejected; enter it again.'); }
    } finally {
      msg.streaming = false;
      for (const c of msg.trace) if (c.status === 'running') c.status = 'error';
      if (msg.error && !msg.content) msg.content = '';
      setBusy(null);
      refresh(msg);
      save();
      live.textContent = msg.error ? `Error: ${msg.error.message}` : 'Answer complete.';
      ta.focus();
    }
  }

  function ask(text, { send: doSend = false } = {}) {
    open(true);
    if (busy) return;
    ta.value = text;
    updateCount();
    if (doSend && keyStore.get() && modelSel.value) send(text);
    else if (!keyStore.get()) { renderKey('Enter your Claude API key, then press Send.'); setTimeout(() => keyBox.querySelector('input')?.focus(), 50); }
    else ta.focus();
  }

  // mobile: the panel is an overlay
  const toggle = document.getElementById('chat-toggle');
  function open(on) {
    panel.classList.toggle('open', on);
    toggle?.setAttribute('aria-expanded', String(on));
  }
  toggle?.addEventListener('click', () => open(!panel.classList.contains('open')));
  closeBtn.addEventListener('click', () => { open(false); toggle?.focus(); });
  newBtn.addEventListener('click', () => { history = []; save(); renderLog(); ta.focus(); });

  panel.append(head, keyBox, log, live, form);
  renderKey();
  renderLog();
  updateCount();
  return { ask, open, forgetKey: () => { keyStore.forget(); renderKey(); } };
}
