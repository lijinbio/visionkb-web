"""The visionkb-kg MCP server as a long-lived stdio child (design §1).

Started once at app start with a clean environment: only VISIONKB_API_URL, VISIONKB_API_TOKEN_FILE and
VISIONKB_TIMEOUT_S are passed (the MCP SDK adds HOME, LOGNAME, PATH, SHELL, TERM, USER; never ANTHROPIC_*).
The session is pinged every ``ping_s`` seconds and restarted with backoff when the child exits or stops answering.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger("visionkb_web.mcp")

EXPECTED_TOOLS = frozenset(
    {
        "get_release",
        "search_entities",
        "get_entity",
        "get_relationships",
        "get_evidence",
        "get_gene_set",
        "query_atlas_expression",
        "find_datasets",
    }
)


def error_result(code: str, message: str) -> dict:
    return {"status": "error", "kg_release": None, "data": None, "page": None, "warnings": [],
            "error": {"code": code, "message": message}}  # fmt: skip


class McpTools:
    def __init__(self, command: str, env: dict[str, str], *, call_timeout_s: float = 60, ping_s: float = 15,
                 errlog: Any = None):  # fmt: skip
        argv = shlex.split(command)
        if not argv:
            raise ValueError("empty MCP command")
        # PATH first, then next to this interpreter (a venv or conda env started without activation)
        beside = Path(sys.executable).parent / argv[0]
        argv[0] = shutil.which(argv[0]) or (str(beside) if "/" not in argv[0] and beside.exists() else argv[0])
        self.argv = argv
        self.env = dict(env)
        self.call_timeout_s = call_timeout_s
        self.ping_s = ping_s
        self.errlog = errlog or sys.stderr
        self.session: ClientSession | None = None
        self.tools: list[Any] = []
        self.status = "starting"
        self.restarts = 0
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._wake = asyncio.Event()
        self._up = asyncio.Event()

    # ---- lifecycle -------------------------------------------------------------------------------------------
    async def start(self, wait_s: float = 20) -> None:
        self._task = asyncio.create_task(self._run(), name="visionkb-kg-mcp")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._up.wait(), wait_s)

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, 10)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                with contextlib.suppress(BaseException):
                    await self._task

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                params = StdioServerParameters(command=self.argv[0], args=self.argv[1:], env=self.env)
                async with (
                    stdio_client(params, errlog=self.errlog) as (read, write),
                    ClientSession(read, write, read_timeout_seconds=self.call_timeout_s) as session,
                ):
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tools = list(listed.tools)
                    self.session, self.status, self.last_error = session, "up", None
                    self._up.set()
                    backoff = 1.0
                    log.info("MCP server up: %d tools (%s)", len(self.tools), ", ".join(sorted(self.names)))
                    await self._watch(session)
            except Exception as exc:
                self.last_error = type(exc).__name__
                log.warning("MCP server session ended: %s", type(exc).__name__)
            finally:
                self.session = None
                self._up.clear()
                if not self._stopping:
                    self.status = "down"
            if self._stopping:
                break
            self.restarts += 1
            log.warning("restarting the MCP server in %.0f s (restart %d)", backoff, self.restarts)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), backoff)
            self._wake.clear()
            backoff = min(backoff * 2, 30.0)
        self.status = "stopped"

    async def _watch(self, session: ClientSession) -> None:
        while not self._stopping:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.ping_s)
            self._wake.clear()
            if self._stopping:
                return
            await asyncio.wait_for(session.send_ping(), 10)  # raises when the child is gone -> restart

    # ---- queries ---------------------------------------------------------------------------------------------
    @property
    def names(self) -> set[str]:
        return {t.name for t in self.tools}

    @property
    def ready(self) -> bool:
        return self.session is not None and self.names == EXPECTED_TOOLS

    def anthropic_tools(self) -> list[dict]:
        """Tool definitions for the Messages API (only the expected read-only tools), sorted for a stable cache."""
        out = [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in sorted(self.tools, key=lambda t: t.name)
            if t.name in EXPECTED_TOOLS
        ]
        if out:
            out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
        return out

    async def call(self, name: str, arguments: dict | None) -> tuple[str, dict, bool]:
        """Run one tool. Returns (text passed to the model verbatim, parsed result, is_error)."""
        if name not in EXPECTED_TOOLS:
            res = error_result("unknown_tool", f"no such tool: {name}")
            return json.dumps(res), res, True
        session = self.session
        if session is None:
            res = error_result("mcp_unavailable", "the VisionKB tool server is restarting; try again shortly")
            return json.dumps(res), res, True
        try:
            result = await session.call_tool(name, arguments or {}, read_timeout_seconds=self.call_timeout_s)
        except Exception as exc:
            self._wake.set()  # ping now; restart if the child is gone
            log.warning("MCP call %s failed: %s", name, type(exc).__name__)
            res = error_result("mcp_call_failed", f"tool call failed ({type(exc).__name__})")
            return json.dumps(res), res, True
        content = getattr(result, "content", None) or []
        text = "\n".join(c.text for c in content if getattr(c, "type", None) == "text")
        structured = getattr(result, "structured_content", None)
        if not isinstance(structured, dict):
            try:
                structured = json.loads(text) if text else {}
            except ValueError:
                structured = {}
            if not isinstance(structured, dict):
                structured = {}
        if not text:
            text = json.dumps(structured, separators=(",", ":"))
        is_error = bool(
            getattr(result, "is_error", False)
        )  # MCP-level error (schema violation); API errors are results
        return text, structured, is_error
