import os, subprocess, sys
import pipeline as lp
ok = True
def step(name, fn):
    global ok
    try: print(f"PASS  {name}: {fn() or ''}")
    except Exception as e: ok = False; print(f"FAIL  {name}: {type(e).__name__}: {e}")
step("env DATABASE_URL", lambda: "set" if os.getenv("DATABASE_URL") else (_ for _ in ()).throw(RuntimeError("missing")))
step("supabase", lambda: lp.db().execute("SELECT version()").fetchone()[0][:40])
step("overpass", lambda: f"{len(lp.fetch_osm('real estate', 28.4089, 77.3178, 5000))} named places via {lp.LAST_OSM.get('mirror')}")
step("google", lambda: f"{len(lp.fetch_google(os.environ['GOOGLE_API_KEY'], 'real estate', 28.4089, 77.3178, 3000, 1))} places" if os.getenv("GOOGLE_API_KEY") else "SKIPPED (no GOOGLE_API_KEY)")
def pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"]); v = b.version; b.close(); return "chromium " + v
step("playwright", pw)
env = {**os.environ, "RUN_LIVE": "1"}
sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-v", "tests"], env=env) or (0 if ok else 1))