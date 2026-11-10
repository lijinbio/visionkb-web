import dataclasses
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fake_api import make_app as make_fake_api
from tests.mock_anthropic import MockAnthropic
from tests.servers import ServerThread
from visionkb_web.app import create_app
from visionkb_web.config import Settings

HERE = Path(__file__).parent
CANARY_KEY = "sk-ant-api03-CANARY" + secrets.token_hex(16)
ACCESS_CODE = "test-access-code-0123456789"
CSRF = {"X-VisionKB-Web": "1"}

# The sandbox may carry NO_PROXY entries httpx cannot parse; tests talk to 127.0.0.1 only.
for _v in ("no_proxy", "NO_PROXY", "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)


@pytest.fixture(scope="session")
def secrets_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("secrets")
    (d / "api_token").write_text("fake-read-token-" + secrets.token_hex(8) + "\n")
    (d / "web_secret").write_text(secrets.token_hex(32) + "\n")
    (d / "web_access_codes").write_text("# codes\n" + ACCESS_CODE + "\n")
    return d


@pytest.fixture(scope="session")
def fake_api(secrets_dir):
    hits = []
    app = make_fake_api((secrets_dir / "api_token").read_text().strip(), hits)
    with ServerThread(app) as srv:
        srv.hits = hits
        yield srv


@pytest.fixture(scope="session")
def mock_anthropic():
    mock = MockAnthropic(CANARY_KEY)
    with ServerThread(mock.app) as srv:
        srv.mock = mock
        yield srv


@pytest.fixture(scope="session")
def base_settings(secrets_dir, fake_api, mock_anthropic):
    return Settings.from_env({
        "VISIONKB_API_URL": fake_api.url + "/v1",
        "VISIONKB_API_TOKEN_FILE": str(secrets_dir / "api_token"),
        "VISIONKB_WEB_SECRET_FILE": str(secrets_dir / "web_secret"),
        "VISIONKB_WEB_ACCESS_CODES_FILE": str(secrets_dir / "web_access_codes"),
        "VISIONKB_WEB_SKILL_DIR": str(HERE / "fixtures" / "skill"),
        "VISIONKB_WEB_ANTHROPIC_BASE_URL": mock_anthropic.url,
        "VISIONKB_TIMEOUT_S": "10",
    })  # fmt: skip


def make_client(settings, **changes):
    return TestClient(create_app(dataclasses.replace(settings, **changes)), base_url="http://testserver")


def login(client):
    r = client.post("/api/session", json={"code": ACCESS_CODE}, headers=CSRF)
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(scope="session")
def client(base_settings):
    with make_client(base_settings) as c:
        login(c)
        yield c
