import os, sys, json, textwrap, subprocess, pytest, psutil
os.environ.setdefault("WORKER_MODE", "inline")
import pipeline as lp

needs_db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")
live = pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 (needs internet)")
R = lambda n: 'RESULT {"name":"ZZTEST%s","phone":"+91987654321%s","maps_url":"https://www.google.com/maps/place/x%s/data=!1s0x%s:0x%s"}' % (n, n, n, n, n)

@pytest.fixture
def db_clean():
    yield
    c = lp.db(); c.execute("DELETE FROM leads WHERE name LIKE 'ZZTEST%'")
    c.execute("DELETE FROM run_events WHERE run_id IN (SELECT id FROM runs WHERE query LIKE 'ZZTEST%')")
    c.execute("DELETE FROM runs WHERE query LIKE 'ZZTEST%'"); c.commit(); c.close()

def job(tmp_path, monkeypatch, body, **kw):
    f = tmp_path / "fake.py"; f.write_text(textwrap.dedent(body))
    monkeypatch.setattr(lp, "SCRAPER", str(f))
    for k, v in kw.items(): monkeypatch.setattr(lp, k, v)
    rid = lp.enqueue_scrape("ZZTEST q", "loc", 5)
    return rid, lp.claim_job("t:1", rid)

def row(rid):
    c = lp.db(); r = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    ev = [e["text"] for e in c.execute("SELECT text FROM run_events WHERE run_id=? ORDER BY id", (rid,)).fetchall()]
    c.close(); return r, ev

# ---- offline ----
def test_osm_selectors():
    assert len(lp.osm_selectors("PG")) >= 3 and lp.osm_selectors("estate agent") and lp.osm_selectors("shop=bakery")
    assert lp.osm_selectors("zzz") is None

def test_google_pagination_and_errors(monkeypatch):
    class Resp:
        def __init__(s, js, code=200): s.js, s.status_code, s.text = js, code, str(js)
        def json(s): return s.js
    pl = lambda i: {"id": f"id{i}", "displayName": {"text": f"P{i}"}, "internationalPhoneNumber": "+91 98765 43210"}
    seq = iter([Resp({"places": [pl(1)], "nextPageToken": "t"}), Resp({"places": [pl(2)]})])
    monkeypatch.setattr(lp.requests, "post", lambda *a, **k: next(seq)); cnt = [0]
    assert len(lp.fetch_google("k", "q", 1, 1, 1000, 3, cnt)) == 2 and cnt[0] == 2
    monkeypatch.setattr(lp.requests, "post", lambda *a, **k: Resp({"error": {"status": "PERMISSION_DENIED", "message": "billing"}}, 403))
    with pytest.raises(RuntimeError, match="billing"): lp.fetch_google("k", "q", 1, 1, 1000)
    with pytest.raises(RuntimeError, match="key missing"): lp.fetch_google("", "q", 1, 1, 1000)

def test_overpass_failover_and_unavailable(monkeypatch):
    class Resp:
        def __init__(s, code, js): s.status_code, s.js, s.text = code, js, ""
        def json(s): return s.js
    calls = []
    def post(url, **k):
        calls.append(url)
        return Resp(504, {}) if len(calls) < 2 else Resp(200, {"elements": [{"type": "node", "id": 1, "lat": 1, "lon": 2, "tags": {"name": "A"}}, {"type": "node", "id": 2, "tags": {}}]})
    monkeypatch.setattr(lp.requests, "post", post); monkeypatch.setattr(lp.time, "sleep", lambda s: None)
    out = lp.fetch_osm("real estate", 1, 1, 1000)
    assert [r["name"] for r in out] == ["A"] and lp.LAST_OSM["unnamed"] == 1
    monkeypatch.setattr(lp.requests, "post", lambda *a, **k: Resp(504, {}))
    with pytest.raises(lp.OSMUnavailable): lp.fetch_osm("real estate", 1, 1, 1000)

def test_playwright_launches_offline():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]); p = b.new_page()
        p.set_content("<h1>ok</h1>"); assert p.inner_text("h1") == "ok"; b.close()

# ---- DB-backed (Supabase or local postgres; local: DB_SSLMODE=disable) ----
@needs_db
def test_supabase_connectivity():
    c = lp.db(); assert c.execute("SELECT 1").fetchone()[0] == 1; c.close()

@needs_db
def test_osm_no_contact_saved_and_outcomes(monkeypatch, db_clean):
    rows = [dict(id=f"o:nodeZZ{i}", source="osm", name=f"ZZTEST{i}", category="ZZTEST q", status="active") for i in (1, 2)]
    monkeypatch.setattr(lp, "fetch_osm", lambda *a: rows)
    assert lp.run("ZZTEST q", 1, 1, 1000, source="osm")[:2] == (2, 2)
    monkeypatch.setattr(lp, "fetch_osm", lambda *a: [])
    lp.run("ZZTEST q", 1, 1, 1000, source="osm")                       # zero results is NOT a failure
    def down(*a): raise lp.OSMUnavailable("all down")
    monkeypatch.setattr(lp, "fetch_osm", down)
    with pytest.raises(lp.OSMUnavailable): lp.run("ZZTEST q", 1, 1, 1000, source="osm")
    c = lp.db(); sts = [r[0] for r in c.execute("SELECT status FROM runs WHERE query='ZZTEST q' ORDER BY id")]; c.close()
    assert sts == ["done", "done", "failed"]

@needs_db
def test_crash_keeps_partial_and_logs_stderr(tmp_path, monkeypatch, db_clean):
    rid, j = job(tmp_path, monkeypatch, f"""
        import sys, os
        print({R(1)!r}, flush=True); print({R(2)!r}, flush=True)
        sys.stderr.write("boom-visible\\n"); sys.stderr.flush(); os._exit(9)""", MAX_ATTEMPTS=1)
    lp.execute_job(j); r, ev = row(rid)
    assert r["status"] == "partial" and r["fetched"] == 2 and "9" in r["error"] and any("boom-visible" in e for e in ev)

@needs_db
def test_hang_is_killed_without_orphans(tmp_path, monkeypatch, db_clean):
    rid, j = job(tmp_path, monkeypatch, f"""
        import subprocess, sys, time
        c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        print({R(3)!r}, flush=True); print("CHILD", c.pid, flush=True); time.sleep(120)""", MAX_ATTEMPTS=1, IDLE_TIMEOUT=3)
    lp.execute_job(j); r, ev = row(rid)
    pid = int(next(e for e in ev if e.startswith("CHILD")).split()[1])
    assert r["status"] == "partial" and "hung" in r["error"] and not psutil.pid_exists(pid)

@needs_db
def test_restart_resumes_without_losing_leads(tmp_path, monkeypatch, db_clean):
    body = f"""
        import sys, os
        a = sys.argv; skip = open(a[a.index("--skip-urls") + 1]).read().split()
        if skip: print("SKIPCOUNT", len(skip), flush=True); print({R(6)!r}, flush=True); sys.exit(0)
        print({R(4)!r}, flush=True); print({R(5)!r}, flush=True); os._exit(9)"""
    rid, j = job(tmp_path, monkeypatch, body, MAX_ATTEMPTS=2)
    assert lp.execute_job(j) == "queued"                                # crash -> re-queued
    assert lp.execute_job(lp.claim_job("t:2", rid)) == "done"           # resumed
    r, ev = row(rid)
    assert r["fetched"] == 3 and any("SKIPCOUNT 2" in e for e in ev)

@needs_db
def test_reap_stale_marks_interrupted(monkeypatch, db_clean):
    c = lp.db(); rid = c.execute("INSERT INTO runs(at,query,source,status,heartbeat_at,attempts) VALUES(?,?,?,?,?,?) RETURNING id",
        ("2020-01-01T00:00:00", "ZZTEST q", "osm", "running", "2020-01-01T00:00:00", 1)).fetchone()[0]; c.commit(); c.close()
    assert lp.reap_stale() >= 1
    r, _ = row(rid); assert r["status"] == "failed" and "Interrupted" in r["error"]

# ---- live ----
@live
def test_live_overpass(): assert isinstance(lp.fetch_osm("real estate", 28.4089, 77.3178, 5000), list)

@live
@pytest.mark.skipif(not os.getenv("GOOGLE_API_KEY"), reason="no GOOGLE_API_KEY")
def test_live_google():
    cnt = [0]; assert lp.fetch_google(os.environ["GOOGLE_API_KEY"], "real estate", 28.4089, 77.3178, 3000, 1, cnt) and cnt[0] == 1

@live
def test_live_maps_scrape(tmp_path):
    p = subprocess.run([sys.executable, "-u", lp.SCRAPER, "-q", "real estate", "-l", "NIT Faridabad", "-n", "3", "--jsonl",
                        "-o", str(tmp_path / "o.json")], capture_output=True, text=True, timeout=300)
    assert p.returncode in (0, 3), p.stdout + p.stderr       # 3 = CAPTCHA stop (acceptable, never bypassed)
    if p.returncode == 0: assert "RESULT " in p.stdout