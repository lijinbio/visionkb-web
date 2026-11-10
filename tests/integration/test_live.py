"""Integration against a running visionkb-web that talks to a real visionkb-api and real MCP tools.

    VISIONKB_IT_WEB_URL=http://127.0.0.1:18922 VISIONKB_IT_ACCESS_CODE_FILE=/path/to/web_access_codes \
    VISIONKB_IT_MOCK_KEY_FILE=/path/to/mock_key VISIONKB_IT_RELEASE=visionkb-2026.11.0 pytest tests/integration

The web app under test must be started with VISIONKB_WEB_ANTHROPIC_BASE_URL pointing at the mock Anthropic server
(``python -m tests.servers mock-anthropic PORT KEYFILE``): the chat loop then calls the real MCP tools against the
real API, without a real Claude key.
"""

import json
import os
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

WEB = os.environ.get("VISIONKB_IT_WEB_URL", "")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not WEB, reason="set VISIONKB_IT_WEB_URL")]
RELEASE = os.environ.get("VISIONKB_IT_RELEASE", "")


@pytest.fixture(scope="module")
def opener():
    jar = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    code_file = os.environ.get("VISIONKB_IT_ACCESS_CODE_FILE")
    if code_file:
        code = next(
            ln.strip() for ln in Path(code_file).read_text().splitlines() if ln.strip() and not ln.startswith("#")
        )
        req = urllib.request.Request(WEB + "/api/session", data=json.dumps({"code": code}).encode(), method="POST",
                                     headers={"X-VisionKB-Web": "1", "Content-Type": "application/json"})  # fmt: skip
        assert op.open(req, timeout=30).status == 200
    return op


def get(op, path):
    with op.open(WEB + path, timeout=120) as r:
        return r.status, json.loads(r.read())


def test_readyz_8_tools(opener):
    status, body = get(opener, "/readyz")
    assert status == 200 and body["mcp"]["n_tools"] == 8 and body["api"]["status"] == "ok", body
    assert not RELEASE or body["kg_release"] == RELEASE


def test_proxy_search_relationships_evidence(opener):
    _, s = get(opener, "/api/kg/entities/search?q=RHO&limit=5")
    assert s["status"] == "ok" and s["data"][0]["id"] == "HGNC:10012", s
    assert not RELEASE or s["kg_release"] == RELEASE
    _, rels = get(opener, "/api/kg/relationships?object=CL:0000604&limit=5")
    assert rels["status"] == "ok" and rels["data"] and rels["page"]["total"] > 0
    assert all(r["object"]["id"] == "CL:0000604" for r in rels["data"])
    edge = rels["data"][0]["edge_id"]
    _, ev = get(opener, f"/api/kg/evidence/{edge}?limit=5")
    assert ev["status"] == "ok" and ev["data"]["edge"]["edge_id"] == edge and ev["data"]["study_results"], ev
    try:
        opener.open(WEB + "/api/kg/proposals", timeout=30)
        raise AssertionError("proposals reachable")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_chat_mock_provider_real_tools(opener):
    key_file = os.environ.get("VISIONKB_IT_MOCK_KEY_FILE")
    if not key_file:
        pytest.skip("set VISIONKB_IT_MOCK_KEY_FILE (the mock provider's key)")
    key = Path(key_file).read_text().strip()
    body = {"model": "claude-sonnet-mock-1", "messages": [{"role": "user", "content": "Which cell types express RHO?"}]}
    req = urllib.request.Request(WEB + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"X-VisionKB-Web": "1", "Content-Type": "application/json", "X-Anthropic-Key": key})  # fmt: skip
    with opener.open(req, timeout=300) as r:
        text = r.read().decode()
    events = []
    for chunk in text.split("\n\n"):
        lines = dict(ln.split(": ", 1) for ln in chunk.strip().splitlines() if ": " in ln)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    results = [d for e, d in events if e == "tool_result"]
    assert [d["name"] for d in results] == ["search_entities", "get_relationships"], events
    assert all(d["status"] == "ok" for d in results)
    assert not RELEASE or all(d["kg_release"] == RELEASE for d in results)
    answer = "".join(d["delta"] for e, d in events if e == "text")
    assert "visionkb:e-" in answer and (not RELEASE or RELEASE in answer), answer
    assert events[-1][0] == "done" and events[-1][1]["tool_calls"] == 2
    assert key not in text
