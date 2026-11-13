"""Check the Supabase connection used by pipeline.py.  Run:  python test_connection.py"""
import os, sys, re

def step(ok, msg, hint=""):
    print(("[ OK ] " if ok else "[FAIL] ") + msg)
    if not ok:
        if hint: print("       -> " + hint)
        sys.exit(1)

try:
    import pipeline as p          # also loads .env
except ModuleNotFoundError as e:
    step(False, f"Missing package: {e.name}", "pip install -r requirements.txt  (needs psycopg2-binary)")

url = p.DATABASE_URL or ""
step(bool(url), "DATABASE_URL found in .env / environment", "Add DATABASE_URL=postgresql://... to your .env file")
step("[YOUR-PASSWORD]" not in url, "Password placeholder replaced", "Replace [YOUR-PASSWORD] in DATABASE_URL with your real database password")
m = re.match(r"postgres(?:ql)?://[^@]+@([^:/]+)(?::(\d+))?/(\w+)", url)
step(bool(m), "DATABASE_URL format looks valid", "Expected postgresql://user:password@host:5432/postgres (URL-encode special characters in the password)")
print(f"       host={m.group(1)} port={m.group(2) or '5432'} db={m.group(3)}")

try:
    c = p.db()
except Exception as e:
    msg = str(e).strip().splitlines()[0]
    hint = "Check host, port and password."
    if "password authentication" in msg: hint = "Wrong password. Reset it in Supabase > Project Settings > Database."
    elif "unreachable" in msg or "could not translate" in msg or "timeout" in msg.lower():
        hint = "Direct connection is IPv6-only. Use the Session pooler string from Supabase > Connect."
    step(False, f"Connected to database: {msg}", hint)
step(True, "Connected and schema ready")

v = c.execute("SELECT version()").fetchone()[0]
step(True, "Server: " + v.split(",")[0])

have = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
need = {"leads", "changes", "runs", "kv", "run_events"}
step(need <= have, "Tables present: " + ", ".join(sorted(need)), f"Missing: {sorted(need - have)}")

rls = {r[0]: r[1] for r in c.execute("SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('leads','changes','runs','kv','run_events')")}
print("[ OK ] Row-level security on all tables" if all(rls.values()) else f"[WARN] RLS off for: {[t for t, on in rls.items() if not on]}")

# write / read / update / delete round trip with a throwaway lead
tid = "test:connection-check"
ts = p.now()
try:
    c.execute("DELETE FROM leads WHERE id=?", (tid,)); c.commit()
    r1 = p.save_row(c, dict(id=tid, source="manual", name="Connection Test", category="test", phone="+919845012345"), ts)
    c.commit()
    step(r1 == "added", "Insert works (save_row -> added)", f"got {r1!r}")
    row = c.execute("SELECT name, phone, is_mobile, score FROM leads WHERE id=?", (tid,)).fetchone()
    step(row is not None and row["name"] == "Connection Test", f"Read works (phone={row['phone']}, score={row['score']})")
    r2 = p.save_row(c, dict(id=tid, source="manual", name="Connection Test 2", category="test", phone="+919845012345"), p.now())
    c.commit()
    step(r2 == "updated", "Update + change history works (save_row -> updated)", f"got {r2!r}")
    p.set_setting(c, "_conn_test", "ok")
    step(p.get_setting(c, "_conn_test") == "ok", "Settings (kv upsert) works")
finally:
    c.rollback()
    c.execute("DELETE FROM changes WHERE lead_id=?", (tid,))
    c.execute("DELETE FROM leads WHERE id=?", (tid,))
    c.execute("DELETE FROM kv WHERE k='_conn_test'")
    c.commit()
n = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
step(True, f"Test data cleaned up. Your database currently has {n} lead(s)")
c.close()
print("\nAll good: Supabase is connected and pipeline.py works against it.")
