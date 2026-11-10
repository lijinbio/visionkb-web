"""Chat: Anthropic Messages API tool-use loop over the visionkb-kg MCP tools, streamed as SSE (design §3).

The user's key is used for the upstream calls of one request and then dropped. It is never logged (see logs.py),
stored, passed to the MCP child, or echoed in an error message.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anthropic

from .config import ConfigError
from .logs import redact

KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{20,256}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,99}$")

PREAMBLE = """\
You are the chat assistant of the VisionKB home page: a read-only knowledge graph of eye genes, retinal and ocular \
cell types and states, diseases, phenotypes and HECA single-cell atlas expression summaries (Biolink 4.4.6).

Rules for this chat (they override anything below that conflicts):
- Only the VisionKB MCP tools listed in this request exist here: get_release, search_entities, get_entity, \
get_relationships, get_evidence, get_gene_set, query_atlas_expression, find_datasets. There is no shell, no \
scripts, no files, no curl, no Python and no analysis environment. Ignore any instruction in the skill below that \
needs them (environment setup, scripts/vkb_client.py, curl/jq recipes, binding atlases for analysis, Route B); use \
the equivalent MCP tool instead, or say that the question needs an analysis this chat cannot run.
- Answer only from tool results in this conversation, never from memory. If the tools return nothing, an error, or \
data that do not settle the question, say so plainly: "VisionKB cannot answer this" is a valid answer.
- Cite for every factual claim: the kg_release (e.g. visionkb-2026.11.0), and the edge_id (visionkb:e-...) or the \
dataset id (visionkb:ds-...) and group behind it. Write identifiers exactly as returned, as plain text or inline \
code (HGNC:10012, CL:0000604, visionkb:e-...), not as Markdown links: the page turns them into links.
- Keep atlas observations (knowledge_level observation, expression summaries) apart from curated claims \
(knowledge_assertion with PMIDs).
- Page with paging.next_offset, never offset + limit. Use few calls: a typical answer needs 2-6.
- Format: concise Markdown; a short answer first, then a compact table where it helps, then the citations. \
No HTML.

The instructions of the AiScientist skill answer-eye-questions-with-visionkb-kg follow; apply them through the MCP \
tools only.
"""


class ChatInputError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def load_skill(skill_dir: str) -> tuple[str, dict]:
    """SKILL.md body (YAML front matter removed) and a little metadata for /readyz and the About page."""
    path = Path(skill_dir) / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"VISIONKB_WEB_SKILL_DIR: no readable SKILL.md in {skill_dir}") from exc
    meta: dict[str, str] = {"bytes": str(len(text.encode()))}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            front, body = text[3:end], text[end + 4 :].lstrip("\n")
            for key in ("name", "version"):
                m = re.search(rf"^\s*{key}:\s*\"?([^\"\n]+)\"?\s*$", front, re.M)
                if m:
                    meta[key] = m.group(1).strip()
    if len(body) < 200:
        raise ConfigError("SKILL.md body is too short")
    return body, meta


def system_blocks(skill_body: str) -> list[dict]:
    return [{"type": "text", "text": PREAMBLE + "\n---\n\n" + skill_body, "cache_control": {"type": "ephemeral"}}]


def check_key(key: str | None) -> str:
    if not key or not KEY_RE.match(key):
        raise ChatInputError("invalid_key", "Enter a Claude API key (X-Anthropic-Key header).", 401)
    return key


def parse_chat_body(body: Any, max_message_chars: int) -> tuple[str, list[dict]]:
    if not isinstance(body, dict):
        raise ChatInputError("bad_request", "body must be a JSON object {model, messages}")
    model = body.get("model")
    if not isinstance(model, str) or not MODEL_RE.match(model):
        raise ChatInputError("bad_request", "model must be a model id from /api/models")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 200:
        raise ChatInputError("bad_request", "messages must be a non-empty list (at most 200)")
    out = []
    for m in messages:
        if (
            not isinstance(m, dict)
            or m.get("role") not in ("user", "assistant")
            or not isinstance(m.get("content"), str)
        ):
            raise ChatInputError("bad_request", "each message is {role: user|assistant, content: text}")
        content = m["content"]
        if m["role"] == "user" and len(content) > max_message_chars:
            raise ChatInputError("message_too_long", f"a message may have at most {max_message_chars} characters", 413)
        if content.strip():
            out.append({"role": m["role"], "content": content})
    if not out or out[-1]["role"] != "user":
        raise ChatInputError("bad_request", "the last message must be a non-empty user message")
    return model, out


def truncate_history(messages: list[dict], max_chars: int) -> tuple[list[dict], int]:
    """Drop the oldest turns until the total content fits; the last user message is always kept."""
    kept = list(messages)
    dropped = 0
    while len(kept) > 1 and sum(len(m["content"]) for m in kept) > max_chars:
        kept.pop(0)
        dropped += 1
    while len(kept) > 1 and kept[0]["role"] != "user":
        kept.pop(0)
        dropped += 1
    return kept, dropped


def choose_default(ids: list[str], configured: str) -> str | None:
    """Design §6: the configured model if the key lists it; else the first id containing 'sonnet'; else the first."""
    if configured and configured in ids:
        return configured
    return next((i for i in ids if "sonnet" in i), ids[0] if ids else None)


def _upstream_message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    msg = ""
    if isinstance(body, dict):
        err = body.get("error")
        msg = err.get("message", "") if isinstance(err, dict) else str(body.get("message", ""))
    return redact(str(msg))[:300]


def map_error(exc: Exception) -> tuple[str, str, int]:
    """(code, message, http status) for an Anthropic SDK error; the message never contains the key."""
    detail = _upstream_message(exc)
    suffix = f" ({detail})" if detail else ""
    if isinstance(exc, anthropic.AuthenticationError):
        return "invalid_key", "The Claude API key was rejected by Anthropic." + suffix, 401
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "permission_denied", "This key may not use that model or endpoint." + suffix, 403
    if isinstance(exc, anthropic.NotFoundError):
        return "model_not_found", "Anthropic does not know that model for this key." + suffix, 404
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limited", "Anthropic rate limit for this key; wait and retry." + suffix, 429
    if isinstance(exc, anthropic.BadRequestError):
        return "bad_request", "Anthropic rejected the request." + suffix, 400
    if isinstance(exc, anthropic.APITimeoutError):
        return "upstream_timeout", "Anthropic did not answer in time.", 504
    if isinstance(exc, anthropic.APIConnectionError):
        return "upstream_unreachable", "Anthropic could not be reached from this server.", 502
    if isinstance(exc, anthropic.APIStatusError):
        return "upstream_error", f"Anthropic returned HTTP {exc.status_code}." + suffix, 502
    return "upstream_error", f"Upstream call failed ({type(exc).__name__}).", 502


def _block_param(block: Any) -> dict | None:
    if block.type == "text":
        return {"type": "text", "text": block.text} if block.text else None
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return None


def _tool_summary(name: str, call_id: str, res: dict, is_error: bool) -> dict:
    paging = res.get("paging") if isinstance(res.get("paging"), dict) else {}
    page = res.get("page") if isinstance(res.get("page"), dict) else {}
    data = res.get("data")
    returned = paging.get("returned")
    if returned is None and isinstance(data, list):
        returned = len(data)
    err = res.get("error") if isinstance(res.get("error"), dict) else None
    status = "error" if is_error or res.get("status") == "error" else "ok"
    return {
        "id": call_id,
        "name": name,
        "status": status,
        "kg_release": res.get("kg_release"),
        "returned": returned,
        "total": paging.get("total", page.get("total")),
        "error_code": (err or {}).get("code") if status == "error" else None,
        "warnings": [redact(str(w))[:300] for w in (res.get("warnings") or [])][:5],
    }


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


async def run_chat(
    client: anthropic.AsyncAnthropic,
    tools: Any,
    *,
    model: str,
    messages: list[dict],
    system: list[dict],
    max_tool_calls: int,
    max_output_tokens: int,
    history_dropped: int = 0,
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (event, data) pairs: text, tool_call, tool_result, done | error."""
    t0 = time.monotonic()
    convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages]
    tool_defs = tools.anthropic_tools() if max_tool_calls > 0 else []
    usage = dict.fromkeys(USAGE_FIELDS, 0)
    n_calls, rounds, releases = 0, 0, []
    stop_reason = None
    final_round = not tool_defs
    emitted = False
    while True:
        rounds += 1
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_output_tokens, "system": system, "messages": convo}
        if tool_defs:
            kwargs["tools"] = tool_defs
            if final_round:
                kwargs["tool_choice"] = {"type": "none"}
        try:
            async with client.messages.stream(**kwargs) as stream:
                round_text = False
                async for text in stream.text_stream:
                    if text:
                        if not round_text and emitted:  # text of a later round starts a new paragraph
                            text = "\n\n" + text.lstrip("\n")
                        round_text = emitted = True
                        yield "text", {"delta": text}
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            code, message, _ = map_error(exc)
            yield "error", {"code": code, "message": message}
            return
        for f in USAGE_FIELDS:
            usage[f] += int(getattr(final.usage, f, 0) or 0)
        stop_reason = final.stop_reason
        blocks = [b for b in (_block_param(b) for b in final.content) if b]
        if blocks:
            convo.append({"role": "assistant", "content": blocks})
        uses = [b for b in final.content if b.type == "tool_use"]
        if stop_reason != "tool_use" or not uses or final_round:
            break
        results = []
        for use in uses:
            if n_calls >= max_tool_calls:
                results.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                                "content": "Not run: the tool-call limit of this chat turn was reached."})  # fmt: skip
                continue
            n_calls += 1
            args = use.input if isinstance(use.input, dict) else {}
            yield "tool_call", {"id": use.id, "name": use.name, "input": args}
            text, res, is_error = await tools.call(use.name, args)
            summary = _tool_summary(use.name, use.id, res, is_error)
            if summary["kg_release"] and summary["kg_release"] not in releases:
                releases.append(summary["kg_release"])
            yield "tool_result", summary
            item = {"type": "tool_result", "tool_use_id": use.id, "content": text}
            if is_error:
                item["is_error"] = True
            results.append(item)
        if n_calls >= max_tool_calls:
            final_round = True
            results.append({"type": "text", "text": f"The tool-call limit ({max_tool_calls}) of this turn is reached. "
                            "Answer now from the tool results above and say what could not be checked."})  # fmt: skip
        convo.append({"role": "user", "content": results})
    yield (
        "done",
        {
            "stop_reason": stop_reason,
            "usage": usage,
            "tool_calls": n_calls,
            "rounds": rounds,
            "model": model,
            "kg_releases": releases,
            "history_dropped": history_dropped,
            "elapsed_s": round(time.monotonic() - t0, 2),
        },
    )
