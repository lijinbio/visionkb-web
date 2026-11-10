## Summary

<!-- What does this add or change, and why? -->

## Checklist

- [ ] Routes, SSE events, settings and key handling still match the design (README "Security" section)
- [ ] The Claude key is never logged, stored, echoed or passed to the MCP child (canary-key test passes)
- [ ] No inline scripts/styles, no external assets (CSP `default-src 'self'`)
- [ ] Tests: `uv run pytest`, `npm test`, `npm run lint`; browser test if the page changed (`VISIONKB_BROWSER=1`)
- [ ] Vendored JS updated with `npm run vendor` after a marked/DOMPurify bump
- [ ] Version bumped in `pyproject.toml` and `__init__.py`, and `CHANGELOG.md` updated
- [ ] No personal paths, accounts, hostnames, tokens, keys or lab data
