"""Settings from the environment (design §6). Secrets only as files; nothing here is ever logged."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SKILL_DIR = "/opt/visionkb-web/skill"


class ConfigError(RuntimeError):
    pass


def _int(env: dict, name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be in [{lo}, {hi}]")
    return value


def read_secret_file(path: str | os.PathLike, *, what: str) -> str:
    """First non-empty, non-comment line of a secret file (the value is never logged)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{what}: cannot read the file") from exc
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise ConfigError(f"{what}: the file is empty")


def read_access_codes(path: str | os.PathLike) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("VISIONKB_WEB_ACCESS_CODES_FILE: cannot read the file") from exc
    codes = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not codes:
        raise ConfigError("VISIONKB_WEB_ACCESS_CODES_FILE: no access codes")
    if any(len(c) < 16 for c in codes):
        raise ConfigError("VISIONKB_WEB_ACCESS_CODES_FILE: every access code must have at least 16 characters")
    return codes


@dataclass(frozen=True)
class Settings:
    api_url: str  # visionkb-api base URL ending in /v1
    api_token_file: str
    host: str = "127.0.0.1"
    port: int = 8780
    root_path: str = ""
    public: bool = False
    secret_file: str | None = None
    access_codes_file: str | None = None
    skill_dir: str = DEFAULT_SKILL_DIR
    mcp_command: str = "visionkb-kg-mcp"
    anthropic_base_url: str = "https://api.anthropic.com"
    default_model: str = ""
    max_tool_calls: int = 16
    max_output_tokens: int = 4096
    max_history_chars: int = 60_000
    api_timeout_s: int = 30
    # limits (design §5)
    max_message_chars: int = 8_000
    max_body_bytes: int = 256 * 1024
    chat_per_window: int = 20
    chat_window_s: int = 600
    proxy_per_minute: int = 120
    session_ttl_s: int = 12 * 3600
    extra: dict = field(default_factory=dict)

    @property
    def api_root(self) -> str:
        """Base URL without the /v1 suffix (the MCP server accepts either)."""
        return self.api_url[: -len("/v1")] if self.api_url.endswith("/v1") else self.api_url

    @classmethod
    def from_env(cls, env: dict | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        api_url = env.get("VISIONKB_API_URL", "").strip().rstrip("/")
        if not api_url:
            raise ConfigError("VISIONKB_API_URL is required (visionkb-api base URL, .../v1)")
        if not api_url.startswith(("http://", "https://")):
            raise ConfigError("VISIONKB_API_URL must be an http(s) URL")
        if not api_url.endswith("/v1"):
            api_url += "/v1"
        token_file = env.get("VISIONKB_API_TOKEN_FILE", "").strip()
        if not token_file:
            raise ConfigError("VISIONKB_API_TOKEN_FILE is required (read-scope visionkb-api token)")
        public = env.get("VISIONKB_WEB_PUBLIC", "0").strip() == "1"
        secret_file = env.get("VISIONKB_WEB_SECRET_FILE", "").strip() or None
        codes_file = env.get("VISIONKB_WEB_ACCESS_CODES_FILE", "").strip() or None
        if not public and not (secret_file and codes_file):
            raise ConfigError(
                "VISIONKB_WEB_SECRET_FILE and VISIONKB_WEB_ACCESS_CODES_FILE are required unless VISIONKB_WEB_PUBLIC=1"
            )
        root_path = env.get("VISIONKB_WEB_ROOT_PATH", "").strip().rstrip("/")
        if root_path and not root_path.startswith("/"):
            raise ConfigError("VISIONKB_WEB_ROOT_PATH must start with /")
        base = env.get("VISIONKB_WEB_ANTHROPIC_BASE_URL", "").strip().rstrip("/") or "https://api.anthropic.com"
        if not base.startswith(("http://", "https://")):
            raise ConfigError("VISIONKB_WEB_ANTHROPIC_BASE_URL must be an http(s) URL")
        return cls(
            api_url=api_url,
            api_token_file=token_file,
            host=env.get("VISIONKB_WEB_HOST", "").strip() or "127.0.0.1",
            port=_int(env, "VISIONKB_WEB_PORT", 8780, 1, 65535),
            root_path=root_path,
            public=public,
            secret_file=secret_file,
            access_codes_file=codes_file,
            skill_dir=env.get("VISIONKB_WEB_SKILL_DIR", "").strip() or DEFAULT_SKILL_DIR,
            mcp_command=env.get("VISIONKB_WEB_MCP_COMMAND", "").strip() or "visionkb-kg-mcp",
            anthropic_base_url=base,
            default_model=env.get("VISIONKB_WEB_DEFAULT_MODEL", "").strip(),
            max_tool_calls=_int(env, "VISIONKB_WEB_MAX_TOOL_CALLS", 16, 0, 64),
            max_output_tokens=_int(env, "VISIONKB_WEB_MAX_OUTPUT_TOKENS", 4096, 256, 64_000),
            max_history_chars=_int(env, "VISIONKB_WEB_MAX_HISTORY_CHARS", 60_000, 8_000, 1_000_000),
            api_timeout_s=_int(env, "VISIONKB_TIMEOUT_S", 30, 1, 600),
        )


def scrub_anthropic_env(environ: dict | None = None) -> list[str]:
    """Remove every ANTHROPIC_* variable (no server-side key in v0.0.1; the SDK would read them). Returns names."""
    environ = os.environ if environ is None else environ
    names = sorted(k for k in environ if k.upper().startswith("ANTHROPIC_"))
    for k in names:
        environ.pop(k, None)
    return names
