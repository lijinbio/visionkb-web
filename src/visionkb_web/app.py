"""visionkb-web: FastAPI app (static page, health, session, KG proxy, models, chat)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from importlib import resources
from pathlib import Path
from typing import Any

import anthropic
import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .chat import (
    ChatInputError,
    check_key,
    choose_default,
    load_skill,
    map_error,
    parse_chat_body,
    run_chat,
    system_blocks,
    truncate_history,
)
from .config import Settings, read_access_codes, read_secret_file, scrub_anthropic_env
from .logs import current_key, redact
from .mcp_tools import EXPECTED_TOOLS, McpTools
from .proxy import MAX_QUERY, envelope_error, upstream_path
from .security import (
    COOKIE,
    CSRF_HEADER,
    HSTS,
    SECURITY_HEADERS,
    ActiveChats,
    RateLimiter,
    SessionSigner,
    code_matches,
)

log = logging.getLogger("visionkb_web")
STATIC = Path(str(resources.files("visionkb_web") / "static"))


def _err(code: str, message: str, status: int, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


class Guard:
    """Pure ASGI middleware: security headers on every response; on non-GET requests the CSRF header and the
    request-body cap (design §5). Never logs headers."""

    def __init__(self, app, max_body: int):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        https = scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https"
        path = scope.get("path", "")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                names = {k.lower() for k, _ in hdrs}
                for k, v in SECURITY_HEADERS.items():
                    hdrs.append((k.encode(), v.encode()))
                if https:
                    hdrs.append((b"strict-transport-security", HSTS.encode()))
                if "/api/" in path and b"cache-control" not in names:
                    hdrs.append((b"cache-control", b"no-store"))
                message = {**message, "headers": hdrs}
            await send(message)

        if scope["method"] not in ("GET", "HEAD"):
            if headers.get(CSRF_HEADER) != "1":
                resp = _err("csrf", "missing header X-VisionKB-Web: 1", 403)
                return await resp(scope, receive, send_wrapper)
            try:
                declared = int(headers.get("content-length", "0") or 0)
            except ValueError:
                declared = self.max_body + 1
            too_big = _err("body_too_large", f"request body over {self.max_body} bytes", 413)
            if declared > self.max_body:
                return await too_big(scope, receive, send_wrapper)
            body, more = b"", True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return None
                body += message.get("body", b"")
                if len(body) > self.max_body:
                    return await too_big(scope, receive, send_wrapper)
                more = message.get("more_body", False)
            replayed = False

            async def receive_replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await self.app(scope, receive_replay, send_wrapper)
        return await self.app(scope, receive, send_wrapper)


def create_app(settings: Settings, *, tools: McpTools | None = None) -> FastAPI:
    removed = scrub_anthropic_env()
    skill_body, skill_meta = load_skill(settings.skill_dir)
    system = system_blocks(skill_body)
    signer = None if settings.public else SessionSigner(read_secret_file(settings.secret_file, what="VISIONKB_WEB_SECRET_FILE"), settings.session_ttl_s)  # fmt: skip
    codes = [] if settings.public else read_access_codes(settings.access_codes_file)
    if tools is None:
        tools = McpTools(
            settings.mcp_command,
            {
                "VISIONKB_API_URL": settings.api_url,
                "VISIONKB_API_TOKEN_FILE": settings.api_token_file,
                "VISIONKB_TIMEOUT_S": str(settings.api_timeout_s),
            },
            call_timeout_s=settings.api_timeout_s * 3 + 10,
        )
    proxy_limit = RateLimiter(settings.proxy_per_minute, 60)
    chat_limit = RateLimiter(settings.chat_per_window, settings.chat_window_s)
    login_limit = RateLimiter(10, 600)
    active = ActiveChats()
    state: dict[str, Any] = {}

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if removed:
            log.warning("ignored and removed environment variables: %s (no server-side key)", ", ".join(removed))
        state["api"] = httpx2.AsyncClient(
            base_url=settings.api_url, timeout=httpx2.Timeout(settings.api_timeout_s, connect=10),
            follow_redirects=False, trust_env=False,
        )  # fmt: skip
        try:
            state["anthropic_http"] = anthropic.DefaultAsyncHttpxClient(timeout=httpx2.Timeout(300, connect=15))
        except Exception as exc:  # e.g. a NO_PROXY entry httpx cannot parse
            log.warning(
                "proxy settings unusable (%s); calling Anthropic without environment proxies", type(exc).__name__
            )
            state["anthropic_http"] = anthropic.DefaultAsyncHttpxClient(timeout=httpx2.Timeout(300, connect=15), trust_env=False)  # fmt: skip
        log.info("visionkb-web %s: api %s, skill %s (%s bytes), public=%s", __version__, settings.api_url,
                 skill_meta.get("name", "?"), skill_meta.get("bytes"), settings.public)  # fmt: skip
        await tools.start()
        try:
            yield
        finally:
            await tools.stop()
            await state["api"].aclose()
            await state["anthropic_http"].aclose()

    app = FastAPI(title="visionkb-web", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)  # fmt: skip
    app.state.settings, app.state.tools = settings, tools

    # ---- sessions ------------------------------------------------------------------------------------------------
    def session_of(request: Request) -> str | None:
        if signer is None:
            return "public:" + (request.client.host if request.client else "-")
        return signer.verify(request.cookies.get(COOKIE))

    def unauthorized() -> JSONResponse:
        return _err("unauthorized", "Enter an access code first.", 401)

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "-"

    # ---- page, health ----------------------------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html", headers={"cache-control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz():
        api: dict[str, Any] = {"status": "error"}
        kg_release = None
        try:
            r = await state["api"].get("/ready", timeout=5)
            body = r.json()
            kg_release = body.get("kg_release")
            api = {"status": "ok" if r.status_code == 200 else "error", "http_status": r.status_code}
        except Exception as exc:
            api = {"status": "error", "error": type(exc).__name__}
        names = sorted(tools.names)
        mcp = {"status": "ok" if tools.ready else "error", "state": tools.status, "n_tools": len(names), "tools": names,
               "expected": len(EXPECTED_TOOLS), "restarts": tools.restarts}  # fmt: skip
        ok = api["status"] == "ok" and tools.ready
        body = {"status": "ok" if ok else "error", "version": __version__, "kg_release": kg_release, "api": api,
                "mcp": mcp, "skill": skill_meta}  # fmt: skip
        return JSONResponse(body, status_code=200 if ok else 503)

    # ---- access codes ----------------------------------------------------------------------------------------
    @app.get("/api/session")
    async def session_get(request: Request):
        return {
            "authenticated": session_of(request) is not None,
            "public": settings.public,
            "version": __version__,
            "skill": {k: v for k, v in skill_meta.items() if k in ("name", "version")},
            "limits": {
                "max_message_chars": settings.max_message_chars,
                "chat_per_window": settings.chat_per_window,
                "chat_window_s": settings.chat_window_s,
                "max_tool_calls": settings.max_tool_calls,
            },
        }

    def _cookie_kwargs(request: Request) -> dict:
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        return {"httponly": True, "samesite": "strict", "secure": https, "path": (settings.root_path or "") + "/"}

    @app.post("/api/session")
    async def session_post(request: Request):
        if signer is None:
            return {"authenticated": True, "public": True}
        if not login_limit.allow(client_ip(request)):
            return _err("rate_limited", "Too many attempts; wait a few minutes.", 429)
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not code_matches(code.strip(), codes):
            return _err("invalid_code", "That access code is not valid.", 401)
        _, token = signer.issue()
        resp = JSONResponse({"authenticated": True, "public": False, "ttl_s": settings.session_ttl_s})
        resp.set_cookie(COOKIE, token, max_age=settings.session_ttl_s, **_cookie_kwargs(request))
        return resp

    @app.delete("/api/session")
    async def session_delete(request: Request):
        resp = JSONResponse({"authenticated": False, "public": settings.public})
        resp.delete_cookie(COOKIE, **_cookie_kwargs(request))
        return resp

    # ---- KG proxy -------------------------------------------------------------------------------------------
    @app.api_route("/api/kg/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def kg_proxy(path: str, request: Request):
        def env(code: str, message: str, status: int, headers: dict | None = None) -> Response:
            return Response(envelope_error(code, message), status_code=status, media_type="application/json",
                            headers=headers)  # fmt: skip

        if request.method != "GET":
            return env("method_not_allowed", "the KG proxy is read-only (GET)", 405, {"allow": "GET"})
        sid = session_of(request)
        if sid is None:
            return env("unauthorized", "Enter an access code first.", 401)
        target = upstream_path(path)
        if target is None:
            return env("not_allowed", "not an allowed VisionKB API path", 404)
        query = request.url.query
        if len(query) > MAX_QUERY:
            return env("query_too_long", "query string too long", 414)
        if not proxy_limit.allow(sid):
            return env(
                "rate_limited", "too many requests; slow down", 429, {"retry-after": str(proxy_limit.retry_after(sid))}
            )
        try:
            token = read_secret_file(settings.api_token_file, what="VISIONKB_API_TOKEN_FILE")
        except Exception:
            return env("token_unreadable", "the server's API token file is unreadable", 503)
        try:
            r = await state["api"].get(target + ("?" + query if query else ""), headers={"authorization": "Bearer " + token, "accept": "application/json"})  # fmt: skip
        except httpx2.TimeoutException:
            return env("upstream_timeout", "visionkb-api did not answer in time", 504)
        except httpx2.HTTPError:
            return env("upstream_unreachable", "visionkb-api is unreachable", 502)
        if 300 <= r.status_code < 400:
            return env("redirect_refused", "visionkb-api answered with a redirect", 502)
        if "json" not in r.headers.get("content-type", ""):
            return env("bad_response", f"visionkb-api answered HTTP {r.status_code} without JSON", 502)
        return Response(r.content, status_code=r.status_code, media_type="application/json")

    # ---- Anthropic ------------------------------------------------------------------------------------------
    def make_client(key: str) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(api_key=key, base_url=settings.anthropic_base_url, max_retries=1,
                                        http_client=state["anthropic_http"])  # fmt: skip

    @app.get("/api/models")
    async def models(request: Request):
        sid = session_of(request)
        if sid is None:
            return unauthorized()
        try:
            key = check_key(request.headers.get("x-anthropic-key"))
        except ChatInputError as e:
            return _err(e.code, e.message, e.status)
        if not proxy_limit.allow(sid):
            return _err("rate_limited", "too many requests; slow down", 429)
        token = current_key.set(key)
        try:
            client = make_client(key)
            items = []
            async for m in client.models.list(limit=100):
                created = m.created_at.isoformat() if hasattr(m.created_at, "isoformat") else str(m.created_at)
                items.append({"id": m.id, "display_name": m.display_name, "created_at": created})
                if len(items) >= 500:
                    break
        except anthropic.APIError as exc:
            code, message, status = map_error(exc)
            if code not in ("invalid_key", "permission_denied"):
                code, status = "upstream_error", 502
            else:
                code, status = "invalid_key", 401
            log.info("models: upstream error %s", code)
            return _err(code, message, status)
        finally:
            current_key.reset(token)
            del key
        return {"data": items, "default_model": choose_default([m["id"] for m in items], settings.default_model)}

    @app.post("/api/chat")
    async def chat(request: Request):
        sid = session_of(request)
        if sid is None:
            return unauthorized()
        try:
            key = check_key(request.headers.get("x-anthropic-key"))
            try:
                body = json.loads(await request.body())
            except ValueError as exc:
                raise ChatInputError("bad_request", "body must be JSON") from exc
            model, messages = parse_chat_body(body, settings.max_message_chars)
        except ChatInputError as e:
            return _err(e.code, e.message, e.status)
        if not tools.ready:
            return _err("tools_unavailable", "The VisionKB tools are not ready; try again shortly.", 503)
        if not chat_limit.allow(sid):
            return _err("rate_limited", f"At most {settings.chat_per_window} questions per {settings.chat_window_s // 60} minutes.", 429,
                        {"retry-after": str(chat_limit.retry_after(sid))})  # fmt: skip
        if not active.acquire(sid):
            return _err("chat_busy", "A question from this session is still being answered.", 429)
        messages, dropped = truncate_history(messages, settings.max_history_chars)
        client = make_client(key)
        del key

        async def stream():
            token = current_key.set(client.api_key)
            t0 = time.monotonic()
            try:
                async for event, data in run_chat(
                    client, tools, model=model, messages=messages, system=system,
                    max_tool_calls=settings.max_tool_calls, max_output_tokens=settings.max_output_tokens,
                    history_dropped=dropped,
                ):  # fmt: skip
                    yield f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
                    if event in ("done", "error"):
                        log.info("chat %s: model=%s tool_calls=%s %.1fs", event, model,
                                 data.get("tool_calls", "-"), time.monotonic() - t0)  # fmt: skip
            except asyncio.CancelledError:
                log.info("chat cancelled by the client after %.1fs", time.monotonic() - t0)
                raise
            except Exception as exc:
                log.warning("chat failed: %s", type(exc).__name__)
                msg = redact(f"internal error ({type(exc).__name__})")
                yield f"event: error\ndata: {json.dumps({'code': 'internal_error', 'message': msg})}\n\n"
            finally:
                active.release(sid)
                current_key.reset(token)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no"})  # fmt: skip

    app.add_middleware(Guard, max_body=settings.max_body_bytes)
    return app
