"""Business search (Maps scraper, OpenStreetMap, Google Places) and its job status."""
import os, threading, requests
from flask import Blueprint, request, jsonify
import pipeline as P
from core import JOB, claim, num

bp = Blueprint("find", __name__)


def geocode(q):
    r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "json", "limit": 1}, headers=P.UA, timeout=20).json()
    if not r: raise RuntimeError(f"Could not find the location '{q}'. Try adding the city.")
    return float(r[0]["lat"]), float(r[0]["lon"])


@bp.post("/api/find")
def find():
    b = request.json or {}
    src, cat, loc = b.get("source", "scrape"), (b.get("category") or "").strip(), (b.get("location") or "").strip()
    if src not in ("scrape", "osm", "google"): return jsonify(error="Unknown source"), 400
    if not cat or not loc: return jsonify(error="Business type and location are required"), 400
    c = P.db()
    try:
        n = num(b.get("n", 20), 1, 100, "How many")
        rad = num(b.get("radius_km", 5), 1, 50, "Radius") if src != "scrape" else 5
        cap = num(b.get("cap", P.get_setting(c, "google_cap") or 900), 10, 100000, "Monthly cap")
        key = (b.get("api_key") or "").strip() or P.get_setting(c, "google_key") or os.getenv("GOOGLE_API_KEY", "")
        if src == "google" and not key: raise ValueError("Add your Google API key first")
    except ValueError as e: c.close(); return jsonify(error=str(e)), 400
    busy = claim("find")                                   # validation passed: now take the global slot
    if busy: c.close(); return jsonify(error=busy), 409
    try:
        if b.get("api_key"): P.set_setting(c, "google_key", key)
        P.set_setting(c, "last_location", loc); P.set_setting(c, "google_cap", cap)
    except Exception as e: JOB["running"] = False; return jsonify(error=str(e)), 500
    finally: c.close()
    JOB.update(running=True, msg=f"Searching {cat} in {loc}", total=0, done=0, collected=0, skipped=0, phase="Starting", run_id=None)

    def work():
        cb = lambda p: JOB.update(p)
        try:
            if src == "scrape": f, a, _ = P.run_scrape(cat, loc, n, on_progress=cb)
            else:
                JOB["phase"] = "Finding the location"; lat, lng = geocode(loc)
                f, a, _ = P.run(cat, lat, lng, rad * 1000, src, key, cap, max_pages=min(5, -(-n // 20)), location=loc, limit=n, on_progress=cb)
            JOB["msg"] = f"Done: {f} businesses with contact info, {a} new." + (f" Stopped early: {P.LAST_WARNING}" if src == "scrape" and P.LAST_WARNING else "")
        except Exception as e: JOB["msg"] = f"Failed: {e}"
        finally: JOB.update(running=False, phase="Finished")      # lock always released
    threading.Thread(target=work, daemon=True).start(); return jsonify(ok=True)


@bp.get("/api/job")
def job():
    if request.args.get("v", type=int) == JOB["v"]: return "", 204
    return jsonify(JOB)
