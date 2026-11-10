"""Allowlisted read-only pass-through to visionkb-api (design §3, contracts §15). GET only; no /proposals."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

FIXED = frozenset({"release", "entities/search", "relationships", "gene-sets", "atlas/expression", "datasets"})
ID_PREFIXES = ("entities/", "evidence/")
# A CURIE or edge id: prefix ':' local id; no '/', '%', '?', '#', whitespace; no '..'
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}:[A-Za-z0-9_.:|\-]{1,200}$")
MAX_QUERY = 4096


def upstream_path(path: str) -> str | None:
    """Map the path after /api/kg/ to the visionkb-api path after /v1, or None when it is not allowed."""
    if path in FIXED:
        return "/" + path
    for prefix in ID_PREFIXES:
        if path.startswith(prefix):
            ident = path[len(prefix) :]
            if ID_RE.match(ident) and ".." not in ident:
                return "/" + prefix + quote(ident, safe=":|")
    return None


def envelope_error(code: str, message: str, kg_release: str | None = None) -> bytes:
    return json.dumps(
        {
            "status": "error",
            "kg_release": kg_release,
            "data": None,
            "page": None,
            "warnings": [],
            "error": {"code": code, "message": message},
        }
    ).encode()
