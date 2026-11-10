# visionkb-web

[![CI](https://github.com/lijinbio/visionkb-web/actions/workflows/ci.yml/badge.svg)](https://github.com/lijinbio/visionkb-web/actions/workflows/ci.yml)

Home page for the **VisionKB** knowledge graph of the eye: search, entity pages (genes, retinal and ocular cell types
and states, diseases, phenotypes, anatomy) with relationships, evidence and HECA atlas expression, the release page
(counts, edge rule, sources, datasets), and a **chat box that answers with your own Claude API key** by calling the read-only
VisionKB MCP tools.

- One small FastAPI service (one port) serving a static page (vanilla JavaScript modules, no build step, no CDN).
- `/api/kg/*`: an allowlisted, read-only proxy to [visionkb-api](https://github.com/lijinbio/visionkb-api) with a
  server-side read token (the browser never sees it; no `/proposals`).
- `/api/chat`: the Anthropic Messages API tool-use loop, streamed as server-sent events, with the eight tools of the
  `visionkb-kg` MCP server ([aiscientist-mcp](https://github.com/lijinbio/aiscientist-mcp) tag `visionkb-kg-v0.0.1`,
  a long-lived stdio child) and the AiScientist skill
  [answer-eye-questions-with-visionkb-kg](https://github.com/lijinbio/aiscientist-skills) (release v0.2.1, verified
  against the release `SHA256SUMS` at image build) as instructions.
- No database and no server-side conversation state; chat history lives in the browser tab.

## User guide

### 1. Open the page

Open the address your deployment gives you (for example `http://127.0.0.1:18922/` through an SSH tunnel to a cluster
node, or the site's HTTPS address behind an ingress). The badge at the top right shows the knowledge-graph release
served (for example `visionkb-2026.11.0`) with a green dot when the API and the tools are ready.

### 2. Enter the access code

The site serves lab-access data, so it asks for an access code first (one per line in the deployment's
`web_access_codes` file; `visionkb init` in [visionkb-deploy](https://github.com/lijinbio/visionkb-deploy) creates
it). The session lasts 12 hours; **Sign out** ends it. Search and entity pages work without a Claude key.

### 3. Enter your Claude API key (for the chat only)

1. Create a key at [console.anthropic.com](https://console.anthropic.com/settings/keys) (a key with a spend limit is
   a good idea).
2. Paste it into **Your Claude API key** in the chat panel (on a phone: tap **Ask**) and press **Use key**.
3. Read and acknowledge the notice: your questions and the tool results are sent to Anthropic under your account.
4. Pick a model; the list comes from your key (`/api/models`). The default is a Sonnet model when your key lists
   one (or the deployment's `VISIONKB_WEB_DEFAULT_MODEL`).

The key stays in this tab's `sessionStorage`: closing the tab or pressing **Forget key** removes it.

### 4. Ask

Type a question and press Enter (Shift+Enter for a new line), or click an example on the home page:

- Which retinal cell types express RHO, and what is the evidence?
- What genes are most specific to retinal rod cells (CL:0000604)?
- Is PRPF31 linked to retinitis pigmentosa in VisionKB?
- Which HECA datasets cover the RPE?
- Which major retinal class shows the highest LRAT expression?

The answer streams in with a collapsible **tool-call trace** (tool, arguments, rows returned, `kg_release`). Every
claim should cite the release and an `edge_id` or dataset: CURIEs such as `HGNC:10012` open entity pages and
`visionkb:e-…` edge ids open the evidence drawer (StudyResults with dataset, group, cells, % expressing, pseudobulk
CP10k, donors; publications). The assistant says so when the graph cannot answer. Check the evidence before relying on
an answer.

### What is sent to Anthropic, and what is not

| Sent to Anthropic (your account) | Not sent |
|---|---|
| your questions and this tab's chat history (text) | the VisionKB API token |
| tool results: VisionKB facts and HECA atlas summary values (HECA `access_level = lab`) | the access code, cookies |
| fixed instructions: a short web preamble and the skill `SKILL.md` | other users' chats; anything from other tabs |

Use the chat only if you may share lab-access summaries with Anthropic under your account's terms.

## Run it

### Container (Docker or Apptainer)

```bash
docker run --rm -p 8780:8780 --read-only --tmpfs /tmp -v /path/to/secrets:/run/secrets:ro \
  -e VISIONKB_API_URL=http://visionkb-api:8770/v1 \
  -e VISIONKB_API_TOKEN_FILE=/run/secrets/api_token_read \
  -e VISIONKB_WEB_SECRET_FILE=/run/secrets/web_secret \
  -e VISIONKB_WEB_ACCESS_CODES_FILE=/run/secrets/web_access_codes \
  ghcr.io/lijinbio/visionkb-web:0.0.2

apptainer pull visionkb-web_0.0.2.sif docker://ghcr.io/lijinbio/visionkb-web:0.0.2
apptainer run --cleanenv --env VISIONKB_WEB_HOST=127.0.0.1,VISIONKB_WEB_PORT=18922,... visionkb-web_0.0.2.sif
```

Use the image by digest in deployments (see the GitHub release notes). [visionkb-deploy](https://github.com/lijinbio/visionkb-deploy)
runs it as the `web` service next to the API (Apptainer on a cluster node, docker compose, Kubernetes).

Secrets: `web_secret` (cookie signing key, e.g. `openssl rand -hex 32`) and `web_access_codes` (one code per line,
at least 16 characters, e.g. `openssl rand -base64 24`), mode 600, readable by the container user (uid 10001).

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `VISIONKB_API_URL` | required | visionkb-api base URL (`…/v1`) |
| `VISIONKB_API_TOKEN_FILE` | required | read-scope API token (also given to the MCP child) |
| `VISIONKB_TIMEOUT_S` | `30` | seconds per API request (proxy and MCP child) |
| `VISIONKB_WEB_HOST` / `VISIONKB_WEB_PORT` | `127.0.0.1` / `8780` (image: `0.0.0.0`) | bind address |
| `VISIONKB_WEB_ROOT_PATH` | empty | URL prefix behind an ingress |
| `VISIONKB_WEB_SECRET_FILE` | required unless public | cookie signing key |
| `VISIONKB_WEB_ACCESS_CODES_FILE` | required unless public | access codes |
| `VISIONKB_WEB_PUBLIC` | `0` | `1` = no access codes (only for public-data deployments) |
| `VISIONKB_WEB_SKILL_DIR` | `/opt/visionkb-web/skill` | folder with the skill's `SKILL.md` |
| `VISIONKB_WEB_MCP_COMMAND` | `visionkb-kg-mcp` | MCP server command (stdio) |
| `VISIONKB_WEB_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | tests point this at a mock |
| `VISIONKB_WEB_DEFAULT_MODEL` | empty | preselected if the key lists it; else the first id containing `sonnet`; else the first |
| `VISIONKB_WEB_MAX_TOOL_CALLS` / `_MAX_OUTPUT_TOKENS` / `_MAX_HISTORY_CHARS` | `16` / `4096` / `60000` | chat limits |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | proxies trusted for `X-Forwarded-*` (uvicorn) |

There is no server-side Claude key: `ANTHROPIC_*` variables are removed at start and logged by name only.

### From source

```bash
git clone https://github.com/lijinbio/visionkb-web.git && cd visionkb-web
uv sync                                   # Python >= 3.12; installs the MCP server from the pinned commit
uv run python scripts/fetch_skill.py --version 0.2.1 \
  --zip-sha256 0a47d095def794c1e80d8b3d3a1d9ec269d901de029ae9d6b99ad5e45fa9c7d2 --out ./skill
export VISIONKB_WEB_SKILL_DIR=$PWD/skill VISIONKB_API_URL=http://127.0.0.1:8770/v1 VISIONKB_API_TOKEN_FILE=...
uv run visionkb-web check                 # settings, skill and the 8 MCP tools
uv run visionkb-web serve
```

## HTTP interface

| Route | Method | Notes |
|---|---|---|
| `/`, `/static/*` | GET | page and assets |
| `/healthz` | GET | process alive |
| `/readyz` | GET | 200 when visionkb-api `/v1/ready` is 200 and the MCP session lists the 8 tools; 503 otherwise |
| `/api/session` | GET / POST / DELETE | status (version, limits) / access-code login (signed HttpOnly SameSite=Strict cookie) / logout |
| `/api/kg/{release, entities/search, entities/<curie>, relationships, evidence/<edge_id>, gene-sets, atlas/expression, datasets}` | GET | pass-through to visionkb-api `/v1/…` with the read token; query parameters forwarded; the API envelope unchanged |
| `/api/models` | GET | header `X-Anthropic-Key`; `{data: [{id, display_name, created_at}], default_model}`; errors `invalid_key`, `upstream_error` |
| `/api/chat` | POST | header `X-Anthropic-Key`; body `{model, messages: [{role, content}]}`; `text/event-stream` |

SSE events of `/api/chat`: `text {delta}` · `tool_call {id, name, input}` · `tool_result {id, name, status,
kg_release, returned, total, error_code, warnings}` · `done {stop_reason, usage, tool_calls, rounds, model,
kg_releases, history_dropped, elapsed_s}` · `error {code, message}`. Every non-GET request needs the header
`X-VisionKB-Web: 1`.

## Security

- **Claude key**: browser `sessionStorage` only; sent in the `X-Anthropic-Key` header to this server and used for that
  one upstream call. Never stored, cached, logged, put in metrics, passed to the MCP child or echoed in errors: every
  log line goes through a formatter that redacts `sk-ant-…` patterns and the key of the request being served;
  request headers are never logged. A canary-key test checks logs (at DEBUG), responses and app state.
- **Access**: access codes → HMAC-signed HttpOnly, SameSite=Strict cookie (`Secure` over HTTPS), TTL 12 h; login
  attempts rate-limited; CSRF header on non-GET requests.
- **Headers**: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, `nosniff`, `no-referrer`, HSTS over
  HTTPS. No inline scripts or styles, no external assets.
- **Model output**: Markdown via marked with raw HTML escaped, then DOMPurify with a tag allowlist; links only to
  `#/…` routes and `http(s)`.
- **Limits**: one chat at a time and 20 chats / 10 min per session; message ≤ 8,000 characters; request body
  ≤ 256 KB; proxy 120 requests / min per session; ≤ 16 tool calls per answer, then an answer without tools; history
  truncated to 60,000 characters (oldest turns first).

See [SECURITY.md](SECURITY.md) for reporting.

## Tests

| Suite | Command | What |
|---|---|---|
| Unit | `uv run pytest` | allowlist (no `/proposals`, GET only), envelope pass-through, access codes + CSRF, CSP and headers, limits, `/readyz`, MCP child restart and clean environment, models default rule, SSE sequence of a two-tool conversation and the tool-call cap against a mock Anthropic server, history truncation, canary key never in logs or responses; the real `visionkb-kg-mcp` runs against a fake API |
| JavaScript | `npm ci && npm test && npm run lint` | DOMPurify/marked on a hostile answer (jsdom), identifier links; ESLint |
| Browser | `VISIONKB_BROWSER=1 uv run pytest tests/test_browser.py` | Chromium: gate, search, entity page, evidence drawer, chat with notice and tool trace, hostile answer inert, no CSP violations, mobile layout |
| Integration | `VISIONKB_IT_WEB_URL=… uv run pytest tests/integration` | a running instance against a real API (see the test's docstring) |
| Container | CI job `container` | image smoke test with the fake API and the mock provider |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). The vendored [marked](https://github.com/markedjs/marked) (MIT) and
[DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0 or MPL-2.0) builds are pinned in `package-lock.json`;
their licenses are in `src/visionkb_web/static/vendor-licenses/`.

## License

MIT, see [LICENSE](LICENSE).
