"""Wiring tests for pipeline.py: sources are separate modules, the pipeline only orchestrates + persists. DB is stubbed."""
import threading
import pytest
import pipeline as pl
import google_source as gs
import osm_source as os_

class Cur:
    def __init__(s, row=None): s.row = row
    def fetchone(s): return s.row
    def fetchall(s): return []

class FakeDB:
    """Records every statement. Answers just enough for run()/save_row()."""
    def __init__(s): s.sql, s.closed = [], False
    def execute(s, sql, params=None):
        s.sql.append((sql, params))
        if "RETURNING id" in sql: return Cur((7,))
        if "SUM(calls)" in sql: return Cur((0,))
        return Cur(None)                               # SELECT lead -> not found => insert path
    def commit(s): pass
    def close(s): s.closed = True
    def runs_update(s): return [p for q, p in s.sql if q.startswith("UPDATE runs SET fetched")][-1]
    def inserts(s): return [p for q, p in s.sql if q.startswith("INSERT INTO leads")]

@pytest.fixture
def fdb(monkeypatch):
    d = FakeDB(); monkeypatch.setattr(pl, "db", lambda: d); return d

def test_pure_helpers():
    assert pl.norm_phone("098450 12345") == ("+919845012345", 1) and pl.norm_phone("nope") == (None, 0)
    assert pl.score(dict(status="STALE", phone="x")) == 0
    assert pl.score(dict(phone="+91", is_mobile=1, website="w", email="e", rating=4, reviews=9)) == 100
    assert pl.scrape_id({"maps_url": "x!1s0xabc:0x123!8m2"}) == "s:0xabc:0x123" and pl.scrape_id({"name": "A"}).startswith("s:")

def test_sources_are_reexported_from_their_own_modules():
    assert pl.fetch_google is gs.fetch_google and pl.fetch_osm is os_.fetch_osm and pl.OSMUnavailable is os_.OSMUnavailable
    assert not hasattr(gs, "psycopg2") and not hasattr(os_, "psycopg2")            # sources know nothing about the DB

def test_run_google_persists_rows_and_bills_calls(monkeypatch, fdb):
    rows = [dict(id="g:1", source="google", name="A", category="gym", phone="+919845012345", website=None),
            dict(id="g:2", source="google", name="B", category="gym", phone=None, website=None)]
    monkeypatch.setattr(pl, "fetch_google", lambda *a, **k: gs.GoogleResult(rows=rows, calls=2, warning="page 3 failed"))
    saved, added, changed = pl.run("gym", 1, 2, 3000, source="google", key="K")
    assert (saved, added, changed) == (2, 2, 0) and len(fdb.inserts()) == 2 and fdb.closed
    assert fdb.runs_update()[3] == 2 and fdb.runs_update()[4] == "done"             # calls=2, status=done
    assert pl.LAST_WARNING == "page 3 failed"

def test_run_google_failure_still_records_billable_calls(monkeypatch, fdb):
    def boom(*a, **k): raise gs.GoogleError("quota", calls=3)
    monkeypatch.setattr(pl, "fetch_google", boom)
    with pytest.raises(gs.GoogleError): pl.run("gym", 1, 2, 3000, source="google", key="K")
    u = fdb.runs_update(); assert u[3] == 3 and u[4] == "failed" and "quota" in u[6]

def test_run_google_monthly_cap(monkeypatch, fdb):
    monkeypatch.setattr(pl, "fetch_google", lambda *a, **k: pytest.fail("must not call Google over the cap"))
    with pytest.raises(RuntimeError, match="cap reached"): pl.run("gym", 1, 2, 3000, source="google", key="K", cap=2, max_pages=3)

def test_run_osm_success_and_outage(monkeypatch, fdb):
    rows = [dict(id="o:node1", source="osm", name="Gym", category="gym", phone="+919845012345")]
    monkeypatch.setattr(pl, "fetch_osm", lambda *a, **k: os_.OSMResult(rows=rows, mirror="m.example", raw=5, unnamed=4))
    assert pl.run("gym", 1, 2, 3000, source="osm")[0] == 1 and pl.LAST_OSM["mirror"] == "m.example" and pl.LAST_OSM["unnamed"] == 4
    def down(*a, **k): raise os_.OSMUnavailable("all down")
    monkeypatch.setattr(pl, "fetch_osm", down)
    with pytest.raises(os_.OSMUnavailable): pl.run("gym", 1, 2, 3000, source="osm")
    assert fdb.runs_update()[4] == "failed"
    assert any(p and p[2] == "error" and "OSM UNAVAILABLE" in p[3] for q, p in fdb.sql if q.startswith("INSERT INTO run_events"))

def test_run_limit_prefers_contactable_rows(monkeypatch, fdb):
    rows = [dict(id="o:1", source="osm", name="NoContact", category="c"), dict(id="o:2", source="osm", name="HasSite", category="c", website="w")]
    monkeypatch.setattr(pl, "fetch_osm", lambda *a, **k: os_.OSMResult(rows=rows))
    pl.run("c", 1, 2, 100, source="osm", limit=1)
    assert [p["name"] for p in fdb.inserts()] == ["HasSite"]

def test_job_slot_is_single_and_reentrant():
    assert pl.EXIT_BUSY == 5
    got = []
    with pl._JOB_SLOT:
        with pl._JOB_SLOT: got.append("reentrant ok")                # run_scrape -> execute_job on the same thread
        t = threading.Thread(target=lambda: got.append(pl._JOB_SLOT.acquire(timeout=0.2)))
        t.start(); t.join()
    assert got == ["reentrant ok", False]                            # a second thread cannot start a second scrape
