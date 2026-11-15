"""Tests for osm_source.py. HTTP is mocked; nothing touches the network."""
import pytest
import osm_source as osm

class R:
    def __init__(s, status=200, js=None, text=""): s.status_code, s._js, s.text = status, js, text
    def json(s):
        if s._js is None: raise ValueError("no json")
        return s._js

@pytest.fixture(autouse=True)
def nosleep(monkeypatch): monkeypatch.setattr(osm.time, "sleep", lambda s: None)

def el(i, name="Gym One", typ="node", **tags):
    e = {"type": typ, "id": i, "lat": 12.97, "lon": 77.64, "tags": {"name": name, **tags}} if typ == "node" else \
        {"type": typ, "id": i, "center": {"lat": 1.5, "lon": 2.5}, "tags": {"name": name, **tags}}
    if name is None: e["tags"].pop("name")
    return e

def patch_post(monkeypatch, responder):
    calls = []
    def post(url, data=None, headers=None, timeout=None):
        calls.append((url, data, headers, timeout)); return responder(url, len(calls))
    monkeypatch.setattr(osm.requests, "post", post); return calls

# ---- selectors
def test_selectors_known_alias_raw_and_unknown():
    assert osm.osm_selectors("gym") == osm.OSM_TAGS["gym"]
    assert osm.osm_selectors("  Realtor ") == osm.OSM_TAGS["real estate"]
    assert osm.osm_selectors("shop=bakery") == ['["shop"="bakery"]']
    assert osm.osm_selectors("shop=a|b") == ['["shop"~"^(a|b)$"]']
    assert osm.osm_selectors("best real estate offices") == osm.OSM_TAGS["real estate"]    # substring match
    assert osm.osm_selectors("zzz") is None and osm.osm_selectors("pg") == osm.OSM_TAGS["pg"]

def test_build_query_shape():
    q = osm.build_query(['["amenity"="cafe"]'], 12.9, 77.6, 2500.7)
    assert q == '[out:json][timeout:60];(nwr["amenity"="cafe"](around:2500,12.9,77.6););out center tags;'

# ---- parsing
def test_parse_elements_names_center_address_and_contacts():
    rows, unnamed = osm.parse_elements([
        el(1, phone="+91 98450 12345", website="https://g.example", email="a@b.co", **{"addr:housenumber": "5", "addr:street": "MG Rd"}),
        el(2, typ="way", **{"contact:mobile": "9845098450", "addr:full": "Full Addr"}),
        el(3, name=None), el(4, name="   ")], "gym")
    assert unnamed == 2 and [r["id"] for r in rows] == ["o:node1", "o:way2"]
    a, b = rows
    assert a["address"] == "5 MG Rd" and a["phone"] == "+91 98450 12345" and a["email"] == "a@b.co" and a["source"] == "osm"
    assert (b["lat"], b["lng"], b["address"], b["phone"]) == (1.5, 2.5, "Full Addr", "9845098450")
    assert b["maps_url"] == "https://www.openstreetmap.org/way/2" and b["status"] == "active" and b["category"] == "gym"

def test_address_none_when_no_parts():
    rows, _ = osm.parse_elements([el(1)], "gym"); assert rows[0]["address"] is None

# ---- fetching / mirrors
def test_success_first_mirror(monkeypatch):
    calls = patch_post(monkeypatch, lambda u, n: R(js={"elements": [el(1), el(2, name=None)]}))
    r = osm.fetch_osm("gym", 12.9, 77.6, 3000)
    assert r.mirror == "overpass-api.de" and r.raw == 2 and r.unnamed == 1 and len(r.rows) == 1 and len(calls) == 1
    assert calls[0][2] == osm.UA and "leisure" in calls[0][1]["data"]

def test_falls_over_to_next_mirror(monkeypatch):
    def resp(u, n): return R(status=504, text="Gateway Timeout") if "overpass-api.de" in u else R(js={"elements": [el(1)]})
    calls = patch_post(monkeypatch, resp)
    r = osm.fetch_osm("gym", 1, 2, 3000)
    assert r.mirror == "overpass.private.coffee" and len(r.rows) == 1 and len(calls) == 3      # 2 tries on mirror 1, then mirror 2

def test_network_exception_then_recovery(monkeypatch):
    def resp(u, n):
        if n == 1: raise ConnectionError("reset")
        return R(js={"elements": [el(1)]})
    patch_post(monkeypatch, resp); assert osm.fetch_osm("gym", 1, 2, 3000).mirror == "overpass-api.de"

def test_runtime_error_remark_with_no_elements_is_a_failure_not_zero_results(monkeypatch):
    def resp(u, n): return R(js={"elements": [], "remark": "runtime error: Query timed out"}) if "overpass-api.de" in u else R(js={"elements": [el(1)]})
    patch_post(monkeypatch, resp); assert osm.fetch_osm("gym", 1, 2, 3000).mirror != "overpass-api.de"

def test_genuine_zero_results_is_not_an_outage(monkeypatch):
    patch_post(monkeypatch, lambda u, n: R(js={"elements": []}))
    r = osm.fetch_osm("gym", 1, 2, 3000); assert r.rows == [] and r.raw == 0

def test_all_mirrors_down_raises_unavailable(monkeypatch):
    calls = patch_post(monkeypatch, lambda u, n: R(status=429, text="busy"))
    with pytest.raises(osm.OSMUnavailable, match=rf"All {len(osm.OVERPASS)} Overpass servers failed.*429"):
        osm.fetch_osm("gym", 1, 2, 3000)
    assert len(calls) == 2 * len(osm.OVERPASS)

def test_unavailable_is_distinguishable_from_bad_category(monkeypatch):
    patch_post(monkeypatch, lambda u, n: R(js={"elements": []}))
    with pytest.raises(RuntimeError, match="unknown category") as e: osm.fetch_osm("zzz", 1, 2, 3000)
    assert not isinstance(e.value, osm.OSMUnavailable)

def test_custom_mirrors_and_no_shared_state(monkeypatch):
    calls = patch_post(monkeypatch, lambda u, n: R(js={"elements": [el(1)]}))
    a = osm.fetch_osm("gym", 1, 2, 3000, mirrors=["https://m1.example/api"])
    b = osm.fetch_osm("cafe", 1, 2, 3000, mirrors=["https://m2.example/api"])
    assert (a.mirror, b.mirror) == ("m1.example", "m2.example") and a.rows[0]["category"] == "gym" and b.rows[0]["category"] == "cafe"
