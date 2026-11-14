"""Google Maps scraper (Playwright). Personal-scale, slow on purpose.
Stops (never evades) on CAPTCHA -> exit code 3.
Run: python maps_scraper.py -q "real estate" -l "Indiranagar, Bengaluru" -n 40 -o leads.json
Protocol lines for the parent: 'found N places', '[i/n] name | phone', 'RESULT {json}', 'STOPPED: ...'."""
import argparse, json, os, random, re, signal, sys, time, traceback, datetime as dt
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError

STOP = False
def _sig(*_):
    global STOP; STOP = True; log("WARN", "termination signal received; finishing current step and saving")
signal.signal(signal.SIGTERM, _sig); signal.signal(signal.SIGINT, _sig)

def log(level, msg): print(f"{dt.datetime.now():%H:%M:%S} {level} {msg}", flush=True)

COORD = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-zygote", "--disable-extensions",
        "--mute-audio", "--js-flags=--max-old-space-size=384"]
RECYCLE_EVERY = 12   # fresh browser every N places: caps Chromium memory growth

def parse_coords(url):
    m = COORD.search(url or ""); return (float(m[1]), float(m[2])) if m else (None, None)
def clean_phone(item_id):
    m = re.search(r"phone:tel:([+\d]+)", item_id or ""); return m[1] if m else None
def nap(a=1.5, b=3.5): time.sleep(random.uniform(a, b))

def blocked(page):
    try: return "/sorry/" in page.url or page.locator("iframe[src*='recaptcha']").count() > 0
    except PWError: return False

def accept_consent(page):
    try: page.get_by_role("button", name=re.compile("Reject all|Accept all", re.I)).first.click(timeout=3000)
    except Exception: pass

class Session:
    def __init__(s, pw, headful): s.pw, s.headful, s.browser, s.ctx, s.page, s.n = pw, headful, None, None, None, 0
    def open(s):
        s.close()
        s.browser = s.pw.chromium.launch(headless=not s.headful, args=ARGS)
        s.browser.on("disconnected", lambda *_: log("ERROR", "browser disconnected/crashed"))
        s.ctx = s.browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        s.ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        s.page = s.ctx.new_page(); s.page.set_default_timeout(20000); s.n = 0
        s.page.on("pageerror", lambda e: log("WARN", f"pageerror: {str(e)[:200]}"))
        s.page.on("crash", lambda *_: log("ERROR", "page crashed (likely out of memory)"))
        s.page.on("requestfailed", lambda r: log("WARN", f"requestfailed {r.url[:110]} {r.failure}") if r.resource_type == "document" else None)
        s.page.on("response", lambda r: log("WARN", f"HTTP {r.status} {r.url[:110]}") if r.request.resource_type == "document" and r.status >= 400 else None)
    def close(s):
        for o in (s.ctx, s.browser):
            try:
                if o: o.close()
            except Exception: pass
        s.ctx = s.browser = s.page = None

def collect_links(page, limit):
    feed = page.locator('div[role="feed"]')
    try: feed.wait_for(timeout=15000)
    except PWTimeout:
        return [page.url] if "/maps/place/" in page.url else []
    links, stale = {}, 0
    while len(links) < limit and stale < 4 and not STOP:
        before = len(links)
        for a in page.locator('div[role="feed"] a[href*="/maps/place/"]').all():
            h = a.get_attribute("href")
            if h: links.setdefault(h, None)
        if blocked(page): raise RuntimeError("CAPTCHA / block page shown. Stop, wait, and retry later (or use the official API).")
        if "reached the end" in feed.inner_text()[-300:].lower(): break
        feed.evaluate("e => e.scrollBy(0, e.scrollHeight)"); nap(1.5, 3)
        stale = stale + 1 if len(links) == before else 0
    return list(links)[:limit]

def first_text(page, sel, attr=None):
    loc = page.locator(sel).first
    try:
        if loc.count() == 0: return None
        v = loc.get_attribute(attr) if attr else loc.inner_text(timeout=1500)
        return v.strip() if v else None
    except PWError: return None

def scrape_place(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try: page.locator("h1").first.wait_for(timeout=10000)
    except PWTimeout: return None
    if blocked(page): raise RuntimeError("CAPTCHA / block page shown. Stop, wait, and retry later.")
    page.wait_for_timeout(1000)
    name = first_text(page, "h1.DUwDvf") or first_text(page, "h1")
    if not name or name.lower() == "results": return None
    addr = first_text(page, 'button[data-item-id="address"]', "aria-label")
    lat, lng = parse_coords(page.url)
    rating = first_text(page, 'div.F7nice span[aria-hidden="true"]')
    rev = first_text(page, 'div.F7nice span[aria-label*="review"]', "aria-label")
    return {"name": name, "gmaps_category": first_text(page, 'button[jsaction*="category"]'),
        "phone": clean_phone(first_text(page, 'button[data-item-id^="phone:tel:"]', "data-item-id")),
        "website": first_text(page, 'a[data-item-id="authority"]', "href"),
        "address": re.sub(r"^Address:\s*", "", addr) if addr else None, "lat": lat, "lng": lng,
        "rating": float(rating.replace(",", ".")) if rating and re.match(r"^\d([.,]\d)?$", rating) else None,
        "reviews": int(re.sub(r"\D", "", rev)) if rev and re.search(r"\d", rev) else None,
        "permanently_closed": page.get_by_text("Permanently closed").count() > 0,
        "maps_url": url.split("?")[0] if "/maps/place/" in url else url}

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

def run(a):
    items, code = [], 0
    if a.resume and os.path.exists(a.out):
        items = json.load(open(a.out, encoding="utf-8")).get("businesses", [])
    seen = {i.get("maps_url") for i in items}
    if a.skip_urls and os.path.exists(a.skip_urls):
        seen |= {l.strip() for l in open(a.skip_urls, encoding="utf-8") if l.strip()}
    log("INFO", f"start; {len(seen)} places already collected, will be skipped")
    with sync_playwright() as pw:
        s = Session(pw, a.headful)
        try:
            s.open()
            for q in a.query:
                if STOP: break
                print(f"\n== {q} in {a.location}", flush=True)
                links = None
                for attempt in (1, 2):
                    try:
                        s.page.goto(f"https://www.google.com/maps/search/{quote(q + ' in ' + a.location)}?hl=en",
                                    wait_until="domcontentloaded", timeout=45000)
                        accept_consent(s.page); links = collect_links(s.page, a.max); break
                    except RuntimeError: raise
                    except (PWTimeout, PWError) as e:
                        log("ERROR", f"search failed (attempt {attempt}): {type(e).__name__}: {str(e)[:200]}"); s.open()
                if links is None: code = code or 4; continue
                print(f"found {len(links)} places", flush=True)
                for i, url in enumerate(links, 1):
                    if STOP: break
                    if url.split("?")[0] in seen: continue
                    p = None
                    for attempt in (1, 2):
                        try: p = scrape_place(s.page, url); break
                        except RuntimeError: raise
                        except (PWTimeout, PWError) as e:
                            log("WARN", f"place {i}/{len(links)} attempt {attempt} failed: {type(e).__name__}: {str(e)[:200]}"); s.open()
                    if p and a.skip_no_contact and not (p["phone"] or p["website"]):
                        print(f"[{i}/{len(links)}] skipped (no contact): {p['name']}", flush=True); p = None
                    if p:
                        b = to_business(p, q); items.append(b); seen.add(b.get("maps_url")); save(a.out, items)
                        print(f"[{i}/{len(links)}] {b['name']} | {b.get('phone', 'no phone')}", flush=True)
                        if a.jsonl: print("RESULT " + json.dumps(b, ensure_ascii=False), flush=True)
                    s.n += 1
                    if s.n >= RECYCLE_EVERY: log("INFO", "recycling browser to bound memory"); s.open()
                    else:
                        try: s.page.goto("about:blank")
                        except PWError: s.open()
                    nap()
        except RuntimeError as e:
            print(f"STOPPED: {e}", file=sys.stderr, flush=True); code = 3
        finally:
            s.close(); save(a.out, items)
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
    try: code = run(a)
    except Exception:
        traceback.print_exc(); sys.stderr.flush(); code = 1
    log("INFO", f"exit code {code}"); sys.exit(code)

if __name__ == "__main__":
    main()