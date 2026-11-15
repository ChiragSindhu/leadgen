"""One-process admin: JSON API + web UI. Run: ADMIN_PASSWORD=secret python server.py
Host: gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 server:app   (keep 1 worker: job state is in memory)"""
import os, secrets, threading, requests, json
from flask import send_file, Flask, request, jsonify, session, send_from_directory
import datetime as dt
import pipeline as P
import re, uuid
import time
from werkzeug.utils import secure_filename

import wa, sbstore
from sbstore import local_media

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(16)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE") == "1")
PW = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(8)
if not os.getenv("ADMIN_PASSWORD"): print("ADMIN_PASSWORD not set. Temporary password:", PW)
class Job(dict):
    """Search progress. Every real change bumps 'v' so clients can ask 'anything new since v?' and get an empty reply."""
    def __setitem__(self, k, val):
        if k != "v" and self.get(k) != val: super().__setitem__("v", self.get("v", 0) + 1)
        super().__setitem__(k, val)
    def update(self, *a, **kw):
        for k, val in dict(*a, **kw).items(): self[k] = val
JOB = Job(running=False, msg="idle", v=0)
SJ = Job(running=False, msg="idle", v=0)

# ---- global execution lock: only ONE of find/send may run at a time
_LOCK = threading.Lock()
def claim(kind):
    """Atomically claim the single execution slot. Returns an error string if busy, else None."""
    with _LOCK:
        if JOB["running"]: return "A search is already running. Wait for it to finish."
        if SJ["running"]: return "A WhatsApp send is already running. Stop it or wait for it to finish."
        (JOB if kind == "find" else SJ)["running"] = True
    return None

_c = P.db()
_c.execute("UPDATE runs SET status='failed', error='Interrupted by a server restart', finished_at=? WHERE status='running'", (P.now(),))
for ddl in ("CREATE INDEX IF NOT EXISTS idx_leads_rank ON leads(score DESC, first_seen DESC) WHERE dup_of IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_leads_outreach ON leads(outreach)",
            "CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, path TEXT NOT NULL, type TEXT, name TEXT, size BIGINT DEFAULT 0, enabled INTEGER DEFAULT 1, at TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_leads_dup ON leads(dup_of)",
            "ALTER TABLE leads ADD COLUMN IF NOT EXISTS priority BIGINT NOT NULL DEFAULT 0"):
    _c.execute(ddl)
_c.execute("DELETE FROM run_events WHERE at < ?", ((dt.datetime.now() - dt.timedelta(days=30)).isoformat(timespec="seconds"),))
_c.commit(); _c.close()

@app.before_request
def guard():
    if request.path.startswith("/api/") and request.path != "/api/login" and not session.get("ok"):
        return jsonify(error="login required"), 401

def rows(sql, *a):
    c = P.db(); r = [dict(x) for x in c.execute(sql, a)]; c.close(); return r

BASE = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
def home():
    for d in (os.path.join(BASE, "static"), BASE):
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
    out = dict(total=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL"), ready=P.sendable_count(c),
               with_phone=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL AND phone IS NOT NULL"),
               contacted=q("SELECT COUNT(*) FROM leads WHERE outreach!='new'"),
               warm=q("SELECT COUNT(*) FROM leads WHERE outreach IN ('replied','interested')"),
               sent_today=P.sent_today(c), limit=int(P.get_setting(c, "daily_limit")),
               wa=wa.state["status"], busy=("find" if JOB["running"] else "send" if SJ["running"] else None))   # global status for every page
    c.close(); return jsonify(out)

OUTREACH = ("new", "messaged", "replied", "interested", "not_interested", "bad_number", "do_not_contact")
def clamp(v, lo, hi): return max(lo, min(hi, v))

def lead_filter(src):
    w, a = ["dup_of IS NULL"], []
    if q := (src.get("q") or "").strip():
        w.append("(name ILIKE ? OR phone LIKE ? OR address ILIKE ? OR category ILIKE ?)"); a += [f"%{q}%"] * 4
    if s := src.get("status"): w.append("outreach=?"); a.append(s)
    if str(src.get("mobile")) == "1": w.append("is_mobile=1")
    return " AND ".join(w), a

@app.get("/api/leads")
def leads():
    where, a = lead_filter(request.args)
    lim = clamp(request.args.get("limit", 50, type=int), 1, 200); off = max(0, request.args.get("offset", 0, type=int))
    c = P.db()
    try:
        total = c.execute(f"SELECT COUNT(*) FROM leads WHERE {where}", a).fetchone()[0]
        items = [dict(x) for x in c.execute(
            f"SELECT id,name,category,phone,is_mobile,score,outreach FROM leads WHERE {where} "
            "ORDER BY score DESC, first_seen DESC, id LIMIT ? OFFSET ?", a + [lim, off])]
    finally: c.close()
    return jsonify(items=items, total=total)

@app.get("/api/leads/phones")
def phones(): return jsonify([r["phone"] for r in rows("SELECT phone FROM leads WHERE dup_of IS NULL AND phone IS NOT NULL")])

@app.post("/api/leads/bulk")
def bulk():
    b = request.json or {}; act = b.get("action")
    if act not in ("delete", "status"): return jsonify(error="Unknown action"), 400
    if act == "status" and b.get("outreach") not in OUTREACH: return jsonify(error="Unknown status"), 400
    c = P.db()
    try:
        if b.get("all"):
            where, a = lead_filter({"q": b.get("q"), "status": b.get("status"), "mobile": "1" if b.get("mobile") else "0"})
            ids = [r[0] for r in c.execute(f"SELECT id FROM leads WHERE {where} LIMIT 5001", a)]
        else: ids = [str(i) for i in (b.get("ids") or [])]
        if len(ids) > 5000: return jsonify(error="Too many leads at once (max 5000). Narrow the filter."), 400
        if not ids: return jsonify(ok=True, n=0)
        if act == "delete":
            c.execute("UPDATE leads SET dup_of=NULL WHERE dup_of = ANY(?)", (ids,))
            c.execute("DELETE FROM changes WHERE lead_id = ANY(?)", (ids,))
            n = c.execute("DELETE FROM leads WHERE id = ANY(?)", (ids,)).rowcount
        else:
            st = b["outreach"]
            n = c.execute("UPDATE leads SET contacted_at = CASE WHEN outreach='new' AND ? != 'new' THEN ? ELSE contacted_at END, outreach=? "
                          "WHERE id = ANY(?)", (st, P.now(), st, ids)).rowcount
        c.commit()
    finally: c.close()
    return jsonify(ok=True, n=n)

@app.post("/api/leads")
def add():
    c = P.db()
    try: res = P.import_businesses(c, request.json)
    except ValueError as e: return jsonify(error=str(e)), 400
    finally: c.close()
    return jsonify(res)

@app.patch("/api/leads/<path:lid>")
def patch(lid):
    c = P.db()
    try:
        r = c.execute("SELECT outreach,notes FROM leads WHERE id=?", (lid,)).fetchone()
        if not r: return jsonify(error="not found"), 404
        b = request.json or {}; P.set_outreach(c, lid, b.get("outreach", r["outreach"]), b.get("notes", r["notes"]))
        if "outreach" in b: c.execute("UPDATE leads SET priority=0 WHERE id=?", (lid,)); c.commit()
    finally: c.close()
    return jsonify(ok=True)

@app.delete("/api/leads/<path:lid>")
def remove(lid):
    c = P.db(); P.delete_leads(c, [lid]); c.close(); return jsonify(ok=True)

@app.post("/api/leads/<path:lid>/front")
def front(lid):
    c = P.db()
    try:
        if not c.execute(f"SELECT 1 FROM leads WHERE id=? AND {P.SENDABLE}", (lid,)).fetchone():
            return jsonify(error="This lead is not in the send queue (already contacted, no mobile number, or excluded)."), 409
        c.execute("UPDATE leads SET priority=? WHERE id=?", (int(time.time() * 1000), lid)); c.commit()
    finally: c.close()
    return jsonify(ok=True)

@app.get("/api/queue")
def queue():
    c = P.db(); lim, used = int(P.get_setting(c, "daily_limit")), P.sent_today(c)
    tpl = P.get_setting(c, "template"); ms = [pub(m) for m in media_list(c, True)]
    items = [{**dict(r), "link": P.wa_link(r["phone"], render_tpl(tpl, dict(r)))} for r in P.sendable(c, max(0, lim - used))]
    c.close(); return jsonify(used=used, limit=lim, items=items, media=ms, wa=wa.state["status"])

@app.route("/api/settings", methods=["GET", "PUT"])
def settings():
    c = P.db()
    if request.method == "PUT":
        b = request.json or {}
        if b.get("template"): P.set_setting(c, "template", b["template"])
        if b.get("daily_limit"): P.set_setting(c, "daily_limit", max(1, min(100, int(b["daily_limit"]))))
    out = {k: P.get_setting(c, k) for k in ("template", "daily_limit", "last_location")}
    out.update(has_google_key=bool(P.get_setting(c, "google_key") or os.getenv("GOOGLE_API_KEY")), google_cap=int(P.get_setting(c, "google_cap") or 900), google_used=P.google_used(c))
    out["media"] = [pub(m) for m in media_list(c)]
    c.close(); return jsonify(out)

# ---- WhatsApp delivery pipeline config (new)
WA_DEFAULT = dict(order="caption", album=False, step_delay=2, gap=25, jitter=15)
def wa_cfg(c=None):
    own = c is None; c = c or P.db()
    try: raw = P.get_setting(c, "wa_cfg")
    finally:
        if own: c.close()
    try: d = json.loads(raw) if raw else {}
    except Exception: d = {}
    return {**WA_DEFAULT, **{k: d[k] for k in d if k in WA_DEFAULT}}

@app.route("/api/wa/config", methods=["GET", "PUT"])
def wa_config():
    c = P.db()
    try:
        cur = wa_cfg(c)
        if request.method == "PUT":
            b = request.json or {}
            if b.get("order", cur["order"]) not in ("caption", "text_first", "media_first"): return jsonify(error="Unknown order"), 400
            try:
                cur = dict(order=b.get("order", cur["order"]), album=bool(b.get("album", cur["album"])),
                           step_delay=clamp(float(b.get("step_delay", cur["step_delay"])), 0, 30),
                           gap=clamp(float(b.get("gap", cur["gap"])), 10, 300), jitter=clamp(float(b.get("jitter", cur["jitter"])), 0, 120))
            except (TypeError, ValueError): return jsonify(error="Delays must be numbers"), 400
            P.set_setting(c, "wa_cfg", json.dumps(cur))
        return jsonify(cur)
    finally: c.close()

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

@app.get("/api/runs")
def runs():
    lim = clamp(request.args.get("limit", 30, type=int), 1, 100); off = max(0, request.args.get("offset", 0, type=int))
    c = P.db()
    try: total = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally: c.close()
    return jsonify(items=rows("SELECT id,at,query,source,fetched,added,changed,calls,location,status,finished_at,requested,error,no_contact "
                              "FROM runs ORDER BY id DESC LIMIT ? OFFSET ?", lim, off), total=total)

@app.get("/api/runs/<int:rid>")
def run_detail(rid):
    r = rows("SELECT * FROM runs WHERE id=?", rid)
    if not r: return jsonify(error="not found"), 404
    return jsonify(run=r[0], events=rows("SELECT * FROM (SELECT id,at,kind,text FROM run_events WHERE run_id=? ORDER BY id DESC LIMIT 300) ORDER BY id", rid))

@app.get("/api/leads/<path:lid>")
def detail(lid):
    c = P.db(); r = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    if not r: c.close(); return jsonify(error="not found"), 404
    d = {k: r[k] for k in r.keys() if k != "hash"}
    d["link"] = P.wa_link(d["phone"], render_tpl(P.get_setting(c, "template"), d)) if d["phone"] else None
    d["changes"] = [dict(x) for x in c.execute("SELECT at,field,old,new FROM changes WHERE lead_id=? ORDER BY id DESC LIMIT 20", (lid,))]
    c.close(); return jsonify(d)

@app.get("/api/job")
def job():
    if request.args.get("v", type=int) == JOB["v"]: return "", 204
    return jsonify(JOB)

MEDIA_MAX = {"image": 5 << 20, "video": 16 << 20}; MAX_FILES, MAX_TOTAL = 10, 100 << 20
app.config["MAX_CONTENT_LENGTH"] = 17 << 20

@app.errorhandler(413)
def too_big(e): return jsonify(error="File is too large (max 16 MB)"), 413

VARS = lambda l: {"name": l.get("name"), "type": l.get("category"), "category": l.get("category"), "phone": l.get("phone"),
                  "address": l.get("address"), "rating": l.get("rating"), "reviews": l.get("reviews"), "website": l.get("website"),
                  "date": dt.date.today().strftime("%d %b")}
def render_tpl(tpl, lead):
    v = VARS(lead)
    return re.sub(r"\{(\w+)\}", lambda m: ("" if v[m[1]] is None else str(v[m[1]])) if m[1] in v else m[0], tpl or "")

def sniff(b):
    if b[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    if b[4:8] == b"ftyp": return "video/3gpp" if b[8:11] == b"3gp" else "video/mp4"

def media_list(c, only_on=False):
    return [dict(r) for r in c.execute("SELECT id,path,type,name,size,enabled FROM media " + ("WHERE enabled=1 " if only_on else "") + "ORDER BY at, id")]
pub = lambda m: dict(id=m["id"], name=m["name"], type=m["type"], size=m["size"] or 0, on=bool(m["enabled"]))

@app.get("/api/media")
def media_all():
    c = P.db()
    try: return jsonify([pub(m) for m in media_list(c)])
    finally: c.close()

@app.post("/api/media")
def media_up():
    if not sbstore.configured(): return jsonify(error="Storage is not configured on the server"), 503
    f = request.files.get("file"); data = f.read() if f else b""
    if not data: return jsonify(error="Choose a file"), 400
    kind = sniff(data[:16])
    if kind not in sbstore.MEDIA_EXT: return jsonify(error="Only JPG, PNG, WebP images and MP4 or 3GP videos are allowed"), 400
    cap = MEDIA_MAX[kind.split("/")[0]]
    if len(data) > cap: return jsonify(error=f"{kind.split('/')[0].title()} files must be under {cap >> 20} MB"), 400
    c = P.db()
    try:
        cur = media_list(c)
        if len(cur) >= MAX_FILES: return jsonify(error=f"You can keep up to {MAX_FILES} files. Delete one first."), 400
        if sum(m["size"] or 0 for m in cur) + len(data) > MAX_TOTAL: return jsonify(error="Library is full (100 MB total)"), 400
        mid = uuid.uuid4().hex; path = f"{mid}.{sbstore.MEDIA_EXT[kind]}"
        try: sbstore.upload(path, data, kind)
        except Exception: return jsonify(error="Upload to storage failed. Check the bucket name and key."), 502
        name = secure_filename(f.filename or path)[:80] or path
        c.execute("INSERT INTO media(id,path,type,name,size,enabled,at) VALUES(?,?,?,?,?,1,?)", (mid, path, kind, name, len(data), P.now())); c.commit()
        return jsonify(pub(dict(id=mid, name=name, type=kind, size=len(data), enabled=1)))
    finally: c.close()

@app.patch("/api/media/<mid>")
def media_toggle(mid):
    on = bool((request.json or {}).get("on"))
    c = P.db()
    try: c.execute("UPDATE media SET enabled=? WHERE id=?", (1 if on else 0, mid)); c.commit()
    finally: c.close()
    return jsonify(ok=True, id=mid, on=on)          # echo the saved state so the UI can reconcile

@app.delete("/api/media/<mid>")
def media_rm(mid):
    c = P.db()
    try:
        r = c.execute("SELECT path FROM media WHERE id=?", (mid,)).fetchone()
        c.execute("DELETE FROM media WHERE id=?", (mid,)); c.commit()
    finally: c.close()
    if r: sbstore.delete(r["path"]); sbstore.purge_cache(mid)
    return jsonify(ok=True)

@app.get("/api/media/<mid>/file")
def media_file(mid):
    c = P.db()
    try: m = next((x for x in media_list(c) if x["id"] == mid), None)
    finally: c.close()
    if not m: return jsonify(error="not found"), 404
    return send_file(local_media(m), mimetype=m["type"], conditional=True)

@app.get("/api/wa/status")
def wa_status(): return jsonify({**wa.state, "busy": "find" if JOB["running"] else "send" if SJ["running"] else None})

def _wa_action(name):
    if JOB["running"] or SJ["running"]: return jsonify(error="Wait for the running search or send to finish first."), 409
    if name == "sync" and not sbstore.configured(): return jsonify(error="Supabase storage is not configured on the server"), 503
    if name == "sync" and wa.state["status"] != "ready": return jsonify(error="WhatsApp is not connected, so there is nothing to back up."), 400
    wa.request_action(name); return jsonify(ok=True)

@app.post("/api/wa/sync")
def wa_sync(): return _wa_action("sync")

@app.post("/api/wa/reset")
def wa_reset(): return _wa_action("reset")

def rlog(rid, kind, text):
    c = P.db()
    try: c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (rid, P.now(), kind, text)); c.commit()
    finally: c.close()

def deliver(lid, step):
    """Returns 'sent' (server-acknowledged) or 'unconfirmed'. Raises on failure."""
    c = P.db()
    try:
        r = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        if not r or not r["phone"]: raise wa.WAError("No phone number")
        lead = dict(r); text = render_tpl(P.get_setting(c, "template"), lead)
        files = [local_media(m) for m in media_list(c, True)]
        cfg = wa_cfg(c)
    finally: c.close()
    res = wa.send(lead["phone"], text, files, step, cfg)
    c = P.db()
    try: P.set_outreach(c, lid, "messaged", lead.get("notes"))
    finally: c.close()
    return res

@app.post("/api/send")
def send_start():
    b = request.json or {}
    if wa.state["status"] != "ready": return jsonify(error="WhatsApp is not connected. Scan the QR code in Settings."), 400
    busy = claim("send")
    if busy: return jsonify(error=busy), 409
    c = P.db()
    try:
        room = max(0, int(P.get_setting(c, "daily_limit")) - P.sent_today(c))
        if b.get("ids"): ids = [str(i) for i in b["ids"]][:100]; label = "Auto send"
        else:
            n = num(b.get("n"), 1, 100, "How many"); ids = [str(r["id"]) for r in P.sendable(c, min(n, room))]; label = "Send all"
        ids = ids[:room]
        if not ids: SJ["running"] = False; return jsonify(error="Daily limit reached" if not room else "No leads ready to send"), 400
        label += f" ({len(ids)} lead{'s' if len(ids) > 1 else ''})"
        rid = c.execute("INSERT INTO runs(at,query,source,requested,fetched,added,changed,calls,status) VALUES(?,?,?,?,?,0,0,0,'running') RETURNING id",
                        (P.now(), label, "whatsapp", len(ids), len(ids))).fetchone()[0]; c.commit()
    except ValueError as e: SJ["running"] = False; return jsonify(error=str(e)), 400
    except Exception as e: SJ["running"] = False; return jsonify(error=str(e)), 500
    finally: c.close()
    SJ.update(running=True, stop=False, msg=label, total=len(ids), done=0, sent=0, failed=0, unconfirmed=0, current="", step="Starting", phase="Sending", run_id=rid, last=None)
    rlog(rid, "info", f"Started: {len(ids)} lead(s) queued")
    def work():
        sent = failed = unc = 0; err = None
        try:
            for i, lid in enumerate(ids):
                if SJ.get("stop"): rlog(rid, "warn", "Stopped by you"); break
                c = P.db(); r = c.execute("SELECT name FROM leads WHERE id=?", (lid,)).fetchone(); c.close(); name = r["name"] if r else lid
                SJ.update(current=name, step="Starting", phase=f"Sending {i + 1} of {len(ids)}"); rlog(rid, "info", f"Sending to {name}")
                try:
                    res = deliver(lid, lambda s: (SJ.update(step=s), rlog(rid, "info", f"{name}: {s}")))
                    sent += 1
                    if res == "unconfirmed": unc += 1; rlog(rid, "warn", f"{name}: sent but WhatsApp never confirmed delivery to its server")
                    else: rlog(rid, "info", f"Sent to {name} (confirmed)")
                except Exception as e:
                    failed += 1; msg = str(e) if isinstance(e, wa.WAError) else f"{type(e).__name__}: {str(e)[:150]}"
                    rlog(rid, "warn", f"{name}: {msg}")
                    if "not connected" in msg or "restarted" in msg: err = msg; break
                SJ.update(done=i + 1, sent=sent, failed=failed, unconfirmed=unc, last=lid)
        except Exception as e: err = str(e)
        finally:
            try:
                c = P.db()
                try:
                    c.execute("UPDATE runs SET status=?, added=?, changed=?, finished_at=?, error=? WHERE id=?",
                              ("failed" if err else "done", sent, failed, P.now(),
                               err or "; ".join(x for x in (f"{failed} failed" if failed else "", f"{unc} unconfirmed" if unc else "") if x) or None, rid)); c.commit()
                finally: c.close()
            finally:
                SJ.update(running=False, phase="Finished", step="", msg=f"Sent {sent}, failed {failed}" + (f", {unc} unconfirmed" if unc else ""))   # lock always released
    threading.Thread(target=work, daemon=True).start(); return jsonify(ok=True)

@app.post("/api/send/stop")
def send_stop(): SJ["stop"] = True; return jsonify(ok=True)

@app.get("/api/send/job")
def send_job():
    if request.args.get("v", type=int) == SJ["v"]: return "", 204
    return jsonify(SJ)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))