"""visionkb-web command line: ``serve`` (default), ``check``, ``--version``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from . import __version__
from .config import ConfigError, Settings, scrub_anthropic_env


def _serve(args) -> int:
    import uvicorn

    from .app import create_app
    from .logs import log_config, setup_logging

    setup_logging(args.log_level)
    settings = Settings.from_env()
    host = args.host or settings.host
    port = args.port or settings.port
    app = create_app(settings)
    uvicorn.run(
        app,
        host=host,
        port=port,
        root_path=settings.root_path,
        log_config=log_config(args.log_level),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
        timeout_graceful_shutdown=5,
    )
    return 0


def _check(args) -> int:
    """Load settings and the skill, start the MCP child once and list its tools (no secrets printed)."""
    from .chat import load_skill
    from .mcp_tools import EXPECTED_TOOLS, McpTools

    scrub_anthropic_env()
    settings = Settings.from_env()
    _, meta = load_skill(settings.skill_dir)

    async def run():
        tools = McpTools(settings.mcp_command, {"VISIONKB_API_URL": settings.api_url,
                         "VISIONKB_API_TOKEN_FILE": settings.api_token_file,
                         "VISIONKB_TIMEOUT_S": str(settings.api_timeout_s)})  # fmt: skip
        await tools.start(wait_s=30)
        names = sorted(tools.names)
        await tools.stop()
        return names

    names = asyncio.run(run())
    print(json.dumps({"version": __version__, "skill": meta, "mcp_tools": names, "ok": set(names) == EXPECTED_TOOLS}))
    return 0 if set(names) == EXPECTED_TOOLS else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="visionkb-web", description="VisionKB home page and chat (bring your own Claude key)"
    )
    p.add_argument("--version", action="version", version=f"visionkb-web {__version__}")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the web server (settings from VISIONKB_* environment variables)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--log-level", default="INFO")
    sub.add_parser("check", help="check settings, skill and MCP tools, then exit")
    args = p.parse_args(argv)
    if args.cmd is None:
        args = p.parse_args(["serve", *(argv or [])])
    try:
        return _check(args) if args.cmd == "check" else _serve(args)
    except ConfigError as exc:
        print(f"visionkb-web: configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
