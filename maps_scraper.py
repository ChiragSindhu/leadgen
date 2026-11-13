"""Google Maps scraper -> JSON that the dashboard's "Import JSON" tab accepts.
Personal-scale use. Slow on purpose. Stops (does not evade) if Google shows a CAPTCHA.

Setup:  pip install playwright && playwright install chromium
Run:    python maps_scraper.py -q "real estate" -q "pg" -l "Indiranagar, Bengaluru" -n 40 -o leads.json
"""
import argparse, json, os, random, re, sys, time
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

COORD = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")

def parse_coords(url):
    m = COORD.search(url or "")
    return (float(m[1]), float(m[2])) if m else (None, None)

def clean_phone(item_id):
    m = re.search(r"phone:tel:([+\d]+)", item_id or "")
    return m[1] if m else None

def nap(a=2.0, b=4.5): time.sleep(random.uniform(a, b))

def blocked(page):
    return "/sorry/" in page.url or page.locator("iframe[src*='recaptcha']").count() > 0

def accept_consent(page):
    try: page.get_by_role("button", name=re.compile("Reject all|Accept all", re.I)).first.click(timeout=3000)
    except Exception: pass

def collect_links(page, limit):
    feed = page.locator('div[role="feed"]')
    try: feed.wait_for(timeout=15000)
    except PWTimeout:   # Maps jumped straight to a single place, or no results
        return [page.url] if "/maps/place/" in page.url else []
    links, stale = {}, 0
    while len(links) < limit and stale < 4:
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
    except Exception: return None

def scrape_place(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try: page.locator("h1").first.wait_for(timeout=10000)
    except PWTimeout: return None
    if blocked(page): raise RuntimeError("CAPTCHA / block page shown. Stop, wait, and retry later.")
    page.wait_for_timeout(1200)
    name = first_text(page, "h1.DUwDvf") or first_text(page, "h1")
    if not name or name.lower() == "results": return None
    addr = first_text(page, 'button[data-item-id="address"]', "aria-label")
    lat, lng = parse_coords(page.url)
    rating = first_text(page, 'div.F7nice span[aria-hidden="true"]')
    rev = first_text(page, 'div.F7nice span[aria-label*="review"]', "aria-label")
    return {
        "name": name,
        "gmaps_category": first_text(page, 'button[jsaction*="category"]'),
        "phone": clean_phone(first_text(page, 'button[data-item-id^="phone:tel:"]', "data-item-id")),
        "website": first_text(page, 'a[data-item-id="authority"]', "href"),
        "address": re.sub(r"^Address:\s*", "", addr) if addr else None,
        "lat": lat, "lng": lng,
        "rating": float(rating.replace(",", ".")) if rating and re.match(r"^\d([.,]\d)?$", rating) else None,
        "reviews": int(re.sub(r"\D", "", rev)) if rev and re.search(r"\d", rev) else None,
        "permanently_closed": page.get_by_text("Permanently closed").count() > 0,
        "maps_url": url.split("?")[0] if "/maps/place/" in url else url,
    }

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
    os.replace(tmp, path)   # atomic: never leaves a half-written file

def main():
    ap = argparse.ArgumentParser(description="Google Maps -> JSON")
    ap.add_argument("-q", "--query", action="append", required=True, help="category; repeat for several")
    ap.add_argument("-l", "--location", required=True, help='e.g. "Indiranagar, Bengaluru"')
    ap.add_argument("-n", "--max", type=int, default=30, help="max places per query (keep modest)")
    ap.add_argument("-o", "--out", default="maps_leads.json")
    ap.add_argument("--headful", action="store_true", help="show the browser (helps debugging)")
    ap.add_argument("--skip-no-contact", action="store_true", help="drop pins with no phone and no website (junk like plain addresses)")
    ap.add_argument("--resume", action="store_true", help="keep existing output and skip places already in it")
    a = ap.parse_args()

    items = []
    if a.resume and os.path.exists(a.out):
        items = json.load(open(a.out, encoding="utf-8")).get("businesses", [])
    seen = {i.get("maps_url") for i in items}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not a.headful)
        page = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900}).new_page()
        try:
            for q in a.query:
                print(f"\n== {q} in {a.location}")
                page.goto(f"https://www.google.com/maps/search/{quote(q + ' in ' + a.location)}?hl=en", timeout=45000)
                accept_consent(page)
                links = collect_links(page, a.max)
                print(f"found {len(links)} places")
                for i, url in enumerate(links, 1):
                    if url.split("?")[0] in seen: continue
                    try: p = scrape_place(page, url)
                    except PWTimeout: p = None
                    if p and a.skip_no_contact and not (p['phone'] or p['website']):
                        print(f"[{i}/{len(links)}] skipped (no contact): {p['name']}"); p = None
                    if p:
                        b = to_business(p, q); items.append(b); seen.add(b.get("maps_url"))
                        save(a.out, items)   # checkpoint after every place
                        print(f"[{i}/{len(links)}] {b['name']} | {b.get('phone', 'no phone')}")
                    nap()
                    page.goto("about:blank")
        except RuntimeError as e:
            print(f"\nSTOPPED: {e}", file=sys.stderr)
        finally:
            browser.close(); save(a.out, items)
    print(f"\nSaved {len(items)} businesses -> {a.out}\nImport it in the dashboard: Import / Export JSON.")

if __name__ == "__main__":
    main()
