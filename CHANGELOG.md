# Changelog

## 0.0.4 - 2026-11-11

Chat layout, after user feedback on 0.0.3 (frontend only).

- One **Expand** control: it opens the full page `#/chat`, so the URL, Back and bookmarks work. The separate
  pop-out link and the in-place expanded mode are gone. Modes are docked, full page and collapsed. Leaving `#/chat`
  (the pressed Expand/Dock button, Esc, Back, or an identifier link) returns to the docked layout on the page the
  chat was opened from. A stored `mode: "expanded"` from 0.0.3 migrates to docked. Ctrl/Cmd+J is unchanged
  (collapsed <-> docked; from the full page it collapses and returns).
- Full-page column `clamp(45rem, 60vw, 60rem)` (720-960 px at the browser's default 16 px font; sizes are in units of
  the browser font size, so they follow the user's font size and zoom), centred. Message text on the full page is
  17 px (1.0625 x 16 px) with line-height 1.6; the docked panel text is unchanged. No separate prose cap: paragraphs,
  lists, tables, code and tool traces use the full column, and tables/code/traces scroll horizontally when wider.
- The column is resizable from both edges (symmetric) with the same pointer, keyboard and ARIA rules as the docked
  handle (arrows ±16 px per edge, Shift ±64, Home/End = max/min, Enter or double-click = reset); range 35rem-87.5rem
  (560-1400 px) and at most the viewport − 64 px; persisted as `fullWidth` in `visionkb-web.layout`, separately from the
  docked `width`.
- Docked panel: the maximum is now 55% of the window (was 70%; the page keeps ≥ 480 px, the chat ≥ 360 px); the
  default stays `clamp(400px, 34vw, 640px)`. Stored widths above the current maximum (from 0.0.3) are re-clamped and
  rewritten on load (desktop only).
- The page root font size is `93.75%` instead of a fixed `15px`: identical at default settings, but the site now
  follows the browser's font-size preference.
- Nothing is written to localStorage until the layout is changed.
- Fixed: no amber focus outline on `<main>` after route changes.

## 0.0.3 - 2026-11-11

Chat panel layout (frontend only; the backend is unchanged).

- Default width `clamp(400px, 34vw, 640px)` (was 440 px, 380 px below 1080 px).
- Resizable: drag the panel's left edge (pointer events, rAF-throttled, col-resize cursor, grip on hover/focus);
  bounds chat >= 360 px, page >= 480 px, chat <= 70% of the window, re-clamped on window resize; double-click resets.
  The edge is a focusable `role="separator"` with `aria-valuenow/min/max`: arrow keys +-16 px (Shift +-64), Home/End =
  max/min, Enter resets.
- Modes from the chat header: docked (default), expanded (chat fills the content area, ~80ch column; Esc returns),
  collapsed (a floating *Ask VisionKB* pill at the bottom right, >= 44 px, and an *Ask VisionKB* button in the top
  bar restore it docked; horizontal text only). Ctrl/Cmd+J toggles collapsed/docked (not while typing in other
  fields). Focus moves to the input / the pill / the expand button; mode changes are announced in an aria-live region.
- `#/chat`: the chat as a full page (same tab and history); identifiers clicked in it open their page with the chat
  docked. Linked from the chat header.
- Width and mode persist in `localStorage` (`visionkb-web.layout`, `{width, mode}` only; the Claude key stays in
  sessionStorage, checked by a browser test).
- Answers: tables scroll inside the message, CURIEs and edge ids do not wrap (edge ids shown as
  `visionkb:e-xxxxxxxx…xxxx`, full id in the title and the copied text), tool trace collapsed by default, the input
  grows to about 8 lines.
- Below 900 px: unchanged full-screen slide-over; no resize handle; open/close only (Ctrl/Cmd+J too).
- CSP unchanged: sizes are set through the CSSOM (`style.setProperty('--chat-w', …)`), no style attributes.

## 0.0.2 - 2026-11-10

- The page no longer shows release known issues: no banner, no Known issues section on the Release page, no KI chips
  in atlas, gene-set or evidence tables (user decision). The `/api/kg/release` proxy still passes the API envelope
  unchanged; the web preamble no longer asks the chat to mention known issues.
- Release page: the datasets table pages on with the rows returned (`offset` + rows; the API may trim a page to its
  size cap), so all datasets are reachable.
- Small screens: the top bar keeps **Ask** and **Sign out** visible (release label hidden below 560 px, dot kept).

## 0.0.1 - 2026-11-10

First release.

- FastAPI service: static home page; `/healthz`, `/readyz` (visionkb-api ready and the MCP session with its 8 tools);
  access-code sessions (`/api/session`, HMAC-signed HttpOnly SameSite=Strict cookie, CSRF header); allowlisted
  read-only proxy `/api/kg/*` to visionkb-api with a server-side read token (no `/proposals`).
- Chat: `/api/models` and `/api/chat` (SSE: `text`, `tool_call`, `tool_result`, `done`, `error`) with the user's own
  Claude key (header `X-Anthropic-Key`) through the official `anthropic` SDK; tool-use loop over the `visionkb-kg`
  MCP server 0.0.1 (stdio child via the official `mcp` SDK, clean environment, restarted when it exits); system
  block = web preamble + skill `answer-eye-questions-with-visionkb-kg` (aiscientist-skills v0.2.1); prompt caching on
  the system block and the tool definitions; tool-call cap, history truncation, rate and size limits.
- Key handling: never stored, logged or echoed (redacting log formatter; canary-key test); `ANTHROPIC_*` environment
  variables removed at start.
- Page: search with autocomplete, entity pages (relationships with paging, evidence drawer, atlas expression, gene
  sets, datasets), release page, about page, chat panel (key in sessionStorage,
  first-use notice, model picker, streamed Markdown, tool-call trace, identifier links). Vendored marked 18.2.0 and
  DOMPurify 3.4.17; strict CSP, no inline code, no external assets.
- Image `ghcr.io/lijinbio/visionkb-web` (python 3.13 slim, uid 10001, read-only root friendly) with the MCP
  packages from the commit pinned in `uv.lock` and the skill verified against the release `SHA256SUMS` and a pinned
  digest.
