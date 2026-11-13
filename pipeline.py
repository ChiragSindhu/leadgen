"""Local lead pipeline v1.1: Google Places (New) + OpenStreetMap + manual/JSON -> SQLite."""
import os, sys, threading, sqlite3, json, re, time, hashlib, subprocess, tempfile, datetime as dt
from urllib.parse import quote
import requests, phonenumbers

HERE = os.path.dirname(os.path.abspath(__file__))
def _load_env():   # every entry point (server, bot, scraper) reads .env
    f = os.path.join(HERE, ".env")
    if os.path.exists(f):
        for ln in open(f, encoding="utf-8-sig"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
_load_env()
DATA_DIR = os.getenv("DATA_DIR") or HERE
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "leads.db")   # one DB shared by server and bot
LAST_WARNING = None
REGION = "IN"  # default country for numbers without a +code
UA = {"User-Agent": "leadpipe/1.1 (personal lead tool)"}
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

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY, source TEXT, name TEXT, category TEXT, address TEXT,
  lat REAL, lng REAL, phone TEXT, is_mobile INT, website TEXT, email TEXT, maps_url TEXT, rating REAL,
  reviews INT, status TEXT, score INT, hash TEXT, first_seen TEXT, last_seen TEXT,
  outreach TEXT DEFAULT 'new', notes TEXT DEFAULT '', dup_of TEXT, contacted_at TEXT);
CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT, at TEXT,
  field TEXT, old TEXT, new TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, query TEXT, source TEXT,
  fetched INT, added INT, changed INT, calls INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS run_events(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INT, at TEXT, kind TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS idx_phone ON leads(phone);
"""

def now(): return dt.datetime.now().isoformat(timespec="seconds")

def db():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=30); c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')   # dashboard + bot can share the file safely
    c.executescript(SCHEMA)
    for t, col, typ in [("leads", "dup_of", "TEXT"), ("leads", "contacted_at", "TEXT"),
                        ("runs", "calls", "INT DEFAULT 0"), ("runs", "location", "TEXT"),
                        ("runs", "status", "TEXT DEFAULT 'done'"), ("runs", "finished_at", "TEXT"),
                        ("runs", "requested", "INT"), ("runs", "error", "TEXT")]:   # migrate older DBs
        if col not in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
    c.commit(); return c

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

# ---------- sources ----------
def fetch_google(key, query, lat, lng, radius_m, max_pages=3, counter=None):
    if not key: raise RuntimeError("Google API key missing")
    mask = ("places.id,places.displayName,places.formattedAddress,places.location,"
            "places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,"
            "places.googleMapsUri,places.businessStatus,places.rating,places.userRatingCount,nextPageToken")
    body = {"textQuery": query, "pageSize": 20, "locationBias": {"circle": {
        "center": {"latitude": lat, "longitude": lng}, "radius": float(min(radius_m, 50000))}}}
    out = []
    for _ in range(max_pages):
        resp = requests.post("https://places.googleapis.com/v1/places:searchText", json=body, timeout=30,
                             headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": mask})
        if counter is not None: counter[0] += 1
        r = resp.json()
        if "error" in r: raise RuntimeError(r["error"].get("message", "Google API error"))
        for p in r.get("places", []):
            loc = p.get("location", {})
            out.append(dict(id="g:" + p["id"], source="google", name=p.get("displayName", {}).get("text"),
                category=query, address=p.get("formattedAddress"), lat=loc.get("latitude"), lng=loc.get("longitude"),
                phone=p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"),
                website=p.get("websiteUri"), maps_url=p.get("googleMapsUri"), rating=p.get("rating"),
                reviews=p.get("userRatingCount"), status=p.get("businessStatus")))
        if not r.get("nextPageToken"): break
        body["pageToken"] = r["nextPageToken"]; time.sleep(1.5)
    return out

OSM_TAGS = {"real estate": '["office"="estate_agent"]', "pg": '["tourism"~"hostel|guest_house"]',
            "hostel": '["tourism"="hostel"]', "gym": '["leisure"="fitness_centre"]',
            "clinic": '["amenity"~"clinic|doctors"]', "salon": '["shop"="hairdresser"]',
            "restaurant": '["amenity"="restaurant"]', "school": '["amenity"="school"]'}

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]

def fetch_osm(category, lat, lng, radius_m):
    tag = OSM_TAGS.get(category.lower())
    m = re.fullmatch(r"(\w+)=(\w+)", category.strip())      # raw OSM tag, e.g. shop=bakery
    if not tag and m: tag = f'["{m.group(1)}"="{m.group(2)}"]'
    if not tag: raise RuntimeError(f"OSM: unknown category '{category}'. Use one of {list(OSM_TAGS)} or key=value (e.g. shop=bakery)")
    q = f"[out:json][timeout:60];nwr{tag}(around:{int(radius_m)},{lat},{lng});out center tags;"
    els, last = None, ""
    for url in OVERPASS:                       # try every mirror, 2 attempts each
        for attempt in range(2):
            try:
                resp = requests.post(url, data={"data": q}, headers=UA, timeout=90)
                if resp.status_code == 200 and "elements" in resp.json(): els = resp.json()["elements"]; break
                last = f"{url.split('/')[2]}: HTTP {resp.status_code} {resp.text[:120]!r}"
            except Exception as e: last = f"{url.split('/')[2]}: {type(e).__name__}: {str(e)[:120]}"
            time.sleep(3 * (attempt + 1))
        if els is not None: break
    if els is None: raise RuntimeError(f"All OpenStreetMap servers failed. Last error -> {last}. Use the Google Maps scraper source instead.")
    out = []
    for e in els:
        t = e.get("tags", {}); c = e.get("center", e)
        out.append(dict(id=f"o:{e['type']}{e['id']}", source="osm", name=t.get("name"), category=category,
            address=t.get("addr:full") or " ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:city")])) or None,
            lat=c.get("lat"), lng=c.get("lon"),
            phone=t.get("phone") or t.get("contact:phone") or t.get("contact:mobile"),
            website=t.get("website") or t.get("contact:website"), email=t.get("email") or t.get("contact:email"),
            maps_url=f"https://www.openstreetmap.org/{e['type']}/{e['id']}", status="active"))
    return out

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
    """Google Places API / OpenStreetMap run, logged like the scraper (runs + run_events)."""
    c = db(); counter = [0]; rows = []; err = None
    run_id = c.execute("INSERT INTO runs(at,query,source,fetched,added,changed,calls,location,status,requested) VALUES(?,?,?,0,0,0,0,?,?,?)",
                       (now(), query, source, location, "running", limit)).lastrowid; c.commit()
    prog = dict(run_id=run_id, total=0, done=0, collected=0, skipped=0, phase="Fetching from " + source)
    def ev(kind, text):
        c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (run_id, now(), kind, text)); c.commit()
        if on_progress: on_progress(dict(prog))
    ev("start", f"Started {source}: {query}" + (f" near {location}" if location else "") + f", radius {radius_m / 1000:g} km")
    try:
        if source == "google":
            used = google_used(c)
            if used + max_pages > cap: raise RuntimeError(f"Monthly Google call cap reached ({used}/{cap}). Raise the cap or use another source.")
            rows = fetch_google(key, query, lat, lng, radius_m, max_pages, counter)
        else: rows = fetch_osm(query, lat, lng, radius_m)
        ev("found", f"{source} returned {len(rows)} places")
    except Exception as e:
        err = e; ev("warn", str(e)[:250])
    keep = [r for r in rows if r.get("phone") or r.get("website")]
    skipped = len(rows) - len(keep)
    if limit: keep = keep[:limit]
    prog.update(total=len(rows), done=len(rows), collected=len(keep), skipped=skipped, phase="Saving leads")
    if rows: ev("skip", f"Skipped {skipped} with no phone or website")
    ts = now(); res = [save_row(c, r, ts) for r in keep]
    added, changed = res.count("added"), res.count("updated")
    c.execute("UPDATE runs SET fetched=?,added=?,changed=?,calls=?,status=?,finished_at=?,error=? WHERE id=?",
              (len(keep), added, changed, counter[0], "failed" if err else "done", now(), str(err)[:250] if err else None, run_id))
    prog["phase"] = "Finished"
    ev("end", f"Finished: {len(keep)} saved ({added} new, {changed} updated)" + (f", {counter[0]} Google calls" if counter[0] else ""))
    c.commit(); c.close()
    if err: raise err
    return len(keep), added, changed

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

# ---------- Google Maps scraper as a source (runs maps_scraper.py as a subprocess: safe on Windows/Streamlit) ----------
def scrape_id(it):
    m = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", it.get("maps_url") or "")
    return "s:" + (m.group(1) if m else hashlib.md5(f"{it.get('name')}|{it.get('address')}".encode()).hexdigest()[:12])

def run_scrape(query, location, limit=30, timeout=None, on_progress=None):
    """Runs maps_scraper.py, streams its output into a run log (runs + run_events), then saves leads."""
    global LAST_WARNING
    LAST_WARNING = None
    here = os.path.dirname(os.path.abspath(__file__))
    tmp = os.path.join(tempfile.gettempdir(), f"scrape_{int(time.time()*1000)}.json")
    c = db()
    run_id = c.execute("INSERT INTO runs(at,query,source,fetched,added,changed,calls,location,status,requested) VALUES(?,?,?,0,0,0,0,?,?,?)",
                       (now(), query, "scrape", location, "running", limit)).lastrowid; c.commit()
    prog = dict(run_id=run_id, total=0, done=0, collected=0, skipped=0, phase="Opening Google Maps")
    def ev(kind, text):
        c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (run_id, now(), kind, text)); c.commit()
        if on_progress: on_progress(dict(prog))
    ev("start", f"Started: {query} in {location} (up to {limit})")
    cmd = [sys.executable, "-u", os.path.join(here, "maps_scraper.py"), "-q", query, "-l", location, "-n", str(limit), "-o", tmp, "--skip-no-contact"]
    err = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        timer = threading.Timer(timeout or limit * 15 + 180, proc.kill); timer.start()
        for line in proc.stdout:
            line = line.strip()
            if m := re.match(r"found (\d+) places", line):
                prog.update(total=int(m[1]), phase="Reading places"); ev("found", f"Found {m[1]} places on the map")
            elif m := re.match(r"\[(\d+)/(\d+)\] skipped \(no contact\): (.*)", line):
                prog.update(done=int(m[1]), skipped=prog["skipped"] + 1); ev("skip", f"Skipped {m[3]} (no phone or website)")
            elif m := re.match(r"\[(\d+)/(\d+)\] (.*?) \| (.*)", line):
                prog.update(done=int(m[1]), collected=prog["collected"] + 1); ev("place", f"{m[3]}: {m[4]}")
            elif line.startswith("STOPPED"):
                err = line.split(":", 1)[-1].strip()[:250]; ev("warn", line[:250])
        proc.wait(); timer.cancel()
        if proc.returncode != 0 and not err: err = "Scraper crashed or timed out"
    except Exception as e: err = str(e)[:250]
    items = []
    if os.path.exists(tmp):
        items = json.load(open(tmp, encoding="utf-8")).get("businesses", []); os.remove(tmp)
    prog["phase"] = "Saving leads"; ev("save", f"Saving {len(items)} leads")
    ts = now(); res = []
    for it in items:
        res.append(save_row(c, dict(id=scrape_id(it), source="scrape", name=it.get("name"), category=query,
            phone=it.get("phone"), website=it.get("website"), address=it.get("address"), lat=it.get("lat"), lng=it.get("lng"),
            maps_url=it.get("maps_url"), rating=it.get("rating"), reviews=it.get("reviews"),
            status="CLOSED_PERMANENTLY" if it.get("permanently_closed") else "active"), ts))
    added, changed = res.count("added"), res.count("updated")
    status = "failed" if (err and not items) else ("partial" if err else "done")
    c.execute("UPDATE runs SET fetched=?,added=?,changed=?,status=?,finished_at=?,error=? WHERE id=?",
              (len(items), added, changed, status, now(), err, run_id))
    prog["phase"] = "Finished"
    ev("end", f"Finished ({status}): {len(items)} with contact info, {added} new, {changed} updated" + (f". {err}" if err else ""))
    c.commit(); c.close()
    if err and not items: raise RuntimeError(err)
    LAST_WARNING = err
    return len(items), added, changed

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
    rows = c.execute(f"SELECT * FROM leads WHERE {SENDABLE} ORDER BY score DESC, first_seen LIMIT ?", (n + len(exclude),)).fetchall()
    return [r for r in rows if r["id"] not in exclude][:n]

def sent_today(c):
    return c.execute("SELECT COUNT(*) FROM leads WHERE contacted_at LIKE ? AND outreach IN ('messaged','replied','interested','not_interested')",
                     (dt.date.today().isoformat() + "%",)).fetchone()[0]
