"""A mock Anthropic API: GET /v1/models and streaming POST /v1/messages with tool use (tests only).

Scenario by model id:
- ``*two-tools*`` (and any other id): search_entities(RHO) -> get_relationships(subject=<first id>) -> a final answer
  that quotes kg_release and the first edge_id from the tool results it was given.
- ``*loop*``: asks for get_release forever (until tool_choice none) -> tests the tool-call cap.
- ``*parallel*``: two tool_use blocks in one response.
- ``*hostile*``: a final answer with script/handler/javascript: payloads.
- ``*echo-key-error*``: 400 whose message contains the key (a hostile upstream echo).
Requests are recorded without the key header (only whether it matched).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

MODELS = [
    {
        "id": "claude-haiku-mock-1",
        "display_name": "Claude Haiku (mock)",
        "created_at": "2026-10-01T00:00:00Z",
        "type": "model",
    },
    {
        "id": "claude-sonnet-mock-1",
        "display_name": "Claude Sonnet (mock)",
        "created_at": "2026-09-01T00:00:00Z",
        "type": "model",
    },
    {"id": "mock-loop", "display_name": "Mock loop", "created_at": "2026-01-01T00:00:00Z", "type": "model"},
    {
        "id": "mock-hostile",
        "display_name": "Mock hostile answer",
        "created_at": "2026-01-01T00:00:00Z",
        "type": "model",
    },
]
HOSTILE = (
    'Answer <script>window.__pwned=1</script> <img src=x onerror="window.__pwned=2"> '
    '[click](javascript:window.__pwned=3) <a href="data:text/html,x">d</a> '
    '<iframe src="https://evil.example"></iframe> **bold** HGNC:10012 visionkb:e-0123456789abcdef0123456789abcdef01234567'
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _tool_results(messages: list) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            out += [b for b in m["content"] if b.get("type") == "tool_result"]
    return out


def _parse(block: dict) -> dict:
    content = block.get("content")
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return {}


class MockAnthropic:
    def __init__(self, key: str):
        self.key = key
        self.requests: list[dict] = []
        self.app = Starlette(
            routes=[Route("/v1/models", self.models), Route("/v1/messages", self.messages, methods=["POST"])]
        )

    def _key_ok(self, request: Request) -> bool:
        # anthropic-sdk-python 2.x sends an API key as "Authorization: Bearer"; 0.x sent "x-api-key"
        return (
            request.headers.get("x-api-key") == self.key or request.headers.get("authorization") == f"Bearer {self.key}"
        )

    def _auth_error(self):
        return JSONResponse(
            {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
            status_code=401,
        )

    async def models(self, request: Request):
        ok = self._key_ok(request)
        self.requests.append({"path": "/v1/models", "key_ok": ok, "query": dict(request.query_params)})
        if not ok:
            return self._auth_error()
        return JSONResponse(
            {"data": MODELS, "has_more": False, "first_id": MODELS[0]["id"], "last_id": MODELS[-1]["id"]}
        )

    async def messages(self, request: Request):
        body = await request.json()
        ok = self._key_ok(request)
        self.requests.append({"path": "/v1/messages", "key_ok": ok, "body": body})
        if not ok:
            return self._auth_error()
        model = body["model"]
        if "echo-key-error" in model:
            return JSONResponse({"type": "error", "error": {"type": "invalid_request_error",
                                 "message": f"bad request for key {self.key}"}}, status_code=400)  # fmt: skip
        if "notfound" in model:
            return JSONResponse(
                {"type": "error", "error": {"type": "not_found_error", "message": f"model: {model}"}}, status_code=404
            )
        return StreamingResponse(self._stream(body), media_type="text/event-stream")

    def _plan(self, body: dict) -> tuple[list[tuple[str, object]], str]:
        """Content blocks [(kind, payload)] and stop_reason for this request."""
        model, msgs = body["model"], body["messages"]
        results = _tool_results(msgs)
        no_tools = body.get("tool_choice", {}).get("type") == "none" or not body.get("tools")
        n = len(results)
        if "hostile" in model:
            return [("text", HOSTILE)], "end_turn"
        if "loop" in model and not no_tools:
            return [("text", f"Checking ({n})."), ("tool_use", ("get_release", {}))], "tool_use"
        if "parallel" in model and not no_tools and n == 0:
            return [
                ("tool_use", ("search_entities", {"q": "RHO", "limit": 3})),
                ("tool_use", ("get_release", {})),
            ], "tool_use"
        if not no_tools and n == 0:
            return [
                ("text", "Let me look up RHO. "),
                ("tool_use", ("search_entities", {"q": "RHO", "limit": 3})),
            ], "tool_use"
        if not no_tools and n == 1:
            first = (_parse(results[0]).get("data") or [{}])[0].get("id", "HGNC:10012")
            return [
                ("tool_use", ("get_relationships", {"subject": first, "predicate": "biolink:expressed_in", "limit": 5}))
            ], "tool_use"
        parsed = [_parse(r) for r in results]
        release = next((p.get("kg_release") for p in parsed if p.get("kg_release")), "unknown")
        edge = next((row.get("edge_id") for p in parsed if isinstance(p.get("data"), list)
                     for row in p["data"] if isinstance(row, dict) and row.get("edge_id")), None)  # fmt: skip
        text = (f"**RHO** (HGNC:10012) is expressed in the cell types below (kg_release {release}).\n\n"
                f"| edge | predicate |\n|---|---|\n| `{edge}` | expressed_in |\n\nTool results seen: {n}.")  # fmt: skip
        return [("text", text)], "end_turn"

    def _stream(self, body: dict) -> Iterator[str]:
        blocks, stop = self._plan(body)
        cached = any(isinstance(b, dict) and b.get("cache_control") for b in body.get("system") or [])
        usage = {
            "input_tokens": 100,
            "output_tokens": 1,
            "cache_creation_input_tokens": 50 if cached else 0,
            "cache_read_input_tokens": 0,
        }
        yield _sse("message_start", {"type": "message_start", "message": {"id": "msg_mock", "type": "message", "role": "assistant",
              "model": body["model"], "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}})  # fmt: skip
        for i, (kind, payload) in enumerate(blocks):
            if kind == "text":
                yield _sse(
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                )
                text = str(payload)
                for j in range(0, len(text), 40):
                    yield _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": i,
                            "delta": {"type": "text_delta", "text": text[j : j + 40]},
                        },
                    )
            else:
                name, args = payload
                yield _sse("content_block_start", {"type": "content_block_start", "index": i,
                           "content_block": {"type": "tool_use", "id": f"toolu_{len(self.requests)}_{i}", "name": name, "input": {}}})  # fmt: skip
                js = json.dumps(args)
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": js[:5]},
                    },
                )
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": js[5:]},
                    },
                )
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": i})
        yield _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 42},
            },
        )
        yield _sse("message_stop", {"type": "message_stop"})
