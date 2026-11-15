"""Tests for maps_scraper.py. No browser needed: Playwright is replaced by a scripted fake."""
import argparse, json, os, sys
import pytest
import maps_scraper as sc
from maps_scraper import PWError, PWTimeout

# ----------------------------------------------------------------------------- fake playwright
class Resp:
    def __init__(s, status=200): s.status = status

class World:
    """Scripted universe. places: url -> cfg(raw, captcha, sorry, h1_timeout, goto_errors, on_visit, status)."""
    def __init__(s, places, no_feed=False, search_captcha=False, launch_fail=0):
        s.places, s.links = places, list(places)
        s.no_feed, s.search_captcha, s.launch_fail = no_feed, search_captcha, launch_fail
        s.visited, s.launches, s.contexts_opened, s.contexts_closed = [], 0, 0, 0

class FakeLoc:
    def __init__(s, page, sel): s.page, s.sel = page, sel
    @property
    def first(s): return s
    def wait_for(s, timeout=None):
        w, cfg = s.page.w, s.page.cfg
        if s.sel == 'div[role="feed"]' and w.no_feed: raise PWTimeout("feed")
        if s.sel == "h1" and cfg and (cfg.get("h1_timeout") or cfg.get("sorry")): raise PWTimeout("h1")
    def count(s):
        cfg = s.page.cfg
        return 1 if ("recaptcha" in s.sel and ((cfg and cfg.get("captcha")) or (cfg is None and s.page.w.search_captcha))) else 0
    def click(s, timeout=None): raise PWTimeout("no consent dialog")

class FakePage:
    def __init__(s, w, ctx): s.w, s.ctx, s.url, s.cfg, s.handlers = w, ctx, "about:blank", None, {}
    def set_default_timeout(s, _): pass
    def set_default_navigation_timeout(s, _): pass
    def on(s, ev, h): s.handlers[ev] = h
    def goto(s, url, **kw):
        s.w.visited.append(url)
        if "/maps/search/" in url: s.url, s.cfg = url, None; return Resp()
        cfg = s.cfg = s.w.places[url]
        if cfg.get("on_visit"): cfg["on_visit"]()
        errs = cfg.get("goto_errors")
        if errs:
            e = errs.pop(0)
            if callable(e): e(s)
            raise e
        s.url = "https://www.google.com/sorry/index" if cfg.get("sorry") else url
        return Resp(cfg.get("status", 200))
    def locator(s, sel): return FakeLoc(s, sel)
    def get_by_role(s, *a, **k): return FakeLoc(s, "consent")
    def wait_for_selector(s, sel, **kw):
        if s.cfg and s.cfg.get("no_address"): raise PWTimeout("address")
    def evaluate(s, js, arg=None):
        return {"hrefs": s.w.links, "end": True} if js is sc.FEED_JS else s.cfg["raw"]

class FakeContext:
    def __init__(s, w, browser): s.w, s.browser = w, browser; w.contexts_opened += 1
    def route(s, pattern, handler): s.handler = handler
    def new_page(s): return FakePage(s.w, s)
    def close(s): s.w.contexts_closed += 1

class FakeBrowser:
    version = "fake-1.0"
    def __init__(s, w): s.w, s.connected, s.h = w, True, {}
    def on(s, ev, h): s.h[ev] = h
    def is_connected(s): return s.connected
    def die(s): s.connected = False; s.h["disconnected"](s)
    def new_context(s, **kw): s.ctx_kwargs = kw; return FakeContext(s.w, s)
    def close(s): s.connected = False

class FakePW:
    def __init__(s, w): s.w, s.chromium = w, s
    def launch(s, headless=True, args=None):
        if s.w.launch_fail > 0: s.w.launch_fail -= 1; raise PWError("launch failed")
        s.w.launches += 1; s.last_args = args; s.w.last_browser = FakeBrowser(s.w); return s.w.last_browser
    def __enter__(s): return s
    def __exit__(s, *a): return False

def raw(name="Alpha Realty", phone="+919845012345", site="https://a.example", **kw):
    d = dict(name=name, category="Real estate agency", item_id=f"phone:tel:{phone}" if phone else None, website=site,
             address="Address: 12 MG Road", rating="4,5", reviews="120 reviews", closed=False); d.update(kw); return d

def url(n): return f"https://www.google.com/maps/place/P{n}/data=!3d12.97{n}!4d77.64{n}?x=1"

def place(n, **kw):
    cfg = dict(raw=raw(name=f"Place {n}", phone=f"+91984501234{n}"))
    cfg.update(kw); return cfg

@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(sc, "STOP", False)
    monkeypatch.setattr(sc, "nap", lambda *a, **k: None)
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    monkeypatch.setattr(sc, "tree_rss_mb", lambda: None)
    yield
    sc.STOP = False

def go(monkeypatch, world, tmp_path, **kw):
    monkeypatch.setattr(sc, "sync_playwright", lambda: FakePW(world))
    ns = dict(query=["real estate"], location="Indiranagar", max=10, out=str(tmp_path / "o.json"), headful=False,
              skip_no_contact=False, resume=False, jsonl=True, skip_urls=None); ns.update(kw)
    return sc.run(argparse.Namespace(**ns)), ns["out"]

def saved(path): return json.load(open(path, encoding="utf-8"))["businesses"]

# ----------------------------------------------------------------------------- pure helpers
def test_parse_coords_and_phone():
    assert sc.parse_coords("x!3d12.97!4d77.64?y") == (12.97, 77.64)
    assert sc.parse_coords("nothing") == (None, None) and sc.parse_coords(None) == (None, None)
    assert sc.clean_phone("phone:tel:+919845012345") == "+919845012345"
    assert sc.clean_phone(None) is None and sc.clean_phone("authority") is None

def test_build_place_full_and_schema():
    p = sc.build_place(raw(), url(1), url(1))
    assert p["name"] == "Alpha Realty" and p["phone"] == "+919845012345" and p["rating"] == 4.5 and p["reviews"] == 120
    assert p["address"] == "12 MG Road" and (p["lat"], p["lng"]) == (12.971, 77.641)
    assert p["maps_url"] == url(1).split("?")[0] and p["permanently_closed"] is False
    b = sc.to_business(p, "real estate")
    assert set(b) == {"name", "category", "phone", "website", "address", "lat", "lng", "notes", "maps_url", "rating", "reviews"}
    assert b["notes"] == "Real estate agency | rating 4.5 (120 reviews)"

def test_build_place_edge_cases():
    assert sc.build_place(raw(name=None), url(1), url(1)) is None
    assert sc.build_place(raw(name="Results"), url(1), url(1)) is None
    p = sc.build_place(raw(phone=None, site=None, rating="n/a", reviews=None, closed=True), "https://x/search", "https://x/search")
    assert p["phone"] is None and p["rating"] is None and p["reviews"] is None and p["maps_url"] == "https://x/search"
    b = sc.to_business(p, "q")
    assert b["permanently_closed"] is True and "PERMANENTLY CLOSED" in b["notes"] and "phone" not in b

def test_save_is_atomic_and_load_survives_corruption(tmp_path):
    f = str(tmp_path / "o.json"); sc.save(f, [{"name": "A"}])
    assert saved(f) == [{"name": "A"}] and not os.path.exists(f + ".tmp")
    open(f, "w").write("{broken")
    assert sc.load_items(f) == []
    assert any(n.startswith("o.json.corrupt-") for n in os.listdir(tmp_path))      # moved aside, never overwritten

# ----------------------------------------------------------------------------- resource blocking / chromium args
@pytest.mark.parametrize("rtype,u,expected", [
    ("image", "https://x/a.png", True), ("media", "https://x/a.mp4", True), ("font", "https://fonts.gstatic.com/f.woff2", True),
    ("ping", "https://x/p", True),
    ("script", "https://www.googletagmanager.com/gtm.js", True), ("xhr", "https://www.google-analytics.com/collect", True),
    ("fetch", "https://www.google.com/gen_204?x=1", True), ("script", "https://doubleclick.net/a.js", True),
    ("document", "https://www.googletagmanager.com/ns.html", False),            # documents are never blocked
    ("document", "https://www.google.com/sorry/index", False),                  # CAPTCHA pages must always load
    ("script", "https://www.google.com/maps/_/js/k=maps", False), ("xhr", "https://www.google.com/search?tbm=map", False),
    ("fetch", "https://www.google.com/maps/preview/place", False), ("stylesheet", "https://www.google.com/maps/s.css", False),
    ("script", "https://www.gstatic.com/recaptcha/releases/x/recaptcha__en.js", False),
    ("fetch", "https://www.google.com/maps/vt/pb=!1m4", sc.BLOCK_TILES)])
def test_should_block(rtype, u, expected): assert sc.should_block(rtype, u) is expected

def test_chromium_args():
    a = sc.ARGS
    assert "--no-sandbox" in a and "--disable-dev-shm-usage" in a and "--disable-extensions" in a
    assert "--single-process" not in a and not any(x.startswith("--remote-debugging") for x in a)   # unstable / exposes a port
    heap = [int(x.split("=")[-1]) for x in a if x.startswith("--js-flags=--max-old-space-size=")]
    assert heap and heap[0] <= 256

def test_route_handler_counts_and_never_raises():
    class R:
        def __init__(s, t, u): s.request = type("Q", (), dict(resource_type=t, url=u))(); s.log = []
        def abort(s): s.log.append("abort")
        def continue_(s): s.log.append("continue")
    s = sc.Session(None, False)
    a, b = R("image", "https://x/a.png"), R("script", "https://www.google.com/maps/_/js/x")
    s._route(a); s._route(b)
    assert a.log == ["abort"] and b.log == ["continue"] and s.blocked_reqs == 1
    class Dead(R):
        def abort(s): raise PWError("closed")
    s._route(Dead("image", "https://x/a.png"))                                  # must swallow closed-page errors

# ----------------------------------------------------------------------------- blocked() / collect_links
def test_blocked_detection():
    p = FakePage(World({}), None); p.url = "https://www.google.com/sorry/index"; assert sc.blocked(p)
    p.url = "https://www.google.com/maps"; assert not sc.blocked(p)
    p.cfg = {"captcha": True}; assert sc.blocked(p)

def test_collect_links_dedupes_limits_and_stops_at_end():
    w = World({}); w.links = [url(1), url(2), url(2), url(3)]
    assert sc.collect_links(FakePage(w, None), 2) == [url(1), url(2)]

def test_collect_links_single_place_redirect():
    w = World({}, no_feed=True); p = FakePage(w, None); p.url = url(1)
    assert sc.collect_links(p, 5) == [url(1)]
    p.url = "https://www.google.com/maps/search/x"; assert sc.collect_links(p, 5) == []

# ----------------------------------------------------------------------------- full runs
def test_happy_path_protocol_and_output(monkeypatch, tmp_path, capsys):
    w = World({url(n): place(n) for n in (1, 2, 3)})
    code, out = go(monkeypatch, w, tmp_path)
    o = capsys.readouterr().out
    assert code == 0 and len(saved(out)) == 3
    assert "found 3 places" in o and "[1/3] Place 1 | +919845012341" in o
    results = [json.loads(l[7:]) for l in o.splitlines() if l.startswith("RESULT ")]
    assert [r["name"] for r in results] == ["Place 1", "Place 2", "Place 3"] and results == saved(out)
    assert w.launches == 1 and w.contexts_opened == 1 and w.contexts_closed == 1      # ONE browser, ONE context, closed
    assert not any("about:blank" in v for v in w.visited)                             # no redundant navigation

def test_context_kwargs_isolate_service_workers(monkeypatch, tmp_path):
    w = World({url(1): place(1)}); go(monkeypatch, w, tmp_path)
    assert w.last_browser.ctx_kwargs["service_workers"] == "block"

def test_jsonl_flag_off_and_skip_no_contact(monkeypatch, tmp_path, capsys):
    w = World({url(1): place(1), url(2): dict(raw=raw(name="NoContact", phone=None, site=None))})
    code, out = go(monkeypatch, w, tmp_path, jsonl=False, skip_no_contact=True)
    o = capsys.readouterr().out
    assert [b["name"] for b in saved(out)] == ["Place 1"] and "RESULT" not in o and "skipped (no contact): NoContact" in o

def test_skip_urls_and_resume(monkeypatch, tmp_path):
    skip = tmp_path / "skip.txt"; skip.write_text(url(1).split("?")[0] + "\n")
    out = str(tmp_path / "o.json"); sc.save(out, [{"name": "Old", "maps_url": url(2).split("?")[0]}])
    w = World({url(n): place(n) for n in (1, 2, 3)})
    code, _ = go(monkeypatch, w, tmp_path, skip_urls=str(skip), resume=True)
    assert code == 0 and [v for v in w.visited if "/maps/place/" in v] == [url(3)]
    assert [b["name"] for b in saved(out)] == ["Old", "Place 3"]

def test_captcha_mid_run_stops_with_code_3_and_keeps_partial(monkeypatch, tmp_path, capsys):
    w = World({url(1): place(1), url(2): place(2, captcha=True), url(3): place(3)})
    code, out = go(monkeypatch, w, tmp_path)
    assert code == 3 and "STOPPED: CAPTCHA" in capsys.readouterr().err
    assert [b["name"] for b in saved(out)] == ["Place 1"] and url(3) not in w.visited      # no retry, no evasion, no further requests

def test_sorry_redirect_is_detected_immediately_without_waiting_for_h1(monkeypatch, tmp_path):
    waited = []
    monkeypatch.setattr(FakeLoc, "wait_for", lambda self, timeout=None: waited.append(self.sel))
    w = World({url(1): place(1, sorry=True)}); code, _ = go(monkeypatch, w, tmp_path)
    assert code == 3 and "h1" not in waited                                    # no 20 s h1 wait on a block page

def test_node_driver_heap_is_capped_unless_user_set_it(monkeypatch, tmp_path):
    monkeypatch.delenv("NODE_OPTIONS", raising=False); go(monkeypatch, World({url(1): place(1)}), tmp_path)
    assert os.environ["NODE_OPTIONS"] == f"--max-old-space-size={sc.NODE_HEAP_MB}"
    monkeypatch.setenv("NODE_OPTIONS", "--foo"); go(monkeypatch, World({url(1): place(1)}), tmp_path)
    assert os.environ["NODE_OPTIONS"] == "--foo"

def test_sorry_page_without_h1_is_caught(monkeypatch, tmp_path):
    """Regression: previously an h1 timeout on a /sorry/ page returned None and the run carried on."""
    w = World({url(1): place(1, sorry=True, h1_timeout=True), url(2): place(2)})
    code, _ = go(monkeypatch, w, tmp_path)
    assert code == 3 and url(2) not in w.visited

def test_recaptcha_iframe_on_place_without_h1_is_caught(monkeypatch, tmp_path):
    """URL looks normal, h1 never appears, but a recaptcha iframe is present: must stop, not skip-and-continue."""
    w = World({url(1): place(1, captcha=True, h1_timeout=True), url(2): place(2)})
    code, _ = go(monkeypatch, w, tmp_path)
    assert code == 3 and url(2) not in w.visited

def test_captcha_on_search_page(monkeypatch, tmp_path):
    w = World({url(1): place(1)}, no_feed=True, search_captcha=True)
    code, _ = go(monkeypatch, w, tmp_path)
    assert code == 3 and w.visited and all("/maps/place/" not in v for v in w.visited)

def test_http_error_status_is_logged(monkeypatch, tmp_path, capsys):
    go(monkeypatch, World({url(1): place(1, status=429)}), tmp_path)
    assert "WARN HTTP 429" in capsys.readouterr().out

def test_browser_crash_is_healed_and_place_retried(monkeypatch, tmp_path):
    """Chromium dies mid-navigation (OOM-kill): disconnect event fires, place is retried on a fresh browser."""
    w = World({url(1): place(1), url(2): place(2)})
    orig, state = FakePage.goto, {"killed": False}
    def goto(self, u, **kw):
        if u == url(1) and not state["killed"]:
            state["killed"] = True; self.ctx.browser.die(); raise PWError("Target closed")
        return orig(self, u, **kw)
    monkeypatch.setattr(FakePage, "goto", goto)
    code, out = go(monkeypatch, w, tmp_path)
    assert code == 0 and [b["name"] for b in saved(out)] == ["Place 1", "Place 2"] and w.launches == 2

def test_timeout_recycles_context_not_browser(monkeypatch, tmp_path):
    w = World({url(1): place(1, goto_errors=[PWTimeout("slow")]), url(2): place(2)})
    code, out = go(monkeypatch, w, tmp_path)
    assert code == 0 and len(saved(out)) == 2 and w.launches == 1 and w.contexts_opened == 2     # cheap recovery

def test_consecutive_failures_abort_with_code_4(monkeypatch, tmp_path):
    ps = {url(n): place(n, goto_errors=[PWTimeout("x"), PWTimeout("x")]) for n in range(1, 9)}
    w = World(ps); w.links = list(ps)
    code, out = go(monkeypatch, w, tmp_path)
    assert code == 4 and sum("/maps/place/" in v for v in w.visited) == 2 * sc.MAX_CONSEC_FAIL and saved(out) == []

def test_launch_failure_exits_4_and_still_writes_output(monkeypatch, tmp_path):
    code, out = go(monkeypatch, World({url(1): place(1)}, launch_fail=3), tmp_path)
    assert code == 4 and saved(out) == []

def test_stop_flag_finishes_current_place_then_saves(monkeypatch, tmp_path):
    w = World({url(1): place(1), url(2): place(2, on_visit=lambda: setattr(sc, "STOP", True)), url(3): place(3)})
    code, out = go(monkeypatch, w, tmp_path)
    assert code == 0 and [b["name"] for b in saved(out)] == ["Place 1", "Place 2"] and url(3) not in w.visited
    assert w.contexts_closed == w.contexts_opened                              # context closed on the way out

def test_cleanup_on_unexpected_exception(monkeypatch, tmp_path):
    w = World({url(1): place(1), url(2): place(2, on_visit=lambda: 1 / 0)})
    with pytest.raises(ZeroDivisionError): go(monkeypatch, w, tmp_path)
    assert len(saved(str(tmp_path / "o.json"))) == 1 and w.contexts_closed == w.contexts_opened     # partial kept, nothing leaked

def test_signal_handler_two_stage(monkeypatch):
    sc._sig(15, None); assert sc.STOP is True
    with pytest.raises(KeyboardInterrupt): sc._sig(15, None)

# ----------------------------------------------------------------------------- recycling policy
def mk_session(monkeypatch, rss=None):
    w = World({}); monkeypatch.setattr(sc, "tree_rss_mb", lambda: rss[0] if rss else None)
    s = sc.Session(FakePW(w), False); s.ensure(); return s, w

def test_no_recycle_while_healthy(monkeypatch):
    s, w = mk_session(monkeypatch, [100.0]); s.n = 5; s.maybe_recycle()
    assert w.launches == 1 and w.contexts_opened == 1

def test_context_recycled_by_count_then_browser_after_n_contexts(monkeypatch):
    s, w = mk_session(monkeypatch)
    for _ in range(sc.BROWSER_EVERY_CONTEXTS - 1): s.n = sc.CONTEXT_EVERY; s.maybe_recycle()
    assert w.launches == 1 and s.contexts == sc.BROWSER_EVERY_CONTEXTS
    s.n = sc.CONTEXT_EVERY; s.maybe_recycle(); assert w.launches == 2 and s.contexts == 1

def test_soft_rss_gives_new_context_hard_rss_relaunches(monkeypatch):
    rss = [sc.RSS_SOFT_MB + 1.0]; s, w = mk_session(monkeypatch, rss)
    s.maybe_recycle(); assert w.launches == 1 and w.contexts_opened == 2
    rss[0] = sc.RSS_HARD_MB + 1.0; s.maybe_recycle(); assert w.launches == 2 and s.peak_rss >= sc.RSS_HARD_MB

def test_ensure_heals_crashed_page_and_dead_browser(monkeypatch):
    s, w = mk_session(monkeypatch)
    s._crashed(); s.ensure(); assert w.launches == 1 and w.contexts_opened == 2 and not s.page_crashed
    w.last_browser.die(); assert s.dead; s.ensure(); assert w.launches == 2 and not s.dead

def test_close_is_idempotent_and_quiet(monkeypatch, capsys):
    s, w = mk_session(monkeypatch); s.close(); s.close()
    assert w.contexts_closed == 1 and "disconnected/crashed" not in capsys.readouterr().out

def test_pageerror_log_is_capped(monkeypatch, capsys):
    s, _ = mk_session(monkeypatch)
    for i in range(50): s._pageerror(Exception(f"e{i}"))
    assert capsys.readouterr().out.count("pageerror:") == 5

# ----------------------------------------------------------------------------- single-instance + main()
def test_single_instance_lock(tmp_path):
    f = str(tmp_path / "l.lock"); a, b = sc.SingleInstance(f), sc.SingleInstance(f)
    assert a.acquire() and not b.acquire()
    a.release(); assert b.acquire(); b.release()

def run_main(monkeypatch, tmp_path, runner):
    monkeypatch.setenv("SCRAPER_LOCK_FILE", str(tmp_path / "l.lock")); monkeypatch.setattr(sc, "run", runner)
    monkeypatch.setattr(sys, "argv", ["maps_scraper.py", "-q", "x", "-l", "y", "-o", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit) as e: sc.main()
    return e.value.code

def test_main_busy_exits_5_without_running(monkeypatch, tmp_path):
    held = sc.SingleInstance(str(tmp_path / "l.lock")); assert held.acquire()
    called = []
    assert run_main(monkeypatch, tmp_path, lambda a: called.append(1) or 0) == 5 and not called
    held.release()

def test_main_exit_codes(monkeypatch, tmp_path):
    assert run_main(monkeypatch, tmp_path, lambda a: 3) == 3
    assert run_main(monkeypatch, tmp_path, lambda a: (_ for _ in ()).throw(RuntimeError("boom"))) == 1
    assert run_main(monkeypatch, tmp_path, lambda a: (_ for _ in ()).throw(KeyboardInterrupt())) == 130
    assert not SingleInstanceLeak(tmp_path)

def SingleInstanceLeak(tmp_path):                       # lock must be free after main() returns
    s = sc.SingleInstance(str(tmp_path / "l.lock")); ok = s.acquire(); s.release(); return not ok
