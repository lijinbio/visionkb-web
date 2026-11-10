// Calls to this server only (same origin, relative URLs so a URL prefix works). The Claude key lives in
// sessionStorage of this tab (never localStorage, cookies or URLs) and goes out only in the X-Anthropic-Key header.

const KEY = 'vkw.anthropic_key';
const HDR = { 'X-VisionKB-Web': '1' };

export class ApiError extends Error {
  constructor(code, message, status) { super(message); this.code = code; this.status = status; }
}

function emitUnauthorized() { window.dispatchEvent(new CustomEvent('vkw:unauthorized')); }

async function json(resp) {
  let body = null;
  try { body = await resp.json(); } catch { /* not JSON */ }
  return body;
}

export const keyStore = {
  get: () => sessionStorage.getItem(KEY) || '',
  set: (k) => sessionStorage.setItem(KEY, k),
  forget: () => sessionStorage.removeItem(KEY),
};

export async function session() {
  const r = await fetch('api/session', { credentials: 'same-origin' });
  return json(r);
}

export async function login(code) {
  const r = await fetch('api/session', { method: 'POST', credentials: 'same-origin', headers: { ...HDR, 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
  const body = await json(r);
  if (!r.ok) throw new ApiError(body?.error?.code || 'error', body?.error?.message || `HTTP ${r.status}`, r.status);
  return body;
}

export async function logout() {
  await fetch('api/session', { method: 'DELETE', credentials: 'same-origin', headers: HDR });
}

// GET /api/kg/<path>; resolves to the API envelope (also for API errors), throws on transport errors.
export async function kg(path, params = {}, { signal } = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    for (const item of Array.isArray(v) ? v : [v]) qs.append(k, String(item));
  }
  const url = `api/kg/${path}${qs.toString() ? `?${qs}` : ''}`;
  const r = await fetch(url, { credentials: 'same-origin', signal });
  const body = await json(r);
  if (r.status === 401 && body?.error?.code === 'unauthorized') emitUnauthorized();
  if (!body) throw new ApiError('bad_response', `HTTP ${r.status}`, r.status);
  return body;
}

export async function ok(path, params, opts) {
  const env = await kg(path, params, opts);
  if (env.status !== 'ok') throw new ApiError(env.error?.code || 'error', env.error?.message || 'request failed', 0);
  return env;
}

export async function readyz() {
  const r = await fetch('readyz');
  return { status: r.status, body: await json(r) };
}

export async function models(key) {
  const r = await fetch('api/models', { credentials: 'same-origin', headers: { 'X-Anthropic-Key': key } });
  const body = await json(r);
  if (r.status === 401 && body?.error?.code === 'unauthorized') emitUnauthorized();
  if (!r.ok) throw new ApiError(body?.error?.code || 'error', body?.error?.message || `HTTP ${r.status}`, r.status);
  return body;
}

// POST /api/chat; calls onEvent(name, data) for each SSE event. Resolves when the stream ends.
export async function chat({ key, model, messages, signal, onEvent }) {
  const r = await fetch('api/chat', {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { ...HDR, 'Content-Type': 'application/json', 'X-Anthropic-Key': key },
    body: JSON.stringify({ model, messages }),
  });
  if (!r.ok || !(r.headers.get('content-type') || '').startsWith('text/event-stream')) {
    const body = await json(r);
    if (r.status === 401 && body?.error?.code === 'unauthorized') emitUnauthorized();
    throw new ApiError(body?.error?.code || 'error', body?.error?.message || `HTTP ${r.status}`, r.status);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const data = [];
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim();
        else if (line.startsWith('data: ')) data.push(line.slice(6));
      }
      if (!data.length) continue;
      let parsed;
      try { parsed = JSON.parse(data.join('\n')); } catch { continue; }
      onEvent(event, parsed);
    }
  }
}
