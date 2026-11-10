"""Headless browser checks (Playwright + Chromium): VISIONKB_BROWSER=1 pytest tests/test_browser.py.

Page against the fake API and the mock Anthropic server: access gate, search autocomplete, entity page, evidence
drawer, chat with the first-use notice, a hostile answer rendered inert, and no CSP violations or page errors.
Screenshots go to $VISIONKB_SCREENSHOTS when set.
"""

import os
import re
from pathlib import Path

import pytest

from tests.conftest import ACCESS_CODE, CANARY_KEY
from tests.servers import ServerThread
from visionkb_web.app import create_app

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(os.environ.get("VISIONKB_BROWSER") != "1", reason="set VISIONKB_BROWSER=1"),
]


@pytest.fixture(scope="module")
def web(base_settings):
    with ServerThread(create_app(base_settings), lifespan="on") as srv:
        yield srv


@pytest.fixture
def page(web):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        pg = ctx.new_page()
        pg.problems = []
        pg.on("console", lambda m: pg.problems.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
        yield pg
        browser.close()


def shot(pg, name):
    out = os.environ.get("VISIONKB_SCREENSHOTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(out) / f"{name}.png"), full_page=False)


def test_page_flow(page, web):
    from playwright.sync_api import expect

    pg = page
    pg.goto(web.url + "/")
    pg.wait_for_selector("#gate:not([hidden])")
    pg.fill("#gate-code", ACCESS_CODE)
    pg.click("#gate-form button[type=submit]")
    pg.wait_for_selector("#gate", state="hidden")
    expect(pg.locator("#release-badge .label")).to_have_text(re.compile(r"^visionkb-"))
    assert "KI-1" in pg.inner_text("#known-issues")
    # search autocomplete -> entity page
    pg.fill("#search-q", "RHO")
    pg.wait_for_selector("#search-suggest li[role=option] .curie")
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter")
    pg.wait_for_url("**#/entity/HGNC:10012")
    pg.wait_for_selector("main .entity-head h1")
    assert "rhodopsin" in pg.inner_text("main .entity-head h1")
    pg.wait_for_selector("[role=tabpanel] table.data")
    shot(pg, "entity_mock")
    # relationships tab and evidence drawer
    pg.click("[role=tab]:has-text('Relationships')")
    pg.wait_for_selector("[role=tabpanel]:not([hidden]) button[aria-label^='Evidence for']")
    pg.click("[role=tabpanel]:not([hidden]) button[aria-label^='Evidence for']")
    pg.wait_for_selector("#drawer:not([hidden]) table.data")
    assert "Rod" in pg.inner_text("#drawer")
    pg.keyboard.press("Escape")
    pg.wait_for_selector("#drawer", state="hidden")
    # chat: key entry -> notice -> models -> answer with tool trace
    pg.fill("#chat-key", CANARY_KEY)
    pg.click(".chat-key button[type=submit]")
    pg.wait_for_selector("dialog#notice[open]")
    pg.click("#notice-ok")
    pg.wait_for_selector("#chat-model option", state="attached")
    assert pg.input_value("#chat-model") == "claude-sonnet-mock-1"
    assert pg.evaluate("sessionStorage.getItem('vkw.anthropic_key')") == CANARY_KEY
    assert pg.evaluate("Object.keys(localStorage).length") == 0
    assert CANARY_KEY not in pg.evaluate("document.cookie")
    pg.fill("#chat-input", "Which cell types express RHO?")
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".msg.assistant .meta", timeout=60_000)
    text = pg.inner_text(".msg.assistant")
    assert "2 tool calls" in text and "visionkb-0000.01.0" in text
    assert pg.locator(".msg.assistant a[data-edge]").count() >= 1
    shot(pg, "chat_mock")
    # hostile answer is inert
    pg.select_option("#chat-model", "mock-hostile")
    pg.fill("#chat-input", "hostile")
    pg.keyboard.press("Enter")
    expect(pg.locator(".msg.assistant .meta")).to_have_count(2, timeout=60_000)
    last = pg.locator(".msg.assistant").last
    assert last.locator("script, img, iframe, object, embed, form, style").count() == 0
    bad = pg.evaluate("""() => [...document.querySelectorAll('.msg.assistant *')].flatMap((e) =>
        e.getAttributeNames().filter((a) => a.startsWith('on') || a === 'style' ||
          (a === 'href' && !/^(https?:\\/\\/|#\\/)/.test(e.getAttribute('href')))).map((a) => e.tagName + ' ' + a))""")
    assert bad == [], bad
    assert "<script>window.__pwned=1</script>" in last.inner_text()  # shown as text
    assert pg.evaluate("window.__pwned") is None
    # forget key
    pg.click(".chat-key button:has-text('Forget key')")
    assert pg.evaluate("sessionStorage.getItem('vkw.anthropic_key')") is None
    # release and about pages render
    pg.goto(web.url + "/#/release")
    pg.wait_for_selector("#datasets table.data")
    pg.goto(web.url + "/#/about")
    pg.wait_for_selector("main h1")
    csp = [p for p in pg.problems if "Content Security Policy" in p or "Refused" in p]
    assert not csp, csp
    assert not [p for p in pg.problems if p.startswith("pageerror")], pg.problems


def test_mobile_layout(page, web):
    pg = page
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.goto(web.url + "/")
    pg.fill("#gate-code", ACCESS_CODE)
    pg.click("#gate-form button[type=submit]")
    pg.wait_for_selector("#search-q")
    assert not pg.is_visible("#chat .chat-input")
    pg.click("#chat-toggle")
    pg.wait_for_selector("#chat.open")
    assert pg.is_visible("#chat .chat-input")
    shot(pg, "mobile_chat_mock")
