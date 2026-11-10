# Changelog

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
