"""Tests for google_source.py. HTTP is mocked; no key, no billing, no network."""
import pytest, requests
import google_source as g

class R:
    def __init__(s, status=200, js=None, text=""): s.status_code, s._js, s.text = status, js, text
    def json(s):
        if s._js is None: raise ValueError("no json")
        return s._js

@pytest.fixture(autouse=True)
def nosleep(monkeypatch): monkeypatch.setattr(g.time, "sleep", lambda s: None)

def pl(i, name="Biz", **kw): return {"id": f"id{i}", "displayName": {"text": name}, "formattedAddress": "Addr", "location": {"latitude": 1.0, "longitude": 2.0}, **kw}

def patch_post(monkeypatch, responder):
    calls = []
    def post(url, json=None, timeout=None, headers=None):
        calls.append(dict(url=url, body=json and dict(json), timeout=timeout, headers=headers)); return responder(len(calls))
    monkeypatch.setattr(g.requests, "post", post); return calls

def test_missing_key():
    with pytest.raises(g.GoogleError, match="key missing") as e: g.fetch_google("", "gym", 1, 2, 3000)
    assert e.value.calls == 0

def test_single_page_row_shape_and_request(monkeypatch):
    calls = patch_post(monkeypatch, lambda n: R(js={"places": [pl(1, internationalPhoneNumber="+91 98450 12345", nationalPhoneNumber="098450 12345",
        websiteUri="https://w.example", googleMapsUri="https://maps/x", rating=4.4, userRatingCount=10, businessStatus="OPERATIONAL")]}))
    r = g.fetch_google("KEY", "gym", 12.9, 77.6, 3000)
    assert r.calls == 1 and r.warning is None and len(calls) == 1
    row = r.rows[0]
    assert row == dict(id="g:id1", source="google", name="Biz", category="gym", address="Addr", lat=1.0, lng=2.0, phone="+91 98450 12345",
                       website="https://w.example", maps_url="https://maps/x", rating=4.4, reviews=10, status="OPERATIONAL")
    c = calls[0]
    assert c["url"] == g.ENDPOINT and c["headers"]["X-Goog-Api-Key"] == "KEY" and c["headers"]["X-Goog-FieldMask"] == g.FIELD_MASK
    assert c["body"]["textQuery"] == "gym" and c["body"]["locationBias"]["circle"]["center"] == {"latitude": 12.9, "longitude": 77.6}

def test_phone_falls_back_to_national_and_missing_fields(monkeypatch):
    patch_post(monkeypatch, lambda n: R(js={"places": [pl(1, nationalPhoneNumber="098450 12345"), {"id": "x"}]}))
    rows = g.fetch_google("K", "q", 1, 2, 100).rows
    assert rows[0]["phone"] == "098450 12345" and rows[1]["name"] is None and rows[1]["lat"] is None

def test_radius_is_capped_at_50km(monkeypatch):
    calls = patch_post(monkeypatch, lambda n: R(js={"places": []}))
    g.fetch_google("K", "q", 1, 2, 500000); assert calls[0]["body"]["locationBias"]["circle"]["radius"] == 50000.0

def test_pagination_follows_token_and_counts_calls(monkeypatch):
    pages = [{"places": [pl(1)], "nextPageToken": "T1"}, {"places": [pl(2)], "nextPageToken": "T2"}, {"places": [pl(3)]}]
    calls = patch_post(monkeypatch, lambda n: R(js=pages[n - 1]))
    r = g.fetch_google("K", "q", 1, 2, 100, max_pages=3)
    assert [x["id"] for x in r.rows] == ["g:id1", "g:id2", "g:id3"] and r.calls == 3
    assert "pageToken" not in calls[0]["body"] and calls[1]["body"]["pageToken"] == "T1" and calls[2]["body"]["pageToken"] == "T2"

def test_max_pages_is_respected(monkeypatch):
    calls = patch_post(monkeypatch, lambda n: R(js={"places": [pl(n)], "nextPageToken": "more"}))
    r = g.fetch_google("K", "q", 1, 2, 100, max_pages=2); assert r.calls == 2 and len(calls) == 2 and len(r.rows) == 2

def test_retries_5xx_and_counts_each_billable_call(monkeypatch):
    seq = [R(503, text="down"), R(502, text="bad"), R(js={"places": [pl(1)]})]
    patch_post(monkeypatch, lambda n: seq[n - 1])
    r = g.fetch_google("K", "q", 1, 2, 100); assert r.calls == 3 and len(r.rows) == 1

def test_persistent_5xx_returns_non_json_error(monkeypatch):
    patch_post(monkeypatch, lambda n: R(503, text="<html>down</html>"))
    with pytest.raises(g.GoogleError, match="non-JSON \\(HTTP 503\\)") as e: g.fetch_google("K", "q", 1, 2, 100)
    assert e.value.calls == 3

@pytest.mark.parametrize("status,err,expect", [
    (403, {"status": "PERMISSION_DENIED", "message": "nope"}, "Places API \\(New\\)"),
    (429, {"status": "RESOURCE_EXHAUSTED", "message": "slow"}, "quota/rate limit"),
    (400, {"status": "INVALID_ARGUMENT", "message": "API key not valid"}, "API key invalid"),
    (401, {"status": "UNAUTHENTICATED", "message": "x"}, "API key invalid"),
    (400, {"status": "INVALID_ARGUMENT", "message": "bad body"}, "Google API error 400 INVALID_ARGUMENT: bad body")])
def test_error_messages_are_actionable(monkeypatch, status, err, expect):
    patch_post(monkeypatch, lambda n: R(status, js={"error": err}))
    with pytest.raises(g.GoogleError, match=expect) as e: g.fetch_google("K", "q", 1, 2, 100)
    assert e.value.calls == 1                                          # failed calls are reported so billing stays accurate

def test_later_page_failure_keeps_earlier_rows_with_warning(monkeypatch):
    seq = [R(js={"places": [pl(1)], "nextPageToken": "T"}), R(429, js={"error": {"status": "RESOURCE_EXHAUSTED", "message": "q"}})]
    patch_post(monkeypatch, lambda n: seq[n - 1])
    r = g.fetch_google("K", "q", 1, 2, 100)
    assert len(r.rows) == 1 and r.calls == 2 and r.warning.startswith("Google page 2 failed, kept earlier pages")

def test_network_error_retries_then_raises_with_call_count(monkeypatch):
    def resp(n): raise requests.ConnectionError("boom")
    monkeypatch.setattr(g.requests, "post", lambda *a, **k: resp(0))
    with pytest.raises(g.GoogleError, match="network error") as e: g.fetch_google("K", "q", 1, 2, 100)
    assert e.value.calls == 0                                          # nothing reached Google, nothing billed

def test_network_error_then_success(monkeypatch):
    state = {"n": 0}
    def post(*a, **k):
        state["n"] += 1
        if state["n"] == 1: raise requests.Timeout("slow")
        return R(js={"places": [pl(1)]})
    monkeypatch.setattr(g.requests, "post", post)
    r = g.fetch_google("K", "q", 1, 2, 100); assert len(r.rows) == 1 and r.calls == 1

def test_empty_result_is_valid(monkeypatch):
    patch_post(monkeypatch, lambda n: R(js={})); r = g.fetch_google("K", "q", 1, 2, 100)
    assert r.rows == [] and r.calls == 1 and r.warning is None
