"""Google Places API (New) text-search source. Standalone: no database, no module-level mutable state.
    from google_source import fetch_google, GoogleError
    res = fetch_google(KEY, "gym", 12.97, 77.64, 3000, max_pages=3)   # -> GoogleResult(rows, calls, warning)
Every HTTP call is billable, so `calls` is returned even when a later page fails (GoogleError.calls on a hard failure)."""
import time
from dataclasses import dataclass, field
import requests

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.location,"
              "places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,"
              "places.googleMapsUri,places.businessStatus,places.rating,places.userRatingCount,nextPageToken")

class GoogleError(RuntimeError):
    def __init__(self, msg, calls=0): super().__init__(msg); self.calls = calls

@dataclass
class GoogleResult:
    rows: list = field(default_factory=list)
    calls: int = 0
    warning: str = None

def google_error(status, e):
    st, msg = e.get("status", ""), e.get("message", "Google API error")
    if st == "RESOURCE_EXHAUSTED" or status == 429: return f"Google quota/rate limit exceeded: {msg}"
    if st == "PERMISSION_DENIED" or status == 403:
        return f"Google refused the request (enable 'Places API (New)', enable billing, check key restrictions): {msg}"
    if "API key" in msg or st == "UNAUTHENTICATED": return f"Google API key invalid: {msg}"
    return f"Google API error {status} {st}: {msg}"

def parse_places(places, query):
    out = []
    for p in places:
        loc = p.get("location", {})
        out.append(dict(id="g:" + p["id"], source="google", name=p.get("displayName", {}).get("text"),
            category=query, address=p.get("formattedAddress"), lat=loc.get("latitude"), lng=loc.get("longitude"),
            phone=p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"),
            website=p.get("websiteUri"), maps_url=p.get("googleMapsUri"), rating=p.get("rating"),
            reviews=p.get("userRatingCount"), status=p.get("businessStatus")))
    return out

def fetch_google(key, query, lat, lng, radius_m, max_pages=3, page_delay=1.5):
    if not key: raise GoogleError("Google API key missing")
    body = {"textQuery": query, "pageSize": 20, "locationBias": {"circle": {
        "center": {"latitude": lat, "longitude": lng}, "radius": float(min(radius_m, 50000))}}}
    res = GoogleResult()
    for pg in range(max_pages):
        resp = None
        for attempt in range(3):
            try:
                resp = requests.post(ENDPOINT, json=body, timeout=30, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK})
            except requests.RequestException as e:
                if attempt == 2: raise GoogleError(f"Google API network error: {e}", res.calls)
                time.sleep(2 * (attempt + 1)); continue
            res.calls += 1
            if resp.status_code in (500, 502, 503, 504) and attempt < 2: time.sleep(2 ** (attempt + 1)); continue
            break
        try: r = resp.json()
        except ValueError: raise GoogleError(f"Google API returned non-JSON (HTTP {resp.status_code}): {resp.text[:120]!r}", res.calls)
        if "error" in r:
            msg = google_error(resp.status_code, r["error"])
            if res.rows: res.warning = f"Google page {pg + 1} failed, kept earlier pages: {msg}"; break
            raise GoogleError(msg, res.calls)
        res.rows += parse_places(r.get("places", []), query)
        if not r.get("nextPageToken"): break
        body["pageToken"] = r["nextPageToken"]; time.sleep(page_delay)
    return res
