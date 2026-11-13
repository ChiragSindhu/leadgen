"""One-process admin: JSON API + web UI. Run: ADMIN_PASSWORD=secret python server.py
Host: gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 server:app   (keep 1 worker: job state is in memory)"""
import os, secrets, threading, requests
from flask import Flask, request, jsonify, session, send_from_directory
import pipeline as P

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(16)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
PW = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(8)
if not os.getenv("ADMIN_PASSWORD"): print("ADMIN_PASSWORD not set. Temporary password:", PW)
JOB = {"running": False, "msg": "idle"}

@app.before_request
def guard():
    if request.path.startswith("/api/") and request.path != "/api/login" and not session.get("ok"):
        return jsonify(error="login required"), 401

def rows(sql, *a):
    c = P.db(); r = [dict(x) for x in c.execute(sql, a)]; c.close(); return r

BASE = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
def home():
    for d in (os.path.join(BASE, "static"), BASE):   # works with or without the static/ folder
        if os.path.exists(os.path.join(d, "index.html")): return send_from_directory(d, "index.html")
    return f"index.html not found. Put it in {os.path.join(BASE, 'static')} (folder named 'static' next to server.py).", 404

@app.post("/api/login")
def login():
    if secrets.compare_digest((request.json or {}).get("password", ""), PW): session["ok"] = True; return jsonify(ok=True)
    return jsonify(error="Wrong password"), 403

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/stats")
def stats():
    c = P.db(); q = lambda s: c.execute(s).fetchone()[0]
    out = dict(total=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL"), ready=len(P.sendable(c, 100000)),
               with_phone=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL AND phone IS NOT NULL"),
               contacted=q("SELECT COUNT(*) FROM leads WHERE outreach!='new'"),
               warm=q("SELECT COUNT(*) FROM leads WHERE outreach IN ('replied','interested')"),
               sent_today=P.sent_today(c), limit=int(P.get_setting(c, "daily_limit")))
    c.close(); return jsonify(out)

@app.get("/api/leads")
def leads():
    w, a = ["dup_of IS NULL"], []
    if q := request.args.get("q"): w.append("(name LIKE ? OR phone LIKE ? OR address LIKE ?)"); a += [f"%{q}%"] * 3
    if s := request.args.get("status"): w.append("outreach=?"); a.append(s)
    if request.args.get("mobile") == "1": w.append("is_mobile=1")
    return jsonify(rows("SELECT id,name,category,phone,is_mobile,website,address,score,outreach,notes,source FROM leads "
                        f"WHERE {' AND '.join(w)} ORDER BY score DESC, first_seen DESC LIMIT 300", *a))

@app.post("/api/leads")
def add():
    c = P.db()
    try: res = P.import_businesses(c, request.json)
    except ValueError as e: return jsonify(error=str(e)), 400
    finally: c.close()
    return jsonify(res)

@app.patch("/api/leads/<path:lid>")
def patch(lid):
    c = P.db(); r = c.execute("SELECT outreach,notes FROM leads WHERE id=?", (lid,)).fetchone()
    if not r: return jsonify(error="not found"), 404
    b = request.json or {}; P.set_outreach(c, lid, b.get("outreach", r["outreach"]), b.get("notes", r["notes"])); c.close()
    return jsonify(ok=True)

@app.delete("/api/leads/<path:lid>")
def remove(lid):
    c = P.db(); P.delete_leads(c, [lid]); c.close(); return jsonify(ok=True)

@app.get("/api/queue")
def queue():
    c = P.db(); lim, used, tpl = int(P.get_setting(c, "daily_limit")), P.sent_today(c), P.get_setting(c, "template")
    items = [{**dict(r), "link": P.wa_link(r["phone"], P.render(tpl, r))} for r in P.sendable(c, max(0, lim - used))]
    c.close(); return jsonify(used=used, limit=lim, items=items)

@app.route("/api/settings", methods=["GET", "PUT"])
def settings():
    c = P.db()
    if request.method == "PUT":
        b = request.json or {}
        if b.get("template"): P.set_setting(c, "template", b["template"])
        if b.get("daily_limit"): P.set_setting(c, "daily_limit", max(1, min(100, int(b["daily_limit"]))))
    out = {k: P.get_setting(c, k) for k in ("template", "daily_limit", "last_location")}
    out.update(has_google_key=bool(P.get_setting(c, "google_key") or os.getenv("GOOGLE_API_KEY")), google_cap=int(P.get_setting(c, "google_cap") or 900), google_used=P.google_used(c))
    c.close(); return jsonify(out)

def geocode(q):
    r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "json", "limit": 1}, headers=P.UA, timeout=20).json()
    if not r: raise RuntimeError(f"Could not find the location '{q}'. Try adding the city.")
    return float(r[0]["lat"]), float(r[0]["lon"])

def num(v, lo, hi, name):
    try: n = int(v)
    except (TypeError, ValueError): n = lo - 1
    if not lo <= n <= hi: raise ValueError(f"{name} must be a number from {lo} to {hi}")
    return n

@app.post("/api/find")
def find():
    b = request.json or {}
    if JOB["running"]: return jsonify(error="A search is already running"), 409
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
        if b.get("api_key"): P.set_setting(c, "google_key", key)
        P.set_setting(c, "last_location", loc); P.set_setting(c, "google_cap", cap)
    except ValueError as e: return jsonify(error=str(e)), 400
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
        finally: JOB.update(running=False, phase="Finished")
    threading.Thread(target=work, daemon=True).start(); return jsonify(ok=True)

@app.get("/api/runs")
def runs(): return jsonify(rows("SELECT * FROM runs ORDER BY id DESC LIMIT 100"))

@app.get("/api/runs/<int:rid>")
def run_detail(rid):
    r = rows("SELECT * FROM runs WHERE id=?", rid)
    if not r: return jsonify(error="not found"), 404
    return jsonify(run=r[0], events=rows("SELECT at,kind,text FROM run_events WHERE run_id=? ORDER BY id", rid))

@app.get("/api/leads/<path:lid>")
def detail(lid):
    c = P.db(); r = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    if not r: c.close(); return jsonify(error="not found"), 404
    d = {k: r[k] for k in r.keys() if k != "hash"}
    d["link"] = P.wa_link(d["phone"], P.render(P.get_setting(c, "template"), d)) if d["phone"] else None
    d["changes"] = [dict(x) for x in c.execute("SELECT at,field,old,new FROM changes WHERE lead_id=? ORDER BY id DESC LIMIT 20", (lid,))]
    c.close(); return jsonify(d)

@app.get("/api/job")
def job(): return jsonify(JOB)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))