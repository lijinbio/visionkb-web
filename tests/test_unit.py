import io
import json
import logging
import os
import time
from pathlib import Path

import pytest

from tests.conftest import ACCESS_CODE, CANARY_KEY, CSRF, login, make_client
from tests.fake_api import EDGE, RELEASE
from visionkb_web.chat import ChatInputError, choose_default, load_skill, parse_chat_body, truncate_history
from visionkb_web.logs import log_config, redact
from visionkb_web.mcp_tools import EXPECTED_TOOLS
from visionkb_web.proxy import upstream_path
from visionkb_web.security import CSP, SessionSigner

KEY = {"X-Anthropic-Key": CANARY_KEY}


def sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.strip().splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def chat(client, model="claude-sonnet-mock-1", messages=None, headers=None):
    body = {"model": model, "messages": messages or [{"role": "user", "content": "Which cell types express RHO?"}]}
    r = client.post("/api/chat", json=body, headers={**CSRF, **KEY, **(headers or {})})
    return r, (sse(r.text) if r.headers.get("content-type", "").startswith("text/event-stream") else [])


# ---- allowlist ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path,want", [
    ("release", "/release"), ("entities/search", "/entities/search"), ("entities/HGNC:10012", "/entities/HGNC:10012"),
    ("relationships", "/relationships"), ("evidence/" + EDGE, "/evidence/" + EDGE), ("gene-sets", "/gene-sets"),
    ("atlas/expression", "/atlas/expression"), ("datasets", "/datasets"),
    ("proposals", None), ("proposals/x", None), ("health", None), ("ready", None), ("", None), ("entities", None),
    ("entities/../proposals", None), ("entities/HGNC:1/../../proposals", None), ("evidence/a/b", None),
    ("entities/HGNC:1%2F..", None), ("release/", None), ("atlas", None), ("entities/search/x", None),
    ("entities/javascript:alert(1)", None), ("evidence/x:y?z", None),
])  # fmt: skip
def test_upstream_path_allowlist(path, want):
    assert upstream_path(path) == want


def test_proxy_passthrough_envelope_unchanged(client, fake_api):
    r = client.get("/api/kg/entities/search?q=RHO&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert body["kg_release"] == RELEASE and body["data"][0]["id"] == "HGNC:10012"
    assert set(body) == {"status", "kg_release", "data", "page", "warnings", "error"}
    hit = [h for h in fake_api.hits if h["path"] == "/v1/entities/search"][-1]
    assert hit["auth_ok"] and hit["query"] == "q=RHO&limit=3"
    # API errors pass through with their status and envelope
    r = client.get("/api/kg/relationships")
    assert r.status_code == 400 and r.json()["error"]["code"] == "missing_anchor"
    r = client.get("/api/kg/entities/HGNC:99999999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.get("/api/kg/evidence/" + EDGE)
    assert r.status_code == 200 and r.json()["data"]["study_results"][0]["group_label"] == "Rod"


def test_proxy_rejects_other_paths_and_methods(client, fake_api):
    n = len(fake_api.hits)
    for p in (
        "proposals",
        "proposals?status=proposed",
        "health",
        "entities/..%2Fproposals",
        "entities/%2E%2E/proposals",
        "x",
    ):
        r = client.get("/api/kg/" + p)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_allowed", p
    for m in ("post", "put", "patch", "delete"):
        r = (
            getattr(client, m)("/api/kg/release", headers=CSRF)
            if m != "post"
            else client.post("/api/kg/proposals", json={}, headers=CSRF)
        )
        assert r.status_code == 405 and r.headers["allow"] == "GET", m
    assert len(fake_api.hits) == n  # nothing reached the API
    assert not [h for h in fake_api.hits if "proposals" in h["path"]]


# ---- access codes, CSRF, headers, limits ----------------------------------------------------------------------
def test_access_code_login_and_csrf(base_settings):
    with make_client(base_settings) as c:
        assert c.get("/api/session").json()["authenticated"] is False
        assert c.get("/api/kg/release").status_code == 401
        assert c.get("/api/models", headers=KEY).status_code == 401
        assert c.post("/api/chat", json={}, headers={**CSRF, **KEY}).status_code == 401
        r = c.post("/api/session", json={"code": ACCESS_CODE})  # no CSRF header
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
        r = c.post("/api/session", json={"code": "wrong-code-0000000000"}, headers=CSRF)
        assert r.status_code == 401 and "set-cookie" not in r.headers
        r = c.post("/api/session", json={"code": ACCESS_CODE}, headers=CSRF)
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie and "secure" not in cookie
        assert c.get("/api/kg/release").status_code == 200
        # tampered cookie
        good = c.cookies.get("vkw_session")
        payload, sig = good.split(".")
        for bad in (payload + "." + sig[::-1], payload[:-2] + "xx." + sig, "garbage", ""):
            c.cookies.clear()
            c.cookies.set("vkw_session", bad)
            assert c.get("/api/kg/release").status_code == 401, bad
        c.cookies.clear()
        c.cookies.set("vkw_session", good)
        assert c.get("/api/kg/release").status_code == 200
        assert c.delete("/api/session").status_code == 403  # CSRF header required for DELETE too
        r = c.delete("/api/session", headers=CSRF)
        assert r.status_code == 200 and "vkw_session=" in r.headers["set-cookie"]
        c.cookies.clear()
        assert c.get("/api/kg/release").status_code == 401


def test_session_expiry():
    s = SessionSigner("secret", ttl_s=10)
    sid, tok = s.issue(now=1000)
    assert s.verify(tok, now=1005) == sid and s.verify(tok, now=1011) is None
    assert SessionSigner("other", 10).verify(tok, now=1005) is None


def test_public_mode(base_settings):
    with make_client(base_settings, public=True, secret_file=None, access_codes_file=None) as c:
        assert c.get("/api/session").json()["public"] is True and c.get("/api/kg/release").status_code == 200


def test_security_headers(client):
    for path in ("/", "/healthz", "/api/session", "/static/js/app.js", "/api/kg/release"):
        r = client.get(path)
        assert r.headers["content-security-policy"] == CSP, path
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
        assert "strict-transport-security" not in r.headers
    assert CSP == ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                   "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")  # fmt: skip
    assert client.get("/api/kg/release").headers["cache-control"] == "no-store"
    r = client.get("/healthz", headers={"x-forwarded-proto": "https"})
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_page_has_no_external_or_inline_code(client):
    html = client.get("/").text
    assert "<script" in html and 'type="module"' in html
    import re

    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline script"
    assert not re.search(r"\sstyle=|<style", html), "inline style"
    assert not re.search(r"src=\"(https?:)?//|<link[^>]+href=\"(https?:)?//", html), "external asset"
    static = Path(__file__).parents[1] / "src" / "visionkb_web" / "static"
    for f in static.rglob("*.js"):
        if "vendor" in f.parts:
            continue
        text = f.read_text()
        assert "localStorage" not in text or "never" in text, f  # the key is never put in localStorage
        assert not re.search(
            r"https?://(?!www\.|pubmed|purl|genenames|identifiers|ebi|ncbi|omim|uniprot|ensembl|github|platform\.claude|console\.anthropic|docs\.anthropic)",
            text,
        ), f


def test_body_cap_and_message_length(client):
    r = client.post(
        "/api/chat", content=b"x" * (300 * 1024), headers={**CSRF, **KEY, "content-type": "application/json"}
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "body_too_large"
    r, _ = chat(client, messages=[{"role": "user", "content": "x" * 8001}])
    assert r.status_code == 413 and r.json()["error"]["code"] == "message_too_long"
    r = client.post("/api/chat", content=b"not json", headers={**CSRF, **KEY})
    assert r.status_code == 400


def test_chat_rate_limit_and_concurrency(base_settings):
    with make_client(base_settings, chat_per_window=2) as c:
        login(c)
        assert chat(c)[0].status_code == 200 and chat(c)[0].status_code == 200
        r, _ = chat(c)
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and "retry-after" in r.headers
    from visionkb_web.security import ActiveChats

    a = ActiveChats()
    assert a.acquire("s") and not a.acquire("s")
    a.release("s")
    assert a.acquire("s")


def test_proxy_rate_limit(base_settings):
    with make_client(base_settings, proxy_per_minute=3) as c:
        login(c)
        codes = [c.get("/api/kg/release").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]


# ---- health ---------------------------------------------------------------------------------------------------
def test_healthz_readyz(client):
    assert client.get("/healthz").json()["status"] == "ok"
    r = client.get("/readyz")
    body = r.json()
    assert r.status_code == 200, body
    assert body["mcp"]["n_tools"] == 8 and set(body["mcp"]["tools"]) == EXPECTED_TOOLS and body["kg_release"] == RELEASE


def test_readyz_503_when_api_down(base_settings):
    with make_client(base_settings, api_url="http://127.0.0.1:9/v1") as c:
        r = c.get("/readyz")
        assert r.status_code == 503 and r.json()["api"]["status"] == "error"


def _children(pattern):
    me = str(os.getpid())
    out = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                stat = (p / "stat").read_text().rsplit(")", 1)[1].split()
                cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            except OSError:
                continue
            if stat[1] == me and pattern in cmd:
                out.append(int(p.name))
    return out


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs /proc")
def test_mcp_child_restarts_and_has_clean_env(base_settings):
    import signal

    with make_client(base_settings) as c:
        tools = c.app.state.tools
        assert tools.ready
        assert set(tools.env) == {"VISIONKB_API_URL", "VISIONKB_API_TOKEN_FILE", "VISIONKB_TIMEOUT_S"}
        pids = _children("visionkb-kg-mcp")
        assert pids, "MCP child not found"
        environ = (Path("/proc") / str(pids[0]) / "environ").read_bytes().split(b"\0")
        names = {e.split(b"=", 1)[0].decode() for e in environ if e}
        assert not {n for n in names if n.startswith("ANTHROPIC")} and "VISIONKB_WEB_SECRET_FILE" not in names
        assert names <= {
            "VISIONKB_API_URL",
            "VISIONKB_API_TOKEN_FILE",
            "VISIONKB_TIMEOUT_S",
            "HOME",
            "LOGNAME",
            "PATH",
            "SHELL",
            "TERM",
            "USER",
        }
        for pid in pids:
            os.kill(pid, signal.SIGKILL)
        t0 = time.time()
        while time.time() - t0 < 30 and not (tools.restarts >= 1 and tools.ready):
            time.sleep(0.2)
            c.get("/healthz")
        assert tools.restarts >= 1 and tools.ready and c.get("/readyz").status_code == 200


def test_env_scrub(base_settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    with make_client(base_settings):
        assert "ANTHROPIC_API_KEY" not in os.environ and "ANTHROPIC_BASE_URL" not in os.environ


# ---- models ---------------------------------------------------------------------------------------------------
def test_models(client):
    r = client.get("/api/models", headers=KEY)
    body = r.json()
    assert r.status_code == 200, body
    assert [m["id"] for m in body["data"]][:2] == ["claude-haiku-mock-1", "claude-sonnet-mock-1"]
    assert set(body["data"][0]) == {"id", "display_name", "created_at"}
    assert body["default_model"] == "claude-sonnet-mock-1"
    r = client.get("/api/models", headers={"X-Anthropic-Key": "sk-ant-api03-wrongwrongwrongwrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_key"
    assert client.get("/api/models").status_code == 401
    assert client.get("/api/models", headers={"X-Anthropic-Key": "short"}).json()["error"]["code"] == "invalid_key"


def test_models_unreachable(base_settings):
    with make_client(base_settings, anthropic_base_url="http://127.0.0.1:9") as c:
        login(c)
        r = c.get("/api/models", headers=KEY)
        assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"


def test_choose_default():
    ids = ["claude-opus-x", "claude-sonnet-y", "claude-haiku-z"]
    assert choose_default(ids, "claude-haiku-z") == "claude-haiku-z"
    assert choose_default(ids, "not-listed") == "claude-sonnet-y"
    assert choose_default(["a", "b"], "") == "a" and choose_default([], "") is None


# ---- chat -----------------------------------------------------------------------------------------------------
def test_chat_two_tool_sse_sequence(client, mock_anthropic):
    start = len(mock_anthropic.mock.requests)
    r, events = chat(client)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    kinds = [e for e, _ in events]
    compact = [k for i, k in enumerate(kinds) if i == 0 or k != kinds[i - 1]]
    assert compact == ["text", "tool_call", "tool_result", "tool_call", "tool_result", "text", "done"], compact
    calls = [d for e, d in events if e == "tool_call"]
    results = [d for e, d in events if e == "tool_result"]
    assert [c["name"] for c in calls] == ["search_entities", "get_relationships"]
    assert calls[1]["input"]["subject"] == "HGNC:10012"
    assert all(r_["status"] == "ok" and r_["kg_release"] == RELEASE for r_ in results)
    assert results[0]["returned"] == 1 and results[0]["id"] == calls[0]["id"]
    answer = "".join(d["delta"] for e, d in events if e == "text")
    assert EDGE in answer and RELEASE in answer
    done = events[-1][1]
    assert done["tool_calls"] == 2 and done["stop_reason"] == "end_turn" and done["kg_releases"] == [RELEASE]
    assert done["usage"]["output_tokens"] == 3 * 42 and done["usage"]["cache_creation_input_tokens"] > 0
    reqs = mock_anthropic.mock.requests[start:]
    assert len(reqs) == 3 and all(q["key_ok"] for q in reqs)
    first = reqs[0]["body"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Only the VisionKB MCP tools" in first["system"][0]["text"] and "test stand-in" in first["system"][0]["text"]
    assert {t["name"] for t in first["tools"]} == EXPECTED_TOOLS
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in t for t in first["tools"][:-1])
    assert first["stream"] is True and "tool_choice" not in first
    # tool results are passed back verbatim (the MCP JSON text)
    last = reqs[-1]["body"]["messages"]
    tr = [b for m in last if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]]
    parsed = json.loads(tr[0]["content"])
    assert parsed["kg_release"] == RELEASE and "paging" in parsed and parsed["request"]["path"] == "/v1/entities/search"


def test_chat_parallel_tool_uses(client):
    _r, events = chat(client, model="mock-parallel")
    assert [d["name"] for e, d in events if e == "tool_call"] == ["search_entities", "get_release"]
    assert events[-1][0] == "done" and events[-1][1]["tool_calls"] == 2


def test_tool_call_cap(base_settings, mock_anthropic):
    with make_client(base_settings, max_tool_calls=3) as c:
        login(c)
        start = len(mock_anthropic.mock.requests)
        _r, events = chat(c, model="mock-loop")
        assert [e for e, _ in events].count("tool_call") == 3
        assert events[-1][0] == "done" and events[-1][1]["tool_calls"] == 3
        reqs = mock_anthropic.mock.requests[start:]
        assert reqs[-1]["body"]["tool_choice"] == {"type": "none"} and "tools" in reqs[-1]["body"]
        assert all("tool_choice" not in q["body"] for q in reqs[:-1])
        note = reqs[-1]["body"]["messages"][-1]["content"][-1]
        assert note["type"] == "text" and "limit (3)" in note["text"]


def test_history_truncation(base_settings, mock_anthropic):
    msgs = [{"role": "user", "content": "q1 " + "a" * 5000}, {"role": "assistant", "content": "b" * 5000},
            {"role": "user", "content": "q2"}, {"role": "assistant", "content": "c" * 100}, {"role": "user", "content": "q3"}]  # fmt: skip
    kept, dropped = truncate_history(msgs, 6000)
    assert dropped == 2 and kept[0]["content"] == "q2" and kept[-1]["content"] == "q3"
    kept, dropped = truncate_history(msgs, 5150)
    assert kept[0]["role"] == "user" and kept[-1]["content"] == "q3"
    assert truncate_history([{"role": "user", "content": "x" * 9000}], 8000) == (
        [{"role": "user", "content": "x" * 9000}],
        0,
    )
    with make_client(base_settings, max_history_chars=8000) as c:
        login(c)
        start = len(mock_anthropic.mock.requests)
        long = [{"role": "user", "content": "old " + "z" * 7000}, {"role": "assistant", "content": "y" * 7000},
                {"role": "user", "content": "Which cell types express RHO?"}]  # fmt: skip
        _r, events = chat(c, messages=long)
        assert events[-1][1]["history_dropped"] == 2
        sent = mock_anthropic.mock.requests[start]["body"]["messages"]
        assert sent == [{"role": "user", "content": "Which cell types express RHO?"}]


def test_chat_input_validation():
    with pytest.raises(ChatInputError):
        parse_chat_body({"model": "m", "messages": [{"role": "assistant", "content": "x"}]}, 8000)
    with pytest.raises(ChatInputError):
        parse_chat_body({"model": "bad model id!", "messages": [{"role": "user", "content": "x"}]}, 8000)
    with pytest.raises(ChatInputError):
        parse_chat_body({"model": "m", "messages": [{"role": "system", "content": "x"}]}, 8000)
    with pytest.raises(ChatInputError):
        parse_chat_body({"model": "m", "messages": [{"role": "user", "content": [{"type": "image"}]}]}, 8000)


def test_chat_upstream_errors(client):
    r, events = chat(client, headers={"X-Anthropic-Key": "sk-ant-api03-wrongwrongwrongwrong"})
    assert events == [("error", events[0][1])] and events[0][1]["code"] == "invalid_key"
    r, events = chat(client, model="claude-notfound-1")
    assert events[-1][0] == "error" and events[-1][1]["code"] == "model_not_found"
    r = client.post("/api/chat", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]}, headers=CSRF)
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_key"


def test_skill_loading():
    body, meta = load_skill(str(Path(__file__).parent / "fixtures" / "skill"))
    assert not body.startswith("---") and meta["name"] == "answer-eye-questions-with-visionkb-kg"


# ---- the key is never logged, echoed or stored ----------------------------------------------------------------
def test_canary_key_never_logged_or_echoed(base_settings, mock_anthropic):
    stream = io.StringIO()
    cfg = log_config("DEBUG")
    cfg["handlers"]["default"]["stream"] = stream
    cfg["handlers"]["access"]["stream"] = stream
    cfg["loggers"].update(
        {n: {"level": "DEBUG", "filters": ["redact"]} for n in ("anthropic", "httpx", "httpx2", "httpcore", "mcp")}
    )
    logging.config.dictConfig(cfg)
    try:
        bodies = []
        with make_client(base_settings) as c:
            login(c)
            for model in ("claude-sonnet-mock-1", "mock-echo-key-error", "claude-notfound-1", "mock-hostile"):
                r, _events = chat(c, model=model)
                bodies.append(r.text + json.dumps(dict(r.headers)))
            r = c.get("/api/models", headers=KEY)
            bodies.append(r.text + json.dumps(dict(r.headers)))
            logging.getLogger("visionkb_web.test").warning("explicit leak attempt %s", CANARY_KEY)
            logging.getLogger("anthropic").debug("headers {'x-api-key': '%s'}", CANARY_KEY)
            try:
                raise RuntimeError("boom " + CANARY_KEY)
            except RuntimeError:
                logging.getLogger("visionkb_web.test").exception("traceback")
            state = repr(vars(c.app.state)) + repr(c.app.state.tools.env)
        out = stream.getvalue()
        assert "explicit leak attempt [redacted]" in out and "boom [redacted]" in out
        assert CANARY_KEY not in out and CANARY_KEY[12:] not in out
        assert not any(CANARY_KEY in b for b in bodies)
        echo = [b for b in bodies if "bad request for key" in b]
        assert echo and "[redacted]" in echo[0]
        assert CANARY_KEY not in state
        # the mock saw the key only in the header, never in a body
        assert not any(CANARY_KEY in json.dumps(q.get("body", {})) for q in mock_anthropic.mock.requests)
    finally:
        logging.config.dictConfig(log_config("WARNING"))


def test_redact():
    assert redact("x sk-ant-api03-abcDEF_123-xyz y") == "x [redacted] y"
    assert redact("key=supersecretvalue123", key="supersecretvalue123") == "key=[redacted]"
