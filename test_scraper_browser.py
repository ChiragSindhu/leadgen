"""Integration test: REAL Chromium + real Playwright against a local HTTPS server that imitates Google Maps markup.
Validates the DOM extractors (FEED_JS / PLACE_JS), resource blocking, CAPTCHA stop and cleanup end-to-end.
Auto-skips when Chromium or openssl is unavailable. Never contacts Google."""
import argparse, json, shutil, ssl, subprocess, threading, collections
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
import maps_scraper as sc

PLACE = "https://www.google.com/maps/place/P{n}/data=!3d12.97{n}!4d77.64{n}!1s0x{n}:0x{n}?x=1"
HITS = collections.Counter(); CAPTCHA_ON = set()

class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def _send(s, body, ctype="text/html", code=200, loc=None):
        s.send_response(code); s.send_header("Content-Type", ctype)
        if loc: s.send_header("Location", loc)
        s.end_headers(); s.wfile.write(body.encode() if isinstance(body, str) else body)
    def do_GET(s):
        path = s.path.split("?")[0]; HITS[path] += 1
        if path.startswith("/maps/search/"):
            cards = "".join(f'<div><a href="{PLACE.format(n=n)}">P{n}</a></div>' for n in (1, 2, 3))
            return s._send('<html><body><div role="feed" style="height:300px;overflow:auto">' + cards +
                           '<div><span>You\'ve reached the end of the list.</span></div></div><img src="/img.png">'
                           "<script>fetch('/gen_204?x=1');fetch('/maps/preview/x').then(r=>r.text())</script></body></html>")
        if path.startswith("/maps/place/"):
            n = path.split("/P")[1][0]
            if n in CAPTCHA_ON: return s._send("", code=302, loc="https://www.google.com/sorry/index?continue=x")
            return s._send(f'<html><body><h1 class="DUwDvf">Place {n}</h1><button jsaction="pane.rating.category">Gym</button>'
                f'<button data-item-id="address" aria-label="Address: {n} MG Road"></button>'
                f'<button data-item-id="phone:tel:+91984501234{n}" aria-label="Phone"></button>'
                f'<a data-item-id="authority" href="https://p{n}.example"></a>'
                '<div class="F7nice"><span aria-hidden="true">4,5</span><span aria-label="120 reviews"></span></div>'
                '<img src="/img.png"><script>fetch("/gen_204");fetch("/maps/preview/place")</script></body></html>')
        if path.startswith("/sorry/"): return s._send("<html><body><p>unusual traffic</p></body></html>", code=429)
        if path == "/img.png": return s._send(b"\x89PNG", "image/png")
        s._send("ok", "text/plain")

@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if not shutil.which("openssl"): pytest.skip("openssl not available")
    d = tmp_path_factory.mktemp("tls"); crt, key = str(d / "c.pem"), str(d / "k.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "1", "-subj", "/CN=www.google.com"],
                   check=True, capture_output=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(crt, key); srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start(); yield srv.server_address[1]; srv.shutdown()

@pytest.fixture
def env(monkeypatch, server):
    if sc.sync_playwright is None: pytest.skip("playwright not installed")
    try:
        with sc.sync_playwright() as pw: pw.chromium.launch(args=sc.ARGS).close()
    except Exception as e: pytest.skip(f"chromium unavailable: {str(e)[:80]}")
    HITS.clear(); CAPTCHA_ON.clear(); monkeypatch.setattr(sc, "STOP", False); monkeypatch.setattr(sc, "nap", lambda *a, **k: None)
    monkeypatch.setattr(sc, "ARGS", sc.ARGS + [f"--host-resolver-rules=MAP www.google.com 127.0.0.1:{server}", "--ignore-certificate-errors"])
    return server

def go(tmp_path, **kw):
    ns = dict(query=["gym"], location="Test", max=10, out=str(tmp_path / "o.json"), headful=False, skip_no_contact=False,
              resume=False, jsonl=False, skip_urls=None); ns.update(kw)
    return sc.run(argparse.Namespace(**ns)), json.load(open(ns["out"]))["businesses"]

def test_real_browser_end_to_end(env, tmp_path):
    code, items = go(tmp_path)
    assert code == 0 and [i["name"] for i in items] == ["Place 1", "Place 2", "Place 3"]
    i = items[0]
    assert i["phone"] == "+919845012341" and i["website"] == "https://p1.example" and i["address"] == "1 MG Road"
    assert (i["lat"], i["lng"]) == (12.971, 77.641) and i["rating"] == 4.5 and i["reviews"] == 120
    assert i["notes"] == "Gym | rating 4.5 (120 reviews)" and i["maps_url"] == PLACE.format(n=1).split("?")[0]

def test_real_browser_blocks_noise_but_keeps_xhr(env, tmp_path):
    go(tmp_path)
    assert HITS["/img.png"] == 0 and HITS["/gen_204"] == 0                    # image + telemetry never leave the browser
    assert HITS["/maps/preview/place"] == 3 and HITS["/maps/preview/x"] >= 1  # essential fetch/XHR untouched

def test_real_browser_captcha_redirect_stops_with_code_3(env, tmp_path, capsys):
    CAPTCHA_ON.add("2")
    code, items = go(tmp_path)
    assert code == 3 and [i["name"] for i in items] == ["Place 1"] and "STOPPED: CAPTCHA" in capsys.readouterr().err
    assert not any(p.endswith("P3/data=!3d12.973!4d77.643!1s0x3:0x3") for p in HITS)

def test_real_browser_leaves_no_chromium_behind(env, tmp_path):
    import psutil
    before = {p.pid for p in psutil.Process().children(recursive=True)}
    go(tmp_path)
    leaked = [p for p in psutil.Process().children(recursive=True) if p.pid not in before and p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
    assert not leaked, [p.name() for p in leaked]
