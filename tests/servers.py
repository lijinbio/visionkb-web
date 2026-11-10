"""Run an ASGI app with uvicorn in a background thread on 127.0.0.1 (tests only)."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerThread:
    def __init__(self, app, port: int | None = None, lifespan: str = "off"):
        self.port = port or free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", lifespan=lifespan)
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        for _ in range(1500):
            if self.server.started:
                return self
            time.sleep(0.02)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)


if __name__ == "__main__":  # python -m tests.servers fake-api|mock-anthropic PORT [TOKEN_FILE|KEY_FILE]
    import sys

    kind, port = sys.argv[1], int(sys.argv[2])
    if kind == "fake-api":
        from tests.fake_api import make_app

        token = Path(sys.argv[3]).read_text().strip()
        app = make_app(token)
    else:
        from tests.mock_anthropic import MockAnthropic

        key = Path(sys.argv[3]).read_text().strip() if len(sys.argv) > 3 else "sk-ant-api03-test"
        app = MockAnthropic(key).app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
