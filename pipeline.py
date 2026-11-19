"""Local lead pipeline v1.3: orchestration + database logic only.
Sources live in their own modules and know nothing about the database:
    google_source.py  (Places API New)   osm_source.py  (Overpass)   maps_scraper.py  (Playwright, run as a subprocess)
Storage: Supabase Postgres."""
import os, sys, threading, json, re, time, hashlib, subprocess, tempfile, datetime as dt
from urllib.parse import quote
import phonenumbers
import psycopg2, psycopg2.extras
import queue, shutil, psutil
import math, requests

from google_source import fetch_google, GoogleError           # noqa: F401  (re-exported for callers)
from osm_source import fetch_osm, OSMUnavailable, OSM_TAGS, osm_selectors   # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
def _load_env():   # every entry point (server, bot, scraper) reads .env
    f = os.path.join(HERE, ".env")
    if os.path.exists(f):
        for ln in open(f, encoding="utf-8-sig"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
_load_env()
DATABASE_URL = os.getenv("DATABASE_URL")   # Supabase: Connect -> Direct/Session pooler -> connection string
LAST_WARNING = None
LAST_OSM = {}
REGION = "IN"  # default country for numbers without a +code
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WATCH = ["name", "phone", "website", "email", "address", "status"]   # changes are logged
COLS = ["id", "source", "name", "category", "address", "lat", "lng", "phone", "is_mobile",
        "website", "email", "maps_url", "rating", "reviews", "status", "notes"]
EDITABLE = ["name", "category", "phone", "email", "website", "address", "lat", "lng", "notes"]
ALIASES = {"mobile": "phone", "contact": "phone", "phone_number": "phone", "business_name": "name",
           "url": "website", "type": "category", "mail": "email"}
SAMPLE = {"businesses": [
    {"name": "Sunrise Realty", "category": "real estate", "phone": "+91 98450 12345",
     "email": "hello@sunriserealty.example", "website": "https://sunriserealty.example",
     "address": "12 MG Road, Bengaluru", "lat": 12.975, "lng": 77.606, "notes": "met at expo"},
    {"name": "Green Nest PG", "category": "pg", "phone": "09845098450", "address": "Indiranagar"}]}

# RLS is enabled with no policies: the public API (publishable key) can't read leads.
# This app connects with the Postgres connection string, which bypasses RLS.
SCHEMA = """
CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY, source TEXT, name TEXT, category TEXT, address TEXT,
  lat DOUBLE PRECISION, lng DOUBLE PRECISION, phone TEXT, is_mobile INT, website TEXT, email TEXT, maps_url TEXT,
  rating DOUBLE PRECISION, reviews INT, status TEXT, score INT, hash TEXT, first_seen TEXT, last_seen TEXT,
  outreach TEXT DEFAULT 'new', notes TEXT DEFAULT '', dup_of TEXT, contacted_at TEXT);
CREATE TABLE IF NOT EXISTS changes(id BIGSERIAL PRIMARY KEY, lead_id TEXT, at TEXT,
  field TEXT, old TEXT, new TEXT);
CREATE TABLE IF NOT EXISTS runs(id BIGSERIAL PRIMARY KEY, at TEXT, query TEXT, source TEXT,
  fetched INT, added INT, changed INT, calls INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS run_events(id BIGSERIAL PRIMARY KEY, run_id BIGINT, at TEXT, kind TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS idx_phone ON leads(phone);
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE kv ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_events ENABLE ROW LEVEL SECURITY;
"""

def now(): return dt.datetime.now().isoformat(timespec="seconds")

_READY = set()
MIGRATIONS = [("leads", "dup_of", "TEXT"), ("leads", "contacted_at", "TEXT"), ("runs", "calls", "INT DEFAULT 0"),
              ("runs", "location", "TEXT"), ("runs", "status", "TEXT DEFAULT 'done'"), ("runs", "finished_at", "TEXT"),
              ("runs", "requested", "INT"), ("runs", "error", "TEXT")]
MIGRATIONS += [("runs", "params", "TEXT"), ("runs", "attempts", "INT DEFAULT 0"), ("runs", "worker_id", "TEXT"),
               ("runs", "heartbeat_at", "TEXT"), ("runs", "no_contact", "INT DEFAULT 0")]
_ready_lock = threading.Lock()

_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")

class Conn:
    """Thin wrapper so the rest of the code keeps sqlite-style `?` / `:name` placeholders."""
    def __init__(self, raw): self.raw = raw
    def execute(self, sql, params=None):
        cur = self.raw.cursor()
        try:
            if params is None: cur.execute(sql)
            else:
                sql = _NAMED.sub(r"%(\1)s", sql) if isinstance(params, dict) else sql.replace("?", "%s")
                cur.execute(sql, params)
        except Exception:
            self.raw.rollback(); raise      # a failed statement must not poison the transaction
        return cur
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()

def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL missing. Add your Supabase Postgres connection string to .env")
    ssl = os.getenv("DB_SSLMODE", "require")
    url = DATABASE_URL if "sslmode=" in DATABASE_URL else DATABASE_URL + ("&" if "?" in DATABASE_URL else "?") + "sslmode=" + ssl
    c = Conn(psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor, connect_timeout=15, keepalives=1,
                              keepalives_idle=30, keepalives_interval=10, keepalives_count=5, application_name="leadpipe"))
    with _ready_lock:
        if DATABASE_URL not in _READY:
            c.execute("SELECT pg_advisory_lock(727001)")     # web + worker may start together
            try:
                c.execute(SCHEMA)
                for t, col, typ in MIGRATIONS: c.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {typ}")
                c.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_ev_run ON run_events(run_id,id)")
                c.commit(); _READY.add(DATABASE_URL)
            finally:
                try: c.execute("SELECT pg_advisory_unlock(727001)"); c.commit()
                except Exception: pass
    return c

def norm_phone(raw, region=None):
    """Return (E.164 number or None, is_mobile). Handles 'a; b' lists, picks a mobile first."""
    if not raw: return None, 0
    good = []
    for part in re.split(r"[;,/]|\s{2,}|\sor\s", str(raw)):
        try:
            n = phonenumbers.parse(part.strip(), region or REGION)
            if phonenumbers.is_valid_number(n):
                mob = phonenumbers.number_type(n) in (phonenumbers.PhoneNumberType.MOBILE,
                      phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE)
                good.append((phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164), int(mob)))
        except Exception: pass
    return (sorted(good, key=lambda x: -x[1])[0] if good else (None, 0))

def score(r):
    if r.get("status") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY", "STALE"): return 0
    s = 40 if r.get("phone") else 0
    s += 15 if r.get("is_mobile") else 0
    s += 10 if r.get("website") else 0
    s += 10 if r.get("email") else 0
    s += 10 if (r.get("rating") or 0) >= 3.5 else 0
    s += 5 if (r.get("reviews") or 0) >= 5 else 0
    return s + 10   # +10 operating/active

# ---------- save + change detection ----------
def save_row(c, r, ts):
    """Insert or update one lead. Returns 'added' | 'updated' | 'same' | 'skipped'."""
    if not (r.get("name") or "").strip(): return "skipped"
    p, mob = norm_phone(r.get("phone"))
    r = {**r, "name": r["name"].strip(), "phone": p, "is_mobile": mob}
    old = c.execute("SELECT * FROM leads WHERE id=?", (r["id"],)).fetchone()
    if not old:
        new = {k: r.get(k) for k in COLS}
        new["status"] = new["status"] or "active"; new["notes"] = new["notes"] or ""
        new.update(score=score(new), first_seen=ts, last_seen=ts)
        keys = list(new)
        c.execute(f"INSERT INTO leads({','.join(keys)}) VALUES({','.join(':'+k for k in keys)})", new)
        if p:
            if r["source"] == "manual":   # manual entry is canonical; hide auto duplicates of it
                c.execute("UPDATE leads SET dup_of=? WHERE phone=? AND id!=? AND source!='manual'", (r["id"], p, r["id"]))
            else:
                o = c.execute("SELECT id FROM leads WHERE phone=? AND id!=? AND dup_of IS NULL ORDER BY source='manual' DESC, first_seen LIMIT 1", (p, r["id"])).fetchone()
                if o: c.execute("UPDATE leads SET dup_of=? WHERE id=?", (o["id"], r["id"]))
        return "added"
    new = dict(old)
    for k in COLS[2:]:                      # overlay only non-empty incoming values
        if k in ("is_mobile",): continue
        if r.get(k) not in (None, ""): new[k] = r[k]
    if p: new["is_mobile"] = mob
    changed = False
    for k in WATCH:
        if old[k] != new[k]:
            c.execute("INSERT INTO changes(lead_id,at,field,old,new) VALUES(?,?,?,?,?)", (r["id"], ts, k, old[k], new[k])); changed = True
    new["score"] = score(new); new["last_seen"] = ts
    ups = COLS[2:] + ["score", "last_seen"]
    c.execute(f"UPDATE leads SET {','.join(k+'=:'+k for k in ups)} WHERE id=:id", new)
    return "updated" if changed else "same"

def google_used(c):
    m = dt.date.today().strftime("%Y-%m") + "%"
    return c.execute("SELECT COALESCE(SUM(calls),0) FROM runs WHERE source='google' AND at LIKE ?", (m,)).fetchone()[0]

def run(query, lat, lng, radius_m, source="google", key=None, cap=900, max_pages=3, location=None, limit=None, on_progress=None):
    """Google / OSM run: fetch via the source module, then persist. All DB + bookkeeping lives here."""
    global LAST_WARNING
    LAST_WARNING = None
    c = db(); counter = [0]; rows = []; err = None; added = changed = nocontact = saved = 0
    run_id = c.execute("INSERT INTO runs(at,query,source,fetched,added,changed,calls,location,status,requested) VALUES(?,?,?,0,0,0,0,?,?,?) RETURNING id",
                       (now(), query, source, location, "running", limit)).fetchone()[0]; c.commit()
    prog = dict(run_id=run_id, total=0, done=0, collected=0, skipped=0, phase="Fetching from " + source)
    def ev(kind, text):
        c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (run_id, now(), kind, text)); c.commit()
        if on_progress: on_progress(dict(prog))
    try:
        ev("start", f"Started {source}: {query}" + (f" near {location}" if location else "") + f", radius {radius_m / 1000:g} km")
        try:
            if source == "google":
                used = google_used(c)
                if used + max_pages > cap: raise RuntimeError(f"Monthly Google call cap reached ({used}/{cap}). Raise the cap or use another source.")
                try: g = fetch_google(key, query, lat, lng, radius_m, max_pages)
                except GoogleError as e: counter[0] = e.calls; raise      # failed calls are still billable
                rows, counter[0] = g.rows, g.calls
                if g.warning: LAST_WARNING = g.warning; ev("warn", g.warning[:250])
            else:
                o = fetch_osm(query, lat, lng, radius_m); rows = o.rows
                LAST_OSM.update(mirror=o.mirror, raw=o.raw, unnamed=o.unnamed)
        except OSMUnavailable as e: err = e; ev("error", f"OSM UNAVAILABLE (not a zero-result): {str(e)[:230]}")
        except Exception as e: err = e; ev("error", str(e)[:250])
        if not err:
            if source == "osm":
                ev("found", f"Overpass ({LAST_OSM.get('mirror')}) reachable: {LAST_OSM.get('raw', 0)} elements, {len(rows)} named, {LAST_OSM.get('unnamed', 0)} unnamed dropped")
            else: ev("found", f"{source} returned {len(rows)} places")
            if not rows: ev("warn", "Source reachable but ZERO matching places. Try a larger radius, another category, or a different source.")
        rows = [r for r in rows if (r.get("name") or "").strip()]
        nocontact = sum(1 for r in rows if not (r.get("phone") or r.get("website")))
        rows.sort(key=lambda r: not (r.get("phone") or r.get("website")))   # contact-bearing first when limiting
        keep = rows[:limit] if limit else rows
        prog.update(total=len(rows), done=len(rows), collected=len(keep), skipped=max(0, len(rows) - len(keep)), phase="Saving leads")
        ts = now(); res = []
        for r in keep:
            res.append(save_row(c, r, ts))
        c.commit()
        added, changed, saved = res.count("added"), res.count("updated"), len([x for x in res if x != "skipped"])
        nocontact = sum(1 for r in keep if not (r.get("phone") or r.get("website")))
        if keep and nocontact: ev("info", f"{nocontact} of {len(keep)} saved WITHOUT phone/website: kept as leads, not sendable until contact info is added")
    except Exception as e:
        err = err or e
        try: ev("error", f"Unexpected failure: {type(e).__name__}: {str(e)[:200]}")
        except Exception: pass
    finally:
        try:
            c.execute("UPDATE runs SET fetched=?,added=?,changed=?,calls=?,status=?,finished_at=?,error=?,no_contact=? WHERE id=?",
                      (saved, added, changed, counter[0], "failed" if err else "done", now(), str(err)[:250] if err else None, nocontact, run_id))
            prog["phase"] = "Finished"
            ev("end", f"Finished: {saved} saved ({added} new, {changed} updated, {nocontact} without contact)" + (f", {counter[0]} Google calls" if counter[0] else ""))
            c.commit()
        finally: c.close()
    if err: raise err
    return saved, added, changed

def mark_stale(days=60):
    """Auto-sourced leads not seen for N days -> STALE. Only meaningful if you re-run the same areas regularly."""
    c = db(); cut = (dt.datetime.now() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    n = c.execute("UPDATE leads SET status='STALE', score=0 WHERE source IN ('google','osm') AND last_seen<? AND status NOT IN ('STALE','CLOSED_PERMANENTLY')", (cut,)).rowcount
    c.commit(); c.close(); return n

# ---------- manual add / JSON import / export ----------
def import_businesses(c, data):
    """data: list of dicts or {'businesses': [...]}. Re-importing the same business updates it, never duplicates."""
    items = data.get("businesses") if isinstance(data, dict) else data
    out = dict(added=0, updated=0, same=0, skipped=0, warnings=[])
    if not isinstance(items, list): raise ValueError("JSON must be a list or an object with a 'businesses' list")
    ts = now()
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict): out["skipped"] += 1; out["warnings"].append(f"#{i}: not an object"); continue
        it = {ALIASES.get(k.lower(), k.lower()): v for k, v in it.items()}
        name = str(it.get("name") or "").strip()
        if not name: out["skipped"] += 1; out["warnings"].append(f"#{i}: missing name"); continue
        row = {k: (str(it[k]).strip() if it.get(k) not in (None, "") else None) for k in
               ["category", "address", "phone", "email", "website", "notes"]}
        if row["email"] and not EMAIL_RE.match(row["email"]):
            out["warnings"].append(f"#{i} {name}: invalid email dropped"); row["email"] = None
        if row["phone"] and not norm_phone(row["phone"])[0]:
            out["warnings"].append(f"#{i} {name}: invalid phone '{row['phone']}' (kept in notes)")
            row["notes"] = ((row["notes"] or "") + f" [raw phone: {row['phone']}]").strip(); row["phone"] = None
        for k in ("lat", "lng"):
            try: row[k] = float(it[k]) if it.get(k) not in (None, "", 0) else None
            except (TypeError, ValueError): row[k] = None
        p = norm_phone(row["phone"])[0]
        key = p or (name.lower() + "|" + (row["address"] or "").lower())
        res = save_row(c, {**row, "id": "m:" + hashlib.md5(key.encode()).hexdigest()[:12], "source": "manual",
                           "name": name, "category": row["category"] or "uncategorized", "status": "active"}, ts)
        out[res] += 1
    c.commit(); return out

def export_json(c, manual_only=False):
    q = "SELECT * FROM leads" + (" WHERE source='manual'" if manual_only else " WHERE dup_of IS NULL")
    return {"businesses": [{k: r[k] for k in EDITABLE if r[k] not in (None, "")} for r in c.execute(q)]}

def set_outreach(c, lead_id, status, notes):
    o = c.execute("SELECT outreach FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not o: return
    ts = now() if (o["outreach"] == "new" and status != "new") else None   # first contact only
    c.execute("UPDATE leads SET outreach=?, notes=?, contacted_at=COALESCE(?,contacted_at) WHERE id=?", (status, notes or "", ts, lead_id))
    c.commit()

def delete_leads(c, ids):
    for i in ids:
        c.execute("DELETE FROM leads WHERE id=?", (i,)); c.execute("DELETE FROM changes WHERE lead_id=?", (i,))
    c.commit()

# ---------- Google Maps scraper as a source (maps_scraper.py runs as a subprocess: safe on Windows/Streamlit) ----------
def scrape_id(it):
    m = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", it.get("maps_url") or "")
    return "s:" + (m.group(1) if m else hashlib.md5(f"{it.get('name')}|{it.get('address')}".encode()).hexdigest()[:12])

# ---------- scraper jobs: queue in `runs`, executed by worker.py (or inline for local dev) ----------
SCRAPER = os.getenv("LEADPIPE_SCRAPER", os.path.join(HERE, "maps_scraper.py"))
MAX_ATTEMPTS = int(os.getenv("SCRAPE_MAX_ATTEMPTS", "3"))
IDLE_TIMEOUT = int(os.getenv("SCRAPE_IDLE_TIMEOUT", "300"))       # seconds without scraper output (0.1 CPU: one slow page can take >2 min)
WORKER_MODE = os.getenv("WORKER_MODE", "inline")                  # inline (local) | remote (Render web: wait for worker)
EXIT_BUSY = 5                                                     # maps_scraper.py: another scraper already running
STOP = threading.Event()
# Process-level half of the "one scraper at a time" rule (the scraper's own file lock is the cross-process half).
# Re-entrant so run_scrape() can hold it across claim_job + execute_job.
_JOB_SLOT = threading.RLock()

def kill_tree(proc, grace=5):
    """Terminate the scraper AND every Chromium child, then SIGKILL stragglers. Cross-platform."""
    try: root = psutil.Process(proc.pid)
    except psutil.NoSuchProcess: return
    procs = root.children(recursive=True) + [root]
    for p in procs:
        try: p.terminate()
        except psutil.Error: pass
    _, alive = psutil.wait_procs(procs, timeout=grace)
    for p in alive:
        try: p.kill()
        except psutil.Error: pass
    psutil.wait_procs(alive, timeout=3)

def sweep_orphans():
    """Worker start-up only: kill Playwright Chromium left behind by a previous crashed worker."""
    n = 0
    for p in psutil.process_iter(["cmdline"]):
        try:
            if any("ms-playwright" in a for a in (p.info["cmdline"] or [])) and p.pid != os.getpid(): p.kill(); n += 1
        except psutil.Error: pass
    return n

PER_SEARCH_MAX = 120

def plan_cells(location, target, step_km=1.2, zoom=16):
    """Grid of map viewports over the location's bounding box, nearest to the centre first."""
    r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": location, "format": "json", "limit": 1},
                     headers={"User-Agent": "leadpipe/1.3 (personal lead tool)"}, timeout=20).json()
    if not r: return []
    s, n, w, e = map(float, r[0]["boundingbox"]); clat, clng = float(r[0]["lat"]), float(r[0]["lon"])
    kx = max(math.cos(math.radians(clat)), 0.2)
    rows = max(1, round((n - s) / (step_km / 111.0))); cols = max(1, round((e - w) / (step_km / (111.0 * kx))))
    cells = [(s + (i + .5) * (n - s) / rows, w + (j + .5) * (e - w) / cols) for i in range(rows) for j in range(cols)]
    cells.sort(key=lambda c: (c[0] - clat) ** 2 + ((c[1] - clng) * kx) ** 2)
    max_cells = min(150, max(3, target // 15))
    return [f"{la:.5f},{ln:.5f},{zoom}" for la, ln in cells[:max_cells]]

def enqueue_scrape(query, location, limit=30):
    try: cells = plan_cells(location, limit)
    except Exception: cells = []                      # fall back to a plain text search
    c = db()
    rid = c.execute("INSERT INTO runs(at,query,source,fetched,added,changed,calls,location,status,requested,params,attempts) VALUES(?,?,?,0,0,0,0,?,?,?,?,0) RETURNING id",
                    (now(), query, "scrape", location, "queued", limit, json.dumps(dict(query=query, location=location, limit=limit, cells=cells)))).fetchone()[0]
    c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (rid, now(), "queued",
              f"Queued: {query} in {location}, {limit} new places across {len(cells) or 1} search area(s)"))
    c.commit(); c.close(); return rid

def claim_job(worker_id, run_id=None):
    """Atomically claim one queued scrape job (FOR UPDATE SKIP LOCKED: safe with several workers)."""
    c = db()
    q = ("UPDATE runs SET status='running', worker_id=?, heartbeat_at=?, attempts=COALESCE(attempts,0)+1 "
         "WHERE id=(SELECT id FROM runs WHERE status='queued' AND source='scrape'" + (" AND id=?" if run_id else "") +
         " ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *")
    row = c.execute(q, (worker_id, now()) + ((run_id,) if run_id else ())).fetchone()
    c.commit(); c.close(); return row

def reap_stale(max_age=120):
    """Mark/requeue 'running' jobs whose worker stopped heartbeating. Call from worker loop and dashboard load."""
    c = db(); n = 0
    for r in c.execute("SELECT id,source,attempts,at,heartbeat_at,fetched FROM runs WHERE status='running'").fetchall():
        age = (dt.datetime.now() - dt.datetime.fromisoformat(r["heartbeat_at"] or r["at"])).total_seconds()
        if age < (max_age if r["source"] == "scrape" else 900): continue
        resume = WORKER_MODE == "remote" and r["source"] == "scrape" and (r["attempts"] or 0) < MAX_ATTEMPTS
        st = "queued" if resume else ("partial" if (r["fetched"] or 0) else "failed")
        k = c.execute("UPDATE runs SET status=?, error=?, finished_at=? WHERE id=? AND status='running'",
                      (st, None if resume else "Interrupted by a server restart", None if resume else now(), r["id"])).rowcount
        if k:
            c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (r["id"], now(), "warn",
                      f"No heartbeat for {int(age)}s: worker died/restarted. " + ("Re-queued; will resume." if resume else f"Marked {st}.")))
            n += 1
    c.commit(); c.close(); return n

def execute_job(job, on_progress=None):
    with _JOB_SLOT:                      # never two scrapes (= two Chromiums) in this process
        return _execute_job(job, on_progress)
    
def _execute_job(job, on_progress=None):
    rid, wid = job["id"], job["worker_id"]
    p = json.loads(job["params"] or "{}"); query, location, limit = p["query"], p["location"], int(p.get("limit") or 30)
    c = db()
    t = dict(fetched=job["fetched"] or 0, added=job["added"] or 0, changed=job["changed"] or 0, nc=job["no_contact"] or 0, blocked=False, err=None, n_ev=0)
    remaining = max(limit - t["added"], 0)
    prog = dict(run_id=rid, total=limit, done=t["added"], collected=t["fetched"], skipped=0, phase="Opening Google Maps")
    def ev(kind, text):
        t["n_ev"] += 1
        if t["n_ev"] > 12000 and kind not in ("end", "error"): return
        c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (rid, now(), kind, text[:600])); c.commit()
        if on_progress: on_progress(dict(prog))
    def hb():
        c.execute("UPDATE runs SET heartbeat_at=?,fetched=?,added=?,changed=?,no_contact=? WHERE id=?", (now(), t["fetched"], t["added"], t["changed"], t["nc"], rid)); c.commit()
    ev("start", f"Attempt {job['attempts']}/{MAX_ATTEMPTS}: {query} in {location} (up to {remaining} new places) [{wid}]")
    tmpd = tempfile.mkdtemp(prefix="scrape_"); skipf = os.path.join(tmpd, "skip.txt")
    skip = [r[0] for r in c.execute("SELECT substr(id,3) FROM leads WHERE source='scrape' AND id LIKE 's:0x%'")]
    with open(skipf, "w", encoding="utf-8") as f: f.write("\n".join(skip))
    ev("info", f"{len(skip)} known places will be skipped; looking for {remaining} new ones")
    def handle(line):
        if line.startswith("RESULT "):
            try: it = json.loads(line[7:])
            except ValueError: return ev("warn", "unparseable RESULT: " + line[:200])
            res = save_row(c, dict(id=scrape_id(it), source="scrape", name=it.get("name"), category=query, phone=it.get("phone"), website=it.get("website"), address=it.get("address"), lat=it.get("lat"), lng=it.get("lng"), maps_url=it.get("maps_url"), rating=it.get("rating"), reviews=it.get("reviews"), status="CLOSED_PERMANENTLY" if it.get("permanently_closed") else "active"), now()); c.commit()
            if res != "skipped":
                t["fetched"] += 1; t["added"] += res == "added"; t["changed"] += res == "updated"
                nc = not (it.get("phone") or it.get("website")); t["nc"] += nc
                prog.update(collected=t["fetched"], skipped=t["nc"])
                ev("place", f"{it.get('name')}: {it.get('phone') or 'no phone'}" + (" (no contact info)" if nc else ""))
            return
        if m := re.match(r"found (\d+) places", line): prog.update(phase="Reading places")
        elif m := re.match(r"PROGRESS (\d+)/(\d+)", line): prog.update(done=int(m[1]), total=int(m[2]))
        if line.startswith("STOPPED"): t["blocked"] = True; t["err"] = line.split(":", 1)[-1].strip()[:250]
        kind = "error" if re.search(r"\b(ERROR|Traceback|Error|Exception)\b", line) else "warn" if " WARN " in line else "log"
        ev(kind, line)
    cmd = [sys.executable, "-u", SCRAPER, "-q", query, "-l", location, "-n", str(remaining), "-o", os.path.join(tmpd, "out.json"), "--jsonl", "--skip-keys", skipf]
    for cz in p.get("cells") or []: cmd += ["-c", cz]
    reason = None; rc = None; q = queue.Queue()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    def pump():
        for ln in proc.stdout: q.put(ln)
        q.put(None)
    threading.Thread(target=pump, daemon=True).start()
    t0 = last_out = last_hb = time.time()
    try:
        while True:
            if STOP.is_set(): reason = "shutdown"; break
            try: ln = q.get(timeout=2)
            except queue.Empty:
                now_ = time.time()
                if now_ - last_out > IDLE_TIMEOUT: reason = f"no scraper output for {IDLE_TIMEOUT}s (hung)"; break
                if now_ - t0 > limit * 60 + 600: reason = "hard time cap exceeded"; break
                if now_ - last_hb > 10: hb(); last_hb = now_
                continue
            if ln is None: break
            last_out = time.time()
            if ln.strip(): handle(ln.rstrip())
            if time.time() - last_hb > 10: hb(); last_hb = time.time()
    except Exception as e: reason = f"worker exception: {type(e).__name__}: {e}"; ev("error", reason)
    finally:
        if proc.poll() is None: kill_tree(proc)
        try: rc = proc.wait(timeout=10)
        except Exception: rc = None
        shutil.rmtree(tmpd, ignore_errors=True)
    ev("info", f"Scraper process exit code: {rc}" + (f" (stopped: {reason})" if reason else ""))
    attempts = job["attempts"] or 1
    if reason == "shutdown": status, error, fin = "queued", None, None; ev("warn", "Worker shutting down: job re-queued, will resume (no results lost)")
    elif t["blocked"]: status, error, fin = ("partial" if t["fetched"] else "failed"), t["err"], now()
    elif rc == EXIT_BUSY and not reason:
        status, error, fin = "queued", None, None
        c.execute("UPDATE runs SET attempts=GREATEST(COALESCE(attempts,1)-1,0) WHERE id=?", (rid,))
        ev("warn", "Another scraper process holds the single scraper slot; re-queued without using an attempt")
    elif reason or rc != 0:
        error = reason or f"Scraper exited with code {rc}"
        if attempts < MAX_ATTEMPTS: status, fin = "queued", None; ev("warn", f"{error}. Re-queued for resume ({attempts}/{MAX_ATTEMPTS} attempts used)")
        else: status, fin = ("partial" if t["fetched"] else "failed"), now()
    else: status, error, fin = "done", None, now()
    c.execute("UPDATE runs SET fetched=?,added=?,changed=?,no_contact=?,status=?,finished_at=?,error=?,heartbeat_at=? WHERE id=?", (t["fetched"], t["added"], t["changed"], t["nc"], status, fin, error, now(), rid))
    prog["phase"] = "Finished" if fin else "Re-queued"
    ev("end" if fin else "info", f"{status}: {t['fetched']} saved ({t['added']} new, {t['changed']} updated, {t['nc']} without contact)" + (f". {error}" if error else ""))
    c.commit(); c.close(); return status


def wait_run(rid, on_progress=None, poll=3):
    c = db()
    try:
        while True:
            r = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone(); c.commit()
            if on_progress: on_progress(dict(run_id=rid, total=r["requested"] or 0, done=r["fetched"] or 0,
                                            collected=r["fetched"] or 0, skipped=r["no_contact"] or 0, phase=r["status"]))
            if r["status"] in ("done", "partial", "failed"): return r
            time.sleep(poll)
    finally: c.close()

def run_scrape(query, location, limit=30, timeout=None, on_progress=None):
    """Same signature as before. inline: runs here (local dev). remote: queues for worker.py and waits."""
    global LAST_WARNING
    LAST_WARNING = None
    rid = enqueue_scrape(query, location, limit)
    if WORKER_MODE != "remote":
        with _JOB_SLOT:                  # claim and execute under one hold so a waiting job is never 'running' without a heartbeat
            job = claim_job(f"inline:{os.getpid()}", rid)
            if job: execute_job(job, on_progress)
    r = wait_run(rid, on_progress)
    if r["status"] == "failed": raise RuntimeError(r["error"] or "Scrape failed")
    LAST_WARNING = r["error"]
    return r["fetched"] or 0, r["added"] or 0, r["changed"] or 0

# ---------- settings + sending helpers (shared by dashboard and Telegram bot) ----------
DEFAULTS = {"template": "Hi {name} 👋 I found your {category} business on Google Maps. [Write your offer here]. Not interested? Just reply STOP and I won't message again.",
            "daily_limit": "20", "last_location": "", "media_type": "", "media_id": ""}
SENDABLE = ("is_mobile=1 AND outreach='new' AND dup_of IS NULL "
            "AND COALESCE(status,'') NOT IN ('STALE','CLOSED_PERMANENTLY','CLOSED_TEMPORARILY')")

def get_setting(c, k):
    r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else DEFAULTS.get(k, "")

def set_setting(c, k, v):
    c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v))); c.commit()

def render(tpl, lead):
    return tpl.replace("{name}", str(lead["name"])).replace("{category}", str(lead["category"]))

def wa_link(phone, text=""):
    return "https://wa.me/" + phone.lstrip("+") + ("?text=" + quote(text) if text else "")

def sendable(c, n, exclude=()):
    rows = c.execute(f"SELECT * FROM leads WHERE {SENDABLE} ORDER BY priority DESC, last_seen DESC, score DESC, first_seen DESC, id DESC LIMIT ?", (n + len(exclude),)).fetchall()
    return [r for r in rows if r["id"] not in exclude][:n]

def sent_today(c):
    return c.execute("SELECT COUNT(*) FROM leads WHERE contacted_at LIKE ? AND outreach IN ('messaged','replied','interested','not_interested')",
                     (dt.date.today().isoformat() + "%",)).fetchone()[0]

def sendable_count(c):
    return c.execute(f"SELECT COUNT(*) FROM leads WHERE {SENDABLE}").fetchone()[0]
