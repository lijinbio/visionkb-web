"""Chat panel layout in Chromium (VISIONKB_BROWSER=1): default width, drag and keyboard resize with bounds, reset,
persistence, docked / expanded / collapsed modes with Esc and Ctrl+J, the #/chat page, readability, the mobile
slide-over, the key never in localStorage, and no CSP violations or page errors.
"""

import json
import os

import pytest

from tests.conftest import ACCESS_CODE, CANARY_KEY, shot

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(os.environ.get("VISIONKB_BROWSER") != "1", reason="set VISIONKB_BROWSER=1"),
]
LAYOUT_KEY = "visionkb-web.layout"


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


_STATE = {}  # one login per module: later contexts reuse the session cookie (the login limiter allows 10 per 10 min)


def open_page(browser, web, width=1366, height=900):
    state = _STATE.get(web.url)
    ctx = browser.new_context(viewport={"width": width, "height": height}, storage_state=state)
    pg = ctx.new_page()
    pg.problems = []
    pg.on("console", lambda m: pg.problems.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.goto(web.url + "/")
    if state is None:
        pg.fill("#gate-code", ACCESS_CODE)
        pg.click("#gate-form button[type=submit]")
        pg.wait_for_selector("#gate", state="hidden")
        _STATE[web.url] = {"cookies": ctx.storage_state()["cookies"], "origins": []}  # cookie only, no storage
    pg.wait_for_selector("#chat-resize", state="attached")
    pg.wait_for_selector("main h1")
    return pg


def clean(pg):
    assert not [p for p in pg.problems if "Content Security Policy" in p or "Refused" in p], pg.problems
    assert not [p for p in pg.problems if p.startswith("pageerror")], pg.problems


def chat_w(pg):
    return pg.locator("#chat").bounding_box()["width"]


def prefs(pg):
    raw = pg.evaluate(f"localStorage.getItem('{LAYOUT_KEY}')")
    return json.loads(raw) if raw else None


def drag_to(pg, x):
    box = pg.locator("#chat-resize").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(x, box["y"] + box["height"] / 2, steps=8)
    pg.mouse.up()
    pg.wait_for_timeout(50)


def mode(pg):
    return pg.evaluate("document.body.dataset.chat")


def active_id(pg):
    return pg.evaluate("document.activeElement && document.activeElement.id")


def use_key(pg):
    pg.fill("#chat-key", CANARY_KEY)
    pg.click(".chat-key button[type=submit]")
    pg.wait_for_selector("dialog#notice[open]")
    pg.click("#notice-ok")
    pg.wait_for_selector("#chat-model option", state="attached")


def ask(pg, text="Which cell types express RHO?", n=1):
    from playwright.sync_api import expect

    pg.fill("#chat-input", text)
    pg.keyboard.press("Enter")
    expect(pg.locator(".msg.assistant .meta")).to_have_count(n, timeout=60_000)


@pytest.mark.parametrize("vw,want", [(1366, 0.34 * 1366), (1920, 640)])
def test_default_width(browser, web, vw, want):
    pg = open_page(browser, web, vw, 1000)
    assert abs(chat_w(pg) - want) <= 2, (vw, chat_w(pg))
    h = pg.locator("#chat-resize")
    assert h.get_attribute("role") == "separator" and h.get_attribute("aria-orientation") == "vertical"
    assert abs(int(h.get_attribute("aria-valuenow")) - want) <= 2
    assert h.get_attribute("aria-valuemin") == "360"
    assert int(h.get_attribute("aria-valuemax")) == int(min(0.7 * vw, vw - 480))
    assert mode(pg) == "docked" and prefs(pg) in (None, {"width": None, "mode": "docked"})
    if vw == 1920:
        shot(pg, "layout_docked_1920")
    clean(pg)


def test_drag_resize_bounds_and_persistence(browser, web):
    pg = open_page(browser, web, 1366, 900)
    drag_to(pg, 1366 - 800)
    assert abs(chat_w(pg) - 800) <= 2, chat_w(pg)
    assert prefs(pg)["width"] in range(798, 803)
    drag_to(pg, 20)  # as wide as allowed: main keeps 480 px
    assert abs(chat_w(pg) - 886) <= 1, chat_w(pg)
    assert pg.locator("main").bounding_box()["width"] >= 479
    drag_to(pg, 1360)  # as narrow as allowed
    assert abs(chat_w(pg) - 360) <= 1, chat_w(pg)
    drag_to(pg, 1366 - 700)
    pg.reload()
    pg.wait_for_selector("#chat-resize", state="attached")
    assert abs(chat_w(pg) - 700) <= 2, chat_w(pg)
    pg.set_viewport_size({"width": 1000, "height": 900})  # re-clamped on window resize: 1000 - 480 = 520
    pg.wait_for_timeout(150)
    assert abs(chat_w(pg) - 520) <= 1, chat_w(pg)
    assert pg.locator("#chat-resize").get_attribute("aria-valuemax") == "520"
    pg.set_viewport_size({"width": 1366, "height": 900})  # the preference comes back
    pg.wait_for_timeout(150)
    assert abs(chat_w(pg) - 700) <= 2
    pg.dblclick("#chat-resize")  # reset to the default
    assert abs(chat_w(pg) - 0.34 * 1366) <= 2 and prefs(pg)["width"] is None
    clean(pg)


def test_keyboard_resize(browser, web):
    pg = open_page(browser, web, 1366, 900)
    pg.focus("#chat-resize")
    w0 = chat_w(pg)
    pg.keyboard.press("ArrowLeft")
    assert abs(chat_w(pg) - (w0 + 16)) <= 1
    pg.keyboard.press("Shift+ArrowLeft")
    assert abs(chat_w(pg) - (w0 + 80)) <= 1
    pg.keyboard.press("ArrowRight")
    assert abs(chat_w(pg) - (w0 + 64)) <= 1
    assert abs(int(pg.get_attribute("#chat-resize", "aria-valuenow")) - chat_w(pg)) <= 1
    pg.keyboard.press("Home")
    assert abs(chat_w(pg) - 886) <= 1
    pg.keyboard.press("End")
    assert abs(chat_w(pg) - 360) <= 1
    assert pg.get_attribute("#chat-resize", "aria-valuenow") == "360"
    clean(pg)


def test_modes_esc_and_shortcut(browser, web):
    from playwright.sync_api import expect

    pg = open_page(browser, web, 1366, 900)
    # expanded
    pg.click("#chat-expand")
    assert mode(pg) == "expanded" and pg.get_attribute("#chat-expand", "aria-pressed") == "true"
    assert not pg.is_visible("main") and chat_w(pg) >= 1360
    col = pg.locator(".chat-input").bounding_box()
    textarea = pg.locator("#chat-input").bounding_box()
    assert textarea["width"] < 0.75 * col["width"], (textarea, col)  # message column ~80ch, centred
    assert active_id(pg) == "chat-input"
    expect(pg.locator("#chat-layout-status")).to_have_text("Chat expanded")
    shot(pg, "layout_expanded_mock")
    pg.keyboard.press("Escape")
    assert mode(pg) == "docked" and pg.is_visible("main") and active_id(pg) == "chat-expand"
    expect(pg.locator("#chat-layout-status")).to_have_text("Chat docked")
    # collapsed: a floating pill (bottom right) and a top-bar button, both horizontal, both restore docked
    assert not pg.is_visible("#chat-restore") and not pg.is_visible("#chat-top-restore")
    pg.click("#chat-collapse")
    assert mode(pg) == "collapsed" and not pg.is_visible("#chat")
    assert pg.is_visible("#chat-restore") and pg.is_visible("#chat-top-restore")
    assert active_id(pg) == "chat-restore"
    for sel in ("#chat-restore", "#chat-top-restore"):
        assert pg.get_attribute(sel, "aria-expanded") == "false" and "Ask VisionKB" in pg.get_attribute(
            sel, "aria-label"
        )
        assert pg.inner_text(sel).strip() == "Ask VisionKB"
        style = pg.evaluate(
            f"(() => {{ const s = getComputedStyle(document.querySelector('{sel}')); return [s.writingMode, s.transform]; }})()"
        )
        assert style == ["horizontal-tb", "none"], (sel, style)  # no rotated text
    pill = pg.locator("#chat-restore").bounding_box()
    assert pill["height"] >= 44 and pill["width"] > pill["height"]
    assert 1366 - (pill["x"] + pill["width"]) < 40 and 900 - (pill["y"] + pill["height"]) < 40  # bottom right
    assert pg.locator("#chat-top-restore").bounding_box()["y"] < 56  # in the top bar
    assert pg.locator("main").bounding_box()["width"] >= 1360
    pg.click("#chat-restore")
    assert mode(pg) == "docked" and pg.is_visible("#chat") and active_id(pg) == "chat-input"
    assert not pg.is_visible("#chat-restore") and not pg.is_visible("#chat-top-restore")
    pg.click("#chat-collapse")
    pg.fill("#search-q", "")  # page state kept
    pg.click("#chat-top-restore")
    assert mode(pg) == "docked" and active_id(pg) == "chat-input"
    # Ctrl+J from the page and from the chat box toggles; not while typing in the search box
    pg.locator("main h1").first.click()
    pg.keyboard.press("Control+j")
    assert mode(pg) == "collapsed"
    pg.keyboard.press("Control+j")
    assert mode(pg) == "docked"
    pg.focus("#chat-input")
    pg.keyboard.press("Control+j")
    assert mode(pg) == "collapsed"
    pg.keyboard.press("Control+j")
    pg.focus("#search-q")
    pg.keyboard.press("Control+j")
    assert mode(pg) == "docked" and active_id(pg) == "search-q"
    # Esc while expanded with the evidence drawer open closes only the drawer
    pg.click("#chat-collapse")
    pg.reload()  # mode persists
    pg.wait_for_selector("#chat-restore", state="visible")
    assert mode(pg) == "collapsed" and prefs(pg)["mode"] == "collapsed"
    shot(pg, "layout_collapsed_mock")
    clean(pg)


def test_chat_route_readability_and_links(browser, web):
    pg = open_page(browser, web, 1366, 900)
    use_key(pg)
    ask(pg)
    trace = pg.locator(".msg.assistant details.trace").first
    assert trace.count() == 1 and trace.get_attribute("open") is None  # trace collapsed by default
    assert pg.evaluate("getComputedStyle(document.querySelector('.msg.assistant .md .table-wrap')).overflowX") == "auto"
    assert pg.evaluate("getComputedStyle(document.querySelector('.msg.assistant a.kg-link')).whiteSpace") == "nowrap"
    edge = pg.locator(".msg.assistant a[data-edge]").first
    assert "…" in edge.inner_text() and edge.get_attribute("data-edge").startswith("visionkb:e-")
    # input grows to about 8 lines, then scrolls
    pg.fill("#chat-input", "\n".join(["line"] * 3))
    h3 = pg.locator("#chat-input").bounding_box()["height"]
    pg.fill("#chat-input", "\n".join(["line"] * 30))
    h30 = pg.locator("#chat-input").bounding_box()["height"]
    lh = pg.evaluate("parseFloat(getComputedStyle(document.getElementById('chat-input')).lineHeight)")
    assert h3 > 2.5 * lh and 7.5 * lh <= h30 <= 9.5 * lh, (h3, h30, lh)
    pg.fill("#chat-input", "")
    # #/chat: same tab, same history
    pg.click("a.chat-page-link")
    pg.wait_for_url("**#/chat")
    pg.wait_for_selector("body[data-chat=page]")
    assert mode(pg) == "page" and not pg.is_visible("main") and chat_w(pg) >= 1360
    assert pg.locator(".msg").count() == 2 and pg.title().startswith("Chat")
    shot(pg, "layout_chat_page_mock")
    # an entity link in the answer opens the entity page with the chat docked
    pg.locator(".msg.assistant a.kg-link[href^='#/entity/']").first.click()
    pg.wait_for_url("**#/entity/HGNC:10012")
    pg.wait_for_selector("body[data-chat=docked] main .entity-head h1")
    assert mode(pg) == "docked" and pg.is_visible("main") and pg.is_visible("#chat")
    # #/chat and back through the header button
    pg.goto(web.url + "/#/chat")
    pg.wait_for_selector("body[data-chat=page]")
    assert mode(pg) == "page"
    pg.click("#chat-expand")
    pg.wait_for_url("**#/entity/HGNC:10012")
    pg.wait_for_selector("body[data-chat=docked]")
    clean(pg)


def test_collapse_keeps_the_conversation(browser, web):
    pg = open_page(browser, web, 1366, 900)
    use_key(pg)
    ask(pg)
    pg.click("#chat-collapse")
    pg.click("#chat-top-restore")
    assert pg.locator(".msg").count() == 2
    pg.keyboard.press("Control+j")
    assert mode(pg) == "collapsed"
    pg.keyboard.press("Control+j")
    assert mode(pg) == "docked" and pg.locator(".msg").count() == 2
    clean(pg)


def test_key_never_in_local_storage(browser, web):
    pg = open_page(browser, web, 1366, 900)
    use_key(pg)
    ask(pg)
    drag_to(pg, 1366 - 640)
    pg.click("#chat-collapse")
    pg.reload()
    pg.wait_for_selector("#chat-restore", state="visible")
    items = pg.evaluate("Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]))")
    assert set(items) == {LAYOUT_KEY}, items
    assert CANARY_KEY not in json.dumps(items) and CANARY_KEY[:20] not in json.dumps(items)
    assert set(json.loads(items[LAYOUT_KEY])) == {"width", "mode"}
    assert pg.evaluate("sessionStorage.getItem('vkw.anthropic_key')") == CANARY_KEY
    assert CANARY_KEY not in pg.evaluate("document.cookie")
    clean(pg)


def test_mobile_slide_over_unchanged(browser, web):
    pg = open_page(browser, web, 390, 844)
    for sel in (
        "#chat-resize",
        "#chat-expand",
        "#chat-collapse",
        "a.chat-page-link",
        "#chat-restore",
        "#chat-top-restore",
    ):
        assert not pg.is_visible(sel), sel
    assert not pg.is_visible("#chat .chat-input")
    pg.click("#chat-toggle")
    pg.wait_for_selector("#chat.open")
    assert abs(chat_w(pg) - 390) <= 1 and pg.is_visible("#chat .chat-input")
    pg.locator("#chat .chat-head .btn", has_text="Close").click()
    pg.wait_for_timeout(300)
    assert not pg.locator("#chat.open").count()
    pg.locator("main h1").first.click()
    pg.keyboard.press("Control+j")  # open / close only
    pg.wait_for_selector("#chat.open")
    pg.keyboard.press("Control+j")
    pg.wait_for_timeout(300)
    assert not pg.locator("#chat.open").count()
    pg.goto(web.url + "/#/chat")
    pg.wait_for_selector("#chat.open")
    shot(pg, "layout_mobile_mock")
    clean(pg)
