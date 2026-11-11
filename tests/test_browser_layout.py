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
    assert int(h.get_attribute("aria-valuemax")) == int(min(0.55 * vw, vw - 480))
    assert mode(pg) == "docked" and prefs(pg) is None  # nothing stored until the user changes the layout
    if vw == 1920:
        shot(pg, "layout_docked_1920")
    clean(pg)


def test_drag_resize_bounds_and_persistence(browser, web):
    pg = open_page(browser, web, 1366, 900)
    drag_to(pg, 1366 - 700)
    assert abs(chat_w(pg) - 700) <= 2, chat_w(pg)
    assert prefs(pg)["width"] in range(698, 703)
    drag_to(pg, 20)  # as wide as allowed: 55% of the viewport (main keeps >= 480 px)
    assert abs(chat_w(pg) - 751) <= 1, chat_w(pg)
    assert pg.locator("main").bounding_box()["width"] >= 479
    drag_to(pg, 1360)  # as narrow as allowed
    assert abs(chat_w(pg) - 360) <= 1, chat_w(pg)
    drag_to(pg, 1366 - 650)
    pg.reload()
    pg.wait_for_selector("#chat-resize", state="attached")
    assert abs(chat_w(pg) - 650) <= 2, chat_w(pg)
    pg.set_viewport_size({"width": 1000, "height": 900})  # re-clamped on window resize: 1000 - 480 = 520
    pg.wait_for_timeout(150)
    assert abs(chat_w(pg) - 520) <= 1, chat_w(pg)
    assert pg.locator("#chat-resize").get_attribute("aria-valuemax") == "520"
    pg.set_viewport_size({"width": 1366, "height": 900})  # the preference comes back
    pg.wait_for_timeout(150)
    assert abs(chat_w(pg) - 650) <= 2
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
    assert abs(chat_w(pg) - 751) <= 1
    pg.keyboard.press("End")
    assert abs(chat_w(pg) - 360) <= 1
    assert pg.get_attribute("#chat-resize", "aria-valuenow") == "360"
    clean(pg)


def test_one_expand_control_and_modes(browser, web):
    from playwright.sync_api import expect

    pg = open_page(browser, web, 1366, 900)
    # one Expand control (to #/chat) and Collapse; no separate pop-out link or in-place expanded mode
    assert pg.locator(".chat-head .chat-mode-btn").count() == 2
    assert pg.locator(".chat-head a[href='#/chat']").count() == 0
    pg.click("nav a[data-nav=release]")
    pg.wait_for_url("**#/release")
    pg.click("#chat-expand")
    pg.wait_for_url("**#/chat")
    pg.wait_for_selector("body[data-chat=page]")
    assert pg.get_attribute("#chat-expand", "aria-pressed") == "true" and not pg.is_visible("main")
    assert active_id(pg) == "chat-input"
    expect(pg.locator("#chat-layout-status")).to_have_text("Chat open as a full page")
    pg.keyboard.press("Escape")  # Esc: back to the page it came from, docked
    pg.wait_for_url("**#/release")
    pg.wait_for_selector("body[data-chat=docked]")
    assert pg.is_visible("main") and active_id(pg) == "chat-expand"
    expect(pg.locator("#chat-layout-status")).to_have_text("Chat docked")
    pg.click("nav a[data-nav=home]")
    pg.wait_for_selector("#search-q")
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
    # Expand = #/chat: same tab, same history
    pg.click("#chat-expand")
    pg.wait_for_url("**#/chat")
    pg.wait_for_selector("body[data-chat=page]")
    assert not pg.is_visible("main") and pg.locator(".msg").count() == 2 and pg.title().startswith("Chat")
    shot(pg, "layout_chat_page_mock")
    # an entity link in the answer opens the entity page with the chat docked
    pg.locator(".msg.assistant a.kg-link[href^='#/entity/']").first.click()
    pg.wait_for_url("**#/entity/HGNC:10012")
    pg.wait_for_selector("body[data-chat=docked] main .entity-head h1")
    assert pg.is_visible("main") and pg.is_visible("#chat")
    # Back from #/chat returns to the entity page, docked
    pg.click("#chat-expand")
    pg.wait_for_selector("body[data-chat=page]")
    pg.go_back()
    pg.wait_for_url("**#/entity/HGNC:10012")
    pg.wait_for_selector("body[data-chat=docked] main .entity-head h1")
    # the pressed Expand (Dock) button returns too; Forward re-opens the full page (bookmarkable URL)
    pg.go_forward()
    pg.wait_for_selector("body[data-chat=page]")
    pg.click("#chat-expand")
    pg.wait_for_url("**#/entity/HGNC:10012")
    pg.wait_for_selector("body[data-chat=docked]")
    # a bookmarked #/chat opens the full page directly; leaving goes home
    pg.goto(web.url + "/#/chat")
    pg.reload()
    pg.wait_for_selector("body[data-chat=page]")
    pg.keyboard.press("Escape")
    pg.wait_for_selector("body[data-chat=docked]")
    clean(pg)


@pytest.mark.parametrize("vw,want", [(1366, 0.6 * 1366), (1920, 960), (2560, 960)])
def test_full_page_default_width(browser, web, vw, want):
    pg = open_page(browser, web, vw, 1000)
    pg.click("#chat-expand")
    pg.wait_for_selector("body[data-chat=page]")
    box = pg.locator("#chat").bounding_box()
    assert abs(box["width"] - want) <= 2, (vw, box)
    assert abs(box["x"] - (vw - box["x"] - box["width"])) <= 2  # centred
    assert not pg.is_visible("#chat-resize")
    for side in ("left", "right"):
        hd = f"#chat-resize-full-{side}"
        assert pg.is_visible(hd) and pg.get_attribute(hd, "role") == "separator"
        assert pg.get_attribute(hd, "aria-valuemin") == "560" and pg.get_attribute(hd, "aria-valuemax") == str(
            min(1400, vw - 64)
        )
        assert abs(int(pg.get_attribute(hd, "aria-valuenow")) - want) <= 2
    if vw == 1920:
        shot(pg, "layout_full_page_1920_mock")
    pg.focus("#chat-resize-full-right")
    pg.keyboard.press("Home")  # the maximum: min(1400, viewport - 64)
    assert abs(chat_w(pg) - min(1400, vw - 64)) <= 1
    pg.keyboard.press("Enter")  # reset
    assert abs(chat_w(pg) - want) <= 2 and prefs(pg)["fullWidth"] is None
    clean(pg)


def test_full_page_content_uses_full_column(browser, web):
    pg = open_page(browser, web, 1920, 1000)
    use_key(pg)
    ask(pg)
    font = "(s) => { const c = getComputedStyle(document.querySelector(s)); return [c.fontSize, c.lineHeight]; }"
    docked = pg.evaluate(font, ".msg.assistant .md")
    pg.click("#chat-expand")
    pg.wait_for_selector("body[data-chat=page]")
    assert pg.evaluate(font, ".msg.assistant .md") == ["17px", "27.2px"]  # 1.0625 x 16 px, line-height 1.6
    assert pg.evaluate(font, ".msg.user") == ["17px", "27.2px"]
    md = pg.locator(".msg.assistant .md").first.bounding_box()
    assert md["width"] >= 960 - 120, md  # the answer fills the 960 px column (minus padding)
    for sel in (".msg.assistant .md .table-wrap", ".msg.assistant .md pre", ".msg.assistant details.trace"):
        if pg.locator(sel).count():
            assert pg.evaluate(f"getComputedStyle(document.querySelector('{sel}')).overflowX") == "auto", sel
    widths = pg.evaluate(
        """() => [...document.querySelectorAll('.msg.assistant .md')].flatMap((md) =>
             [...md.querySelectorAll(':scope > p, :scope > .table-wrap, :scope > pre')].map((el) =>
               [el.tagName + '.' + el.className, el.getBoundingClientRect().width, md.clientWidth]))"""
    )
    assert any(t.startswith("P") for t, _, _ in widths), widths
    for tag, w, md_w in widths:  # no prose cap: paragraphs, tables and code fill the answer width
        assert w >= md_w - 2, (tag, w, md_w)
    trace = pg.locator(".msg.assistant details.trace").first.bounding_box()
    assert trace["width"] >= md["width"] - 2, (trace, md)  # tool trace: full column width
    pg.keyboard.press("Escape")
    pg.wait_for_selector("body[data-chat=docked]")
    assert pg.evaluate(font, ".msg.assistant .md") == docked  # docked text unchanged
    clean(pg)


def test_full_page_width_follows_root_font_size(browser, web):
    pg = open_page(browser, web, 1920, 1000)
    pg.evaluate(
        "document.documentElement.style.fontSize = '18.75px'"  # = 93.75% of a 20 px browser font size
    )  # as with a 20 px browser font size (93.75% -> 125%)
    pg.click("#chat-expand")
    pg.wait_for_selector("body[data-chat=page]")
    assert abs(chat_w(pg) - 1152) <= 2  # clamp(45, 60vw, 60) x 20 px = clamp(900, 1152, 1200)
    hd = "#chat-resize-full-right"
    assert pg.get_attribute(hd, "aria-valuemin") == "700" and pg.get_attribute(hd, "aria-valuemax") == "1750"
    pg.focus(hd)
    pg.keyboard.press("End")
    assert abs(chat_w(pg) - 700) <= 1  # 35 x 20 px
    pg.keyboard.press("Enter")
    pg.evaluate("document.documentElement.style.fontSize = ''")
    clean(pg)


def test_full_page_resize_bounds_and_persistence(browser, web):
    pg = open_page(browser, web, 1366, 900)
    pg.click("#chat-expand")
    pg.wait_for_selector("body[data-chat=page]")
    w0 = chat_w(pg)
    right = pg.locator("#chat-resize-full-right").bounding_box()
    y = right["y"] + right["height"] / 2
    pg.mouse.move(right["x"] + right["width"] / 2, y)
    pg.mouse.down()
    pg.mouse.move(right["x"] + right["width"] / 2 + 100, y, steps=6)  # right edge out by 100: both edges move
    pg.mouse.up()
    assert abs(chat_w(pg) - (w0 + 200)) <= 3, (w0, chat_w(pg))
    assert abs(prefs(pg)["fullWidth"] - chat_w(pg)) <= 1 and prefs(pg)["width"] is None  # stored apart from the dock
    left = pg.locator("#chat-resize-full-left").bounding_box()
    pg.mouse.move(left["x"] + left["width"] / 2, y)
    pg.mouse.down()
    pg.mouse.move(683, y, steps=6)  # to the centre: the minimum
    pg.mouse.up()
    assert abs(chat_w(pg) - 560) <= 1
    pg.mouse.move(683 - 280, y)  # the left edge is now at 683 - 280
    pg.mouse.down()
    pg.mouse.move(0, y, steps=6)
    pg.mouse.up()
    assert abs(chat_w(pg) - (1366 - 64)) <= 1  # the maximum: viewport - 64
    pg.focus("#chat-resize-full-right")
    pg.keyboard.press("End")
    assert abs(chat_w(pg) - 560) <= 1
    pg.keyboard.press("ArrowRight")
    assert abs(chat_w(pg) - 592) <= 1  # 16 px per edge
    pg.focus("#chat-resize-full-left")
    pg.keyboard.press("Shift+ArrowLeft")
    assert abs(chat_w(pg) - 720) <= 1  # 64 px per edge
    pg.keyboard.press("ArrowRight")
    assert abs(chat_w(pg) - 688) <= 1
    pg.keyboard.press("Home")
    assert abs(chat_w(pg) - 1302) <= 1 and pg.get_attribute("#chat-resize-full-left", "aria-valuenow") == "1302"
    pg.keyboard.press("ArrowRight")
    pg.reload()  # persists; #/chat reloads as the full page
    pg.wait_for_selector("body[data-chat=page]")
    assert abs(chat_w(pg) - 1270) <= 1
    pg.set_viewport_size({"width": 1100, "height": 900})  # re-clamped: 1100 - 64
    pg.wait_for_timeout(150)
    assert abs(chat_w(pg) - 1036) <= 1 and pg.get_attribute("#chat-resize-full-right", "aria-valuemax") == "1036"
    pg.set_viewport_size({"width": 1366, "height": 900})
    pg.wait_for_timeout(150)
    pg.dblclick("#chat-resize-full-right")  # reset
    assert abs(chat_w(pg) - 0.6 * 1366) <= 2 and prefs(pg)["fullWidth"] is None
    pg.focus("#chat-resize-full-left")
    pg.keyboard.press("Home")
    pg.keyboard.press("Enter")  # Enter resets too
    assert abs(chat_w(pg) - 0.6 * 1366) <= 2
    clean(pg)


def test_migrates_stored_expanded_mode(browser, web):
    pg = open_page(browser, web, 1366, 900)
    pg.evaluate(f"localStorage.setItem('{LAYOUT_KEY}', JSON.stringify({{width: 700, mode: 'expanded'}}))")
    pg.reload()
    pg.wait_for_selector("#chat-resize", state="attached")
    pg.wait_for_selector("body[data-chat=docked]")
    assert abs(chat_w(pg) - 700) <= 2 and pg.is_visible("main")
    assert prefs(pg) == {"width": 700, "fullWidth": None, "mode": "docked"}
    clean(pg)


def test_reclamps_stored_widths_above_the_new_maximum(browser, web):
    pg = open_page(browser, web, 1920, 1000)  # 0.0.3 allowed 70%: 1344 px docked; full page went to viewport - 64
    pg.evaluate(
        f"localStorage.setItem('{LAYOUT_KEY}', JSON.stringify({{width: 1344, fullWidth: 1856, mode: 'docked'}}))"
    )
    pg.reload()
    pg.wait_for_selector("body[data-chat=docked]")
    assert abs(chat_w(pg) - 1056) <= 1 and pg.locator("main").bounding_box()["width"] >= 479  # 55% of 1920
    assert prefs(pg) == {"width": 1056, "fullWidth": 1400, "mode": "docked"}  # rewritten
    pg.click("#chat-expand")
    pg.wait_for_selector("body[data-chat=page]")
    assert abs(chat_w(pg) - 1400) <= 1
    clean(pg)


def test_main_has_no_focus_outline_after_route_change(browser, web):
    pg = open_page(browser, web, 1366, 900)
    pg.click("nav a[data-nav=about]")
    pg.wait_for_url("**#/about")
    pg.wait_for_selector("main h1:has-text('About VisionKB')")
    assert active_id(pg) == "main"
    style = pg.evaluate(
        "(() => { const s = getComputedStyle(document.getElementById('main')); return [s.outlineStyle, s.outlineWidth]; })()"
    )
    assert style[0] == "none" or style[1] == "0px", style
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
    assert set(json.loads(items[LAYOUT_KEY])) == {"width", "fullWidth", "mode"}
    assert pg.evaluate("sessionStorage.getItem('vkw.anthropic_key')") == CANARY_KEY
    assert CANARY_KEY not in pg.evaluate("document.cookie")
    clean(pg)


def test_mobile_slide_over_unchanged(browser, web):
    pg = open_page(browser, web, 390, 844)
    for sel in (
        "#chat-resize",
        "#chat-expand",
        "#chat-collapse",
        "#chat-resize-full-left",
        "#chat-resize-full-right",
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
