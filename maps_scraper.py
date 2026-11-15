"""Google Maps scraper (Playwright). Personal-scale, slow on purpose, tuned for a 0.1 CPU / 512 MB container.
Stops (never evades) on CAPTCHA -> exit code 3.
Run: python maps_scraper.py -q "real estate" -l "Indiranagar, Bengaluru" -n 40 -o leads.json
Protocol lines for the parent: 'found N places', '[i/n] name | phone', 'RESULT {json}', 'STOPPED: ...'.

Exit codes: 0 ok | 1 unexpected crash | 3 CAPTCHA/block page (never bypassed) | 4 search/browser unusable
            5 another scraper process already holds the single-scraper slot (nothing was done)
Tuning knobs (env, all optional): SCRAPER_NAV_TIMEOUT_MS, SCRAPER_OP_TIMEOUT_MS, SCRAPER_HEAP_MB,
  SCRAPER_RSS_SOFT_MB, SCRAPER_RSS_HARD_MB, SCRAPER_CONTEXT_EVERY, SCRAPER_BROWSER_EVERY_CONTEXTS,
  SCRAPER_BLOCK_TILES (0 to allow map tiles), SCRAPER_EXTRA_ARGS, SCRAPER_LOCK_FILE."""
import argparse, json, os, random, re, shlex, signal, sys, tempfile, time, traceback, datetime as dt
from urllib.parse import quote

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError
except ImportError:                       # importable (and testable) without playwright installed
    sync_playwright = None
    class PWError(Exception): pass
    class PWTimeout(PWError): pass
try: import psutil
except ImportError: psutil = None


def _env_int(name, default):
    try: return int(os.getenv(name, default))
    except (TypeError, ValueError): return default

# ---- configuration -------------------------------------------------------------------------------------
NAV_TIMEOUT_MS = _env_int("SCRAPER_NAV_TIMEOUT_MS", 60000)   # 0.1 CPU: Maps needs far longer than on a laptop
OP_TIMEOUT_MS = _env_int("SCRAPER_OP_TIMEOUT_MS", 30000)
H1_TIMEOUT_MS, FEED_TIMEOUT_MS, SETTLE_MS = 20000, 30000, 2500
HEAP_MB = _env_int("SCRAPER_HEAP_MB", 192)            # per-renderer V8 cap: dies (recoverably) before the container does
RSS_SOFT_MB = _env_int("SCRAPER_RSS_SOFT_MB", 330)    # whole process tree: above this -> fresh context
RSS_HARD_MB = _env_int("SCRAPER_RSS_HARD_MB", 420)    # above this -> relaunch Chromium
CONTEXT_EVERY = _env_int("SCRAPER_CONTEXT_EVERY", 40) # places per context when memory is fine (keeps HTTP cache warm)
BROWSER_EVERY_CONTEXTS = _env_int("SCRAPER_BROWSER_EVERY_CONTEXTS", 5)
MAX_CONSEC_FAIL = 5                                   # stop instead of hammering Google when everything fails
BLOCK_TILES = os.getenv("SCRAPER_BLOCK_TILES", "1") != "0"
NODE_HEAP_MB = _env_int("SCRAPER_NODE_HEAP_MB", 64)    # Playwright's Node driver: ~140 MB -> ~110 MB. Not applied if NODE_OPTIONS is already set

ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-zygote", "--disable-extensions", "--mute-audio",
        "--renderer-process-limit=1", "--disable-site-isolation-trials",
        "--blink-settings=imagesEnabled=false",       # Chromium never issues image requests -> fewer route round-trips
        "--disable-domain-reliability", "--disable-speech-api", "--disable-print-preview",
        f"--js-flags=--max-old-space-size={HEAP_MB}"] + shlex.split(os.getenv("SCRAPER_EXTRA_ARGS", ""))

# ---- resource blocking ---------------------------------------------------------------------------------
# Never blocked: documents (CAPTCHA / consent pages must load), scripts, XHR/fetch, stylesheets, recaptcha.
BLOCK_TYPES = frozenset(("image", "media", "font", "ping"))
BLOCK_MARKERS = ("google-analytics.com", "googletagmanager.com", "doubleclick.net", "googlesyndication.com",
                 "googleadservices.com", "connect.facebook.net", "/gen_204", "play.google.com/log",
                 "/maps/vt", "/kh?") if BLOCK_TILES else (
                 "google-analytics.com", "googletagmanager.com", "doubleclick.net", "googlesyndication.com",
                 "googleadservices.com", "connect.facebook.net", "/gen_204", "play.google.com/log")

def should_block(resource_type, url):
    if resource_type == "document": return False
    if resource_type in BLOCK_TYPES: return True
    return any(m in url for m in BLOCK_MARKERS)

# ---- state / logging / helpers -------------------------------------------------------------------------
STOP = False
def log(level, msg): print(f"{dt.datetime.now():%H:%M:%S} {level} {msg}", flush=True)

def _sig(signum, _frame):
    global STOP
    if STOP: raise KeyboardInterrupt          # second signal: unwind now; finally-blocks still save and close
    STOP = True; log("WARN", "termination signal received; finishing current step and saving")
signal.signal(signal.SIGTERM, _sig); signal.signal(signal.SIGINT, _sig)

class Blocked(RuntimeError):
    """CAPTCHA / block page. Always ends the run with exit code 3; never retried, never bypassed."""
class BrowserUnavailable(Exception):
    """Chromium cannot be (re)started. Ends the run with exit code 4."""

COORD = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
def parse_coords(url):
    m = COORD.search(url or ""); return (float(m[1]), float(m[2])) if m else (None, None)
def clean_phone(item_id):
    m = re.search(r"phone:tel:([+\d]+)", item_id or ""); return m[1] if m else None

def nap(a=1.5, b=3.5):
    """Deliberately slow, but interruptible so SIGTERM never waits out a full pause."""
    end = time.monotonic() + random.uniform(a, b)
    while not STOP and (left := end - time.monotonic()) > 0: time.sleep(min(left, 0.5))

def tree_rss_mb():
    """RSS of this process + node driver + all Chromium processes (slight over-count: conservative). None if no psutil."""
    if psutil is None: return None
    try:
        me = psutil.Process(); total = me.memory_info().rss
        for ch in me.children(recursive=True):
            try: total += ch.memory_info().rss
            except psutil.Error: pass
        return total / 1048576
    except psutil.Error: return None

def browser_gone(exc):
    m = str(exc).lower()
    return any(x in m for x in ("target closed", "has been closed", "browser closed", "connection closed", "disconnected"))

def blocked(page):
    try: return "/sorry/" in page.url or page.locator("iframe[src*='recaptcha']").count() > 0
    except PWError: return False

def note_status(resp, what):
    try:
        if resp is not None and resp.status >= 400: log("WARN", f"HTTP {resp.status} {what[:110]}")
    except Exception: pass

def accept_consent(page):
    try: page.get_by_role("button", name=re.compile("Reject all|Accept all", re.I)).first.click(timeout=3000)
    except Exception: pass

# ---- browser session: ONE Chromium, isolated contexts -------------------------------------------------
class Session:
    def __init__(s, pw, headful):
        s.pw, s.headful = pw, headful
        s.browser = s.ctx = s.page = None
        s.n = 0                  # places scraped in the current context
        s.contexts = 0           # contexts opened on the current browser
        s.dead = False           # browser disconnected
        s.page_crashed = False   # renderer crashed (typically OOM)
        s.closing = False
        s.launches = s.ctx_recycles = s.blocked_reqs = s.page_errors = 0
        s.peak_rss = 0.0

    def launch(s):
        s.close()
        for attempt in (1, 2, 3):
            t0 = time.time()
            try:
                s.browser = s.pw.chromium.launch(headless=not s.headful, args=ARGS); break
            except (PWError, OSError) as e:
                log("ERROR", f"browser launch attempt {attempt}/3 failed: {type(e).__name__}: {str(e)[:200]}")
                if attempt == 3: raise BrowserUnavailable(f"cannot start Chromium: {str(e)[:200]}")
                time.sleep(3 * attempt)
        s.dead = False; s.contexts = 0; s.launches += 1
        s.browser.on("disconnected", s._gone)
        rss = tree_rss_mb() or 0; s.peak_rss = max(s.peak_rss, rss)
        log("INFO", f"browser launched in {time.time() - t0:.1f}s (launch #{s.launches}, chromium {getattr(s.browser, 'version', '?')}, "
                    f"heap cap {HEAP_MB} MB, rss {rss:.0f} MB)")

    def _gone(s, *_):
        if not s.closing: s.dead = True; log("ERROR", "browser disconnected/crashed")

    def _route(s, route):
        try:
            r = route.request
            if should_block(r.resource_type, r.url): s.blocked_reqs += 1; route.abort()
            else: route.continue_()
        except PWError: pass                      # page/context closed mid-request

    def new_context(s):
        s.close_context()
        s.ctx = s.browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900}, service_workers="block")
        s.ctx.route("**/*", s._route)
        s.page = s.ctx.new_page(); s.page_crashed = False; s.page_errors = 0; s.contexts += 1
        s.page.set_default_timeout(OP_TIMEOUT_MS); s.page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        s.page.on("crash", s._crashed)
        s.page.on("pageerror", s._pageerror)
        s.page.on("requestfailed", lambda r: log("WARN", f"requestfailed {r.url[:110]} {r.failure}") if r.resource_type == "document" else None)
        s.n = 0

    def _crashed(s, *_): s.page_crashed = True; log("ERROR", "page crashed (likely out of memory)")
    def _pageerror(s, e):
        s.page_errors += 1                        # Maps with blocked assets can be noisy: cap the log volume
        if s.page_errors <= 5: log("WARN", f"pageerror: {str(e)[:200]}")

    def close_context(s):
        ctx, s.ctx, s.page = s.ctx, None, None
        if ctx:
            try: ctx.close()
            except Exception as e: log("WARN", f"context close failed: {type(e).__name__}")

    def close(s):
        s.closing = True
        try:
            s.close_context()
            b, s.browser = s.browser, None
            if b:
                try: b.close()
                except Exception as e: log("WARN", f"browser close failed: {type(e).__name__}")
        finally: s.closing = False

    def ensure(s):
        """Called before every operation: heal a dead browser or crashed page instead of failing the run."""
        if s.browser is None or s.dead or not s.browser.is_connected(): s.restart_browser("not running")
        elif s.page is None or s.page_crashed: s.recycle_context("page crashed" if s.page_crashed else "no page")

    def restart_browser(s, why):
        log("INFO", f"restarting Chromium ({why})"); s.launch(); s.new_context()

    def recycle_context(s, why):
        log("INFO", f"recycling browser context ({why})"); s.ctx_recycles += 1; s.new_context()

    def recover(s, exc):
        if s.dead or browser_gone(exc) or (s.browser is not None and not s.browser.is_connected()): s.restart_browser(type(exc).__name__)
        else: s.recycle_context(type(exc).__name__)

    def maybe_recycle(s):
        """Memory-driven, not clock-driven: contexts are cheap, browser relaunch (CPU-heavy at 0.1 vCPU) is the last resort."""
        rss = tree_rss_mb()
        if rss: s.peak_rss = max(s.peak_rss, rss)
        if rss and rss >= RSS_HARD_MB: s.restart_browser(f"rss {rss:.0f} MB >= hard limit {RSS_HARD_MB} MB")
        elif s.n >= CONTEXT_EVERY or (rss and rss >= RSS_SOFT_MB):
            why = f"{s.n} places" if s.n >= CONTEXT_EVERY else f"rss {rss:.0f} MB >= soft limit {RSS_SOFT_MB} MB"
            if s.contexts >= BROWSER_EVERY_CONTEXTS: s.restart_browser(f"{why}; browser served {s.contexts} contexts")
            else: s.recycle_context(why)

class SingleInstance:
    """OS-level advisory lock: only ONE scraper process may run per machine. Released automatically if the process dies."""
    def __init__(s, path): s.path, s.f = path, None
    def acquire(s):
        s.f = open(s.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt; msvcrt.locking(s.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl; fcntl.flock(s.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            s.f.close(); s.f = None; return False
        return True
    def release(s):
        if s.f:
            try: s.f.close()
            except Exception: pass
            s.f = None

# ---- scraping ------------------------------------------------------------------------------------------
# One evaluate per scroll instead of one round-trip per link; checks only the last cards for the end marker.
FEED_JS = """(limit) => {
  const feed = document.querySelector('div[role="feed"]'); if (!feed) return null;
  const hrefs = [...feed.querySelectorAll('a[href*="/maps/place/"]')].map(a => a.getAttribute('href')).filter(Boolean);
  const tail = [...feed.children].slice(-3).map(c => c.innerText || '').join(' ').toLowerCase();
  const end = tail.includes('reached the end');
  if (!end && new Set(hrefs).size < limit) feed.scrollBy(0, feed.scrollHeight);
  return {hrefs, end};
}"""
# One evaluate per place instead of ~20 locator round-trips.
PLACE_JS = """() => {
  const t = s => { const e = document.querySelector(s); const v = e ? (e.innerText || '').trim() : ''; return v || null; };
  const a = (s, at) => { const e = document.querySelector(s); const v = e ? (e.getAttribute(at) || '').trim() : ''; return v || null; };
  return {name: t('h1.DUwDvf') || t('h1'), category: t('button[jsaction*="category"]'),
    item_id: a('button[data-item-id^="phone:tel:"]', 'data-item-id'), website: a('a[data-item-id="authority"]', 'href'),
    address: a('button[data-item-id="address"]', 'aria-label'), rating: t('div.F7nice span[aria-hidden="true"]'),
    reviews: a('div.F7nice span[aria-label*="review"]', 'aria-label'),
    closed: (document.body.innerText || '').toLowerCase().includes('permanently closed')};
}"""

def collect_links(page, limit):
    feed = page.locator('div[role="feed"]')
    try: feed.wait_for(timeout=FEED_TIMEOUT_MS)
    except PWTimeout:
        if blocked(page): raise Blocked("CAPTCHA / block page shown. Stop, wait, and retry later (or use the official API).")
        return [page.url] if "/maps/place/" in page.url else []
    links, stale = {}, 0
    while len(links) < limit and stale < 4 and not STOP:
        if blocked(page): raise Blocked("CAPTCHA / block page shown. Stop, wait, and retry later (or use the official API).")
        data = page.evaluate(FEED_JS, limit)
        if not data: break
        before = len(links)
        for h in data["hrefs"]: links.setdefault(h, None)
        if len(links) != before: log("INFO", f"collecting links: {len(links)}/{limit}")   # also keeps the parent's idle timer fed
        if data["end"]: break
        nap(1.5, 3)
        stale = stale + 1 if len(links) == before else 0
    return list(links)[:limit]

def build_place(raw, url, page_url):
    """Pure transformation of the raw DOM extract into the place dict (kept separate so it is unit-testable)."""
    name = raw.get("name")
    if not name or name.lower() == "results": return None
    addr, rating, rev = raw.get("address"), raw.get("rating"), raw.get("reviews")
    lat, lng = parse_coords(page_url)
    return {"name": name, "gmaps_category": raw.get("category"), "phone": clean_phone(raw.get("item_id")),
        "website": raw.get("website"), "address": re.sub(r"^Address:\s*", "", addr) if addr else None, "lat": lat, "lng": lng,
        "rating": float(rating.replace(",", ".")) if rating and re.match(r"^\d([.,]\d)?$", rating) else None,
        "reviews": int(re.sub(r"\D", "", rev)) if rev and re.search(r"\d", rev) else None,
        "permanently_closed": bool(raw.get("closed")),
        "maps_url": url.split("?")[0] if "/maps/place/" in url else url}

def scrape_place(page, url):
    note_status(page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS), url)
    if "/sorry/" in page.url: raise Blocked("CAPTCHA / block page shown. Stop, wait, and retry later.")   # free check, no waiting
    try: page.locator("h1").first.wait_for(timeout=H1_TIMEOUT_MS)
    except PWTimeout:
        if blocked(page): raise Blocked("CAPTCHA / block page shown. Stop, wait, and retry later.")   # a /sorry/ page has no h1
        return None
    if blocked(page): raise Blocked("CAPTCHA / block page shown. Stop, wait, and retry later.")
    try: page.wait_for_selector('button[data-item-id="address"]', state="attached", timeout=SETTLE_MS)   # replaces a fixed 1 s sleep
    except PWTimeout: pass
    return build_place(page.evaluate(PLACE_JS), url, page.url)

def to_business(p, query):
    notes = " | ".join(filter(None, [p.get("gmaps_category"),
            f"rating {p['rating']} ({p['reviews']} reviews)" if p.get("rating") else None,
            "PERMANENTLY CLOSED" if p["permanently_closed"] else None]))
    d = {"name": p["name"], "category": query, "phone": p["phone"], "website": p["website"], "address": p["address"],
         "lat": p["lat"], "lng": p["lng"], "notes": notes, "maps_url": p["maps_url"], "rating": p.get("rating"),
         "reviews": p.get("reviews"), "permanently_closed": True if p["permanently_closed"] else None}
    return {k: v for k, v in d.items() if v not in (None, "")}

def save(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump({"businesses": items}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def load_items(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f).get("businesses", [])
    except (ValueError, OSError) as e:       # never let a damaged resume file be silently overwritten
        bad = f"{path}.corrupt-{int(time.time())}"
        try: os.replace(path, bad)
        except OSError: bad = "(could not move)"
        log("WARN", f"resume file unreadable ({type(e).__name__}); moved to {bad}, starting fresh"); return []

def search(s, q, a):
    for attempt in (1, 2):
        try:
            s.ensure(); t0 = time.time()
            note_status(s.page.goto(f"https://www.google.com/maps/search/{quote(q + ' in ' + a.location)}?hl=en",
                                    wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS), "search")
            accept_consent(s.page)
            links = collect_links(s.page, a.max)
            log("INFO", f"search '{q}' finished in {time.time() - t0:.1f}s with {len(links)} links"); return links
        except (Blocked, BrowserUnavailable): raise
        except (PWTimeout, PWError) as e:
            log("ERROR", f"search failed (attempt {attempt}): {type(e).__name__}: {str(e)[:200]}"); s.recover(e)
    return None

def fetch_place(s, url, i, n):
    """Returns (place_or_None, failed). Two attempts; each failure heals the browser/context instead of relaunching blindly."""
    for attempt in (1, 2):
        try:
            s.ensure(); return scrape_place(s.page, url), False
        except (Blocked, BrowserUnavailable): raise
        except (PWTimeout, PWError) as e:
            log("WARN", f"place {i}/{n} attempt {attempt} failed: {type(e).__name__}: {str(e)[:200]}"); s.recover(e)
    return None, True

def run(a):
    t_start = time.time()
    if sync_playwright is None: raise RuntimeError("playwright is not installed (pip install playwright && playwright install chromium)")
    os.environ.setdefault("NODE_OPTIONS", f"--max-old-space-size={NODE_HEAP_MB}")   # inherited by the driver process
    items, code = (load_items(a.out) if a.resume and os.path.exists(a.out) else []), 0
    seen = {i.get("maps_url") for i in items}
    if a.skip_urls and os.path.exists(a.skip_urls):
        with open(a.skip_urls, encoding="utf-8") as f: seen |= {l.strip() for l in f if l.strip()}
    log("INFO", f"start; {len(seen)} places already collected, will be skipped")
    done = failed = fails_in_row = 0; place_secs = 0.0; abort = False
    with sync_playwright() as pw:
        s = Session(pw, a.headful)
        try:
            s.ensure()
            for q in a.query:
                if STOP or abort: break
                print(f"\n== {q} in {a.location}", flush=True)
                links = search(s, q, a)
                if links is None: code = code or 4; continue
                print(f"found {len(links)} places", flush=True)
                for i, url in enumerate(links, 1):
                    if STOP: break
                    if url.split("?")[0] in seen: continue
                    t0 = time.time()
                    p, fail = fetch_place(s, url, i, len(links))
                    fails_in_row = fails_in_row + 1 if fail else 0; failed += fail
                    if fails_in_row >= MAX_CONSEC_FAIL:
                        log("ERROR", f"{fails_in_row} places failed in a row; stopping instead of hammering Google"); code = 4; abort = True; break
                    if p and a.skip_no_contact and not (p["phone"] or p["website"]):
                        print(f"[{i}/{len(links)}] skipped (no contact): {p['name']}", flush=True); p = None
                    if p:
                        b = to_business(p, q); items.append(b); seen.add(b.get("maps_url")); save(a.out, items); done += 1
                        print(f"[{i}/{len(links)}] {b['name']} | {b.get('phone', 'no phone')}", flush=True)
                        if a.jsonl: print("RESULT " + json.dumps(b, ensure_ascii=False), flush=True)
                    dur = time.time() - t0; place_secs += dur; s.n += 1
                    if dur > 45: log("WARN", f"slow place {i}/{len(links)}: {dur:.0f}s")
                    if (done + failed) % 10 == 0 and (done + failed):
                        rss = tree_rss_mb()
                        log("INFO", f"progress: {done} saved, {failed} failed, avg {place_secs / (done + failed):.1f}s/place" + (f", rss {rss:.0f} MB" if rss else ""))
                    if not STOP: s.maybe_recycle(); nap()
        except Blocked as e:
            print(f"STOPPED: {e}", file=sys.stderr, flush=True); code = 3
        except BrowserUnavailable as e:
            log("ERROR", f"stopping: {e}"); code = 4
        finally:
            s.close(); save(a.out, items)
            log("INFO", f"summary: {done} saved, {failed} failed, {time.time() - t_start:.0f}s elapsed, {s.launches} browser launches, "
                        f"{s.ctx_recycles} context recycles, {s.blocked_reqs} requests blocked, peak rss {s.peak_rss:.0f} MB")
    print(f"\nSaved {len(items)} businesses -> {a.out}", flush=True)
    return code

def main():
    ap = argparse.ArgumentParser(description="Google Maps -> JSON")
    ap.add_argument("-q", "--query", action="append", required=True)
    ap.add_argument("-l", "--location", required=True)
    ap.add_argument("-n", "--max", type=int, default=30)
    ap.add_argument("-o", "--out", default="maps_leads.json")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--skip-no-contact", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--jsonl", action="store_true", help="emit 'RESULT {json}' per place (used by the worker)")
    ap.add_argument("--skip-urls", help="file of maps_url values to skip (resume)")
    a = ap.parse_args()
    lock = SingleInstance(os.getenv("SCRAPER_LOCK_FILE", os.path.join(tempfile.gettempdir(), "maps_scraper.lock")))
    if not lock.acquire():
        log("ERROR", "another scraper process is already running (max 1 at a time); exiting with code 5"); sys.exit(5)
    try:
        try: code = run(a)
        except KeyboardInterrupt: log("WARN", "interrupted twice; exiting"); code = 130
        except Exception: traceback.print_exc(); sys.stderr.flush(); code = 1
    finally: lock.release()
    log("INFO", f"exit code {code}"); sys.exit(code)

if __name__ == "__main__":
    main()
