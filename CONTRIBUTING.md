# Contributing

## Setup

```bash
git clone https://github.com/lijinbio/visionkb-web.git && cd visionkb-web
uv sync && uv run pytest              # Python >= 3.12
npm ci && npm test && npm run lint    # Node >= 22: ESLint, jsdom tests, the vendored-file check
pre-commit install                    # optional
```

## Checks (all run in CI)

| Check | Command |
|---|---|
| Python | `uv run ruff check . && uv run ruff format --check .` |
| Unit tests | `uv run pytest -rs` |
| JavaScript | `npm run lint && npm test && npm run vendor:check` |
| Browser | `uv run playwright install chromium-headless-shell && VISIONKB_BROWSER=1 uv run pytest tests/test_browser.py` |
| Hygiene | `scripts/hygiene-check.sh` |
| Image | `docker build -t visionkb-web:dev .` and the smoke test in `.github/workflows/ci.yml` |

## Conventions

| Topic | Rule |
|---|---|
| Frontend | vanilla ES modules, no build step, no CDN, no inline scripts or styles (CSP); text via `textContent`; model output only through `render.js` |
| Vendored JS | bump `marked` / `dompurify` in `package.json`, `npm install`, `npm run vendor`, commit the copies |
| Claude key | header only; never in logs, errors, storage, the MCP child or tests' recorded bodies |
| Secrets | files only (`*_FILE`); examples use `CHANGE_ME` |
| Hygiene | no personal or cluster paths, accounts, hostnames, tokens, keys or lab data |

## Releasing

Bump the version in `pyproject.toml` and `src/visionkb_web/__init__.py`, add a CHANGELOG entry, wait for CI to pass
on `main`, then tag `vX.Y.Z` and push the tag. The Release workflow checks the versions, runs the tests, pushes
`ghcr.io/lijinbio/visionkb-web:X.Y.Z` and publishes a GitHub release with the image digest.
