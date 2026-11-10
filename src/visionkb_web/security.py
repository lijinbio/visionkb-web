"""Access codes, signed session cookies, CSRF header, security headers, body cap and rate limits (design §5)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque

COOKIE = "vkw_session"
CSRF_HEADER = "x-visionkb-web"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "cross-origin-opener-policy": "same-origin",
}
HSTS = "max-age=31536000"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionSigner:
    """``<payload>.<hmac>`` with payload ``{"sid", "exp"}``; HMAC-SHA256 with a key derived from the secret file."""

    def __init__(self, secret: str, ttl_s: int):
        self._key = hashlib.sha256(b"visionkb-web session v1\0" + secret.encode()).digest()
        self.ttl_s = ttl_s

    def issue(self, now: float | None = None) -> tuple[str, str]:
        sid = secrets.token_urlsafe(18)
        exp = int((now or time.time()) + self.ttl_s)
        payload = _b64(json.dumps({"sid": sid, "exp": exp}, separators=(",", ":")).encode())
        return sid, payload + "." + _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def verify(self, token: str | None, now: float | None = None) -> str | None:
        if not token or token.count(".") != 1 or len(token) > 512:
            return None
        payload, sig = token.split(".")
        want = _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        try:
            body = json.loads(_unb64(payload))
        except ValueError:
            return None
        if not isinstance(body, dict) or int(body.get("exp", 0)) < (now or time.time()):
            return None
        sid = body.get("sid")
        return sid if isinstance(sid, str) else None


def code_matches(code: str, codes: list[str]) -> bool:
    """Constant-time comparison against every configured code (no early exit)."""
    given = hashlib.sha256(code.encode()).digest()
    ok = False
    for c in codes:
        ok |= hmac.compare_digest(given, hashlib.sha256(c.encode()).digest())
    return ok


class RateLimiter:
    """Sliding-window counter per key (in memory, one process)."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and q[0] <= now - self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > 50_000:  # bound memory: drop idle keys
            for k in [k for k, v in self._hits.items() if not v]:
                del self._hits[k]
        return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        q = self._hits.get(key)
        return max(1, int(q[0] + self.window_s - now) + 1) if q else 1


class ActiveChats:
    """At most one running chat per session; entries older than ``stale_s`` are ignored (lost disconnects)."""

    def __init__(self, stale_s: float = 900):
        self.stale_s = stale_s
        self._active: dict[str, float] = {}

    def acquire(self, sid: str) -> bool:
        now = time.monotonic()
        started = self._active.get(sid)
        if started is not None and now - started < self.stale_s:
            return False
        self._active[sid] = now
        return True

    def release(self, sid: str) -> None:
        self._active.pop(sid, None)
