#!/usr/bin/env bash
# Fail if a tracked file mentions a private path, user, account or node name, or holds a Claude key (public repo).
# Extra patterns can be added locally with VISIONKB_HYGIENE_EXTRA='pat1|pat2' (never commit them).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# Patterns are split so this file does not match itself.
pat='df''s3b|ruic''20|jinl''14|homez''vol|hpc3''-[0-9]|mrr''dir'
[[ -n "${VISIONKB_HYGIENE_EXTRA:-}" ]] && pat="$pat|$VISIONKB_HYGIENE_EXTRA"
bad=0
if git grep -nIiE "$pat" -- . ':!uv.lock' ':!package-lock.json'; then bad=1; fi
# A real-looking key (sk-ant-api03- plus 40+ key characters) anywhere outside the tests' synthetic canaries.
if git grep -nIE 'sk-''ant-[a-z0-9]+-[A-Za-z0-9_-]{40,}' -- . ':!tests/'; then bad=1; fi
if [[ $bad -ne 0 ]]; then
  echo "hygiene-check: remove the matches above (use /path/to/..., <partition>, <account>)" >&2
  exit 1
fi
echo "hygiene-check: ok"
