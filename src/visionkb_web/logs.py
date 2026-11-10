"""Logging that cannot leak a Claude API key (design §4).

Every handler formats through ``RedactingFormatter``: ``sk-ant-...`` patterns and the key of the request being served
(a context variable) are replaced before the line is written, including tracebacks. Request headers are never logged;
the access log has client, request line (no query values that carry keys: keys travel only in a header) and status.
"""

from __future__ import annotations

import contextvars
import logging
import logging.config
import re

from uvicorn.logging import AccessFormatter

KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]{4,}")
REDACTED = "[redacted]"
current_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("visionkb_web_current_key", default=None)


def redact(text: str, key: str | None = None) -> str:
    if not text:
        return text
    key = key if key is not None else current_key.get()
    if key and len(key) >= 8:
        text = text.replace(key, REDACTED)
    return KEY_PATTERN.sub(REDACTED, text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingAccessFormatter(AccessFormatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingFilter(logging.Filter):
    """Also attached to loggers, for handlers configured by someone else (e.g. pytest's capture)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # a broken format string: keep the raw template only
            msg = str(record.msg)
        record.msg, record.args = redact(msg), None
        return True


QUIET_LOGGERS = ("anthropic", "httpx", "httpx2", "httpcore", "mcp", "hpack")


def log_config(level: str = "INFO") -> dict:
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact": {"()": RedactingFilter}},
        "formatters": {
            "default": {"()": RedactingFormatter, "fmt": fmt},
            "access": {
                "()": RedactingAccessFormatter,
                "fmt": '%(asctime)s access %(client_addr)s "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "filters": ["redact"],
                "stream": "ext://sys.stderr",
            },
            "access": {"class": "logging.StreamHandler", "formatter": "access", "stream": "ext://sys.stderr"},
        },
        "loggers": {
            "": {"handlers": ["default"], "level": level, "filters": ["redact"]},
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False, "filters": ["redact"]},
            "uvicorn.error": {"level": level, "filters": ["redact"]},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            **{name: {"level": "WARNING", "filters": ["redact"]} for name in QUIET_LOGGERS},
        },
    }


def setup_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(log_config(level))
