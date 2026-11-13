import os, json, urllib.parse
import pandas as pd, streamlit as st
import pipeline as P

st.set_page_config(page_title="Lead Pipeline", layout="wide")
st.title("📍 Local Business Lead Pipeline")
conn = P.db()
STATUSES = ["new", "messaged", "replied", "interested", "not_interested", "bad_number", "do_not_contact"]

with st.sidebar:
    st.header("Run pipeline")
    P.REGION = st.text_input("Default country code", P.REGION, max_chars=2).upper() or "IN"
    source = st.radio("Source", ["scrape", "osm", "google"], format_func=lambda s: {
        "scrape": "Google Maps scraper (free)", "osm": "OpenStreetMap (free, patchy)", "google": "Google Places API (free tier, then paid)"}[s])
    key = cap = None
    if source == "google":
        key = st.text_input("Google API key", os.getenv("GOOGLE_API_KEY", ""), type="password")
        cap = st.number_input("Monthly call cap (safety)", 100, 100000, 900, 100)
        used = P.google_used(conn); st.progress(min(used / cap, 1.0), f"Google calls this month: {used}/{cap}")
    if source == "scrape":
        location = st.text_input("Location (area, city)", P.get_setting(conn, "last_location") or "Indiranagar, Bengaluru")
        maxn = st.slider("Max places per category", 10, 60, 30)
        st.caption("Uses a hidden browser, about 2-5 min per category. Pins without phone/website are skipped.")
    else:
        lat = st.number_input("Latitude", value=12.9716, format="%.5f")
        lng = st.number_input("Longitude", value=77.5946, format="%.5f")
        radius = st.slider("Radius (km)", 1, 50, 5) * 1000
    if source == "osm": st.caption("OSM categories: real estate, pg, hostel, gym, clinic, salon, restaurant, school, or key=value (shop=bakery)")
    cats = st.text_area("Categories (one per line)", "real estate\npg").splitlines()
    if st.button("▶ Start pipeline", type="primary"):
        if source == "scrape": P.set_setting(conn, "last_location", location)
        for q in filter(None, [x.strip() for x in cats]):
            with st.spinner(f"Fetching {q}..."):
                try:
                    if source == "scrape": f, a_, c_ = P.run_scrape(q, location, maxn)
                    else: f, a_, c_ = P.run(q, lat, lng, radius, source, key, int(cap or 900))
                    st.success(f"{q}: fetched {f}, new {a_}, changed {c_}")
                    if source == "scrape" and P.LAST_WARNING: st.warning(f"Stopped early: {P.LAST_WARNING}")
                except Exception as e:
                    st.error(f"{q}: {e}")
    st.divider()
    days = st.number_input("Stale after (days unseen)", 7, 365, 60)
    if st.button("Mark stale"): st.info(f"{P.mark_stale(int(days))} leads marked STALE (only valid if you re-run regularly)")

df = pd.read_sql("SELECT * FROM leads", conn)
tabs = st.tabs(["Leads", "➕ Add business", "Import / Export JSON", "Changes", "Runs", "WhatsApp"])

with tabs[0]:
    if df.empty: st.info("No leads yet. Start the pipeline, add a business, or import JSON.")
    else:
        live = df[df.dup_of.isna() & ~df.status.isin(["STALE", "CLOSED_PERMANENTLY"])]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Unique leads", len(live)); c2.metric("With phone", int(live.phone.notna().sum()))
        c3.metric("WhatsApp-able", int(live.is_mobile.sum()))
        c4.metric("New today", int((df.first_seen.str[:10] == pd.Timestamp.now().strftime("%Y-%m-%d")).sum()))
        f1, f2, f3, f4 = st.columns([2, 1, 1, 2])
        cat = f1.multiselect("Category", sorted(df.category.dropna().unique()))
        minq = f2.slider("Min quality", 0, 100, 0)
        mob = f3.checkbox("Mobile only"); hide = f3.checkbox("Hide dup/stale/closed", True)
        text = f4.text_input("Search name / phone / address")
        v = (live if hide else df); v = v[v.score >= minq]
        if cat: v = v[v.category.isin(cat)]
        if mob: v = v[v.is_mobile == 1]
        if text:
            t = text.lower(); v = v[v[["name", "phone", "address"]].fillna("").apply(lambda s: s.str.lower().str.contains(t, regex=False)).any(axis=1)]
        show = v[["id", "name", "category", "phone", "email", "website", "address", "source", "score", "outreach", "notes"]].copy()
        show["delete"] = False
        ro = ["id", "name", "category", "phone", "email", "website", "address", "source", "score"]
        ed = st.data_editor(show, hide_index=True, disabled=ro, column_config={
            "outreach": st.column_config.SelectboxColumn(options=STATUSES), "id": None})
        s1, s2 = st.columns(2)
        if s1.button("💾 Save status / notes"):
            for _, r in ed.iterrows(): P.set_outreach(conn, r["id"], r["outreach"], r["notes"])
            conn.commit(); st.success("Saved")
        ok = s2.checkbox("Confirm delete of ticked rows")
        if s2.button("🗑 Delete ticked") and ok:
            ids = list(ed[ed["delete"]]["id"]); P.delete_leads(conn, ids); st.success(f"Deleted {len(ids)}"); st.rerun()

with tabs[1]:
    st.caption("Phone is validated; the same phone/name+address updates the existing entry instead of duplicating.")
    with st.form("add", clear_on_submit=True):
        a, b = st.columns(2)
        name = a.text_input("Business name *"); category = b.text_input("Category", "uncategorized")
        phone = a.text_input("Phone / WhatsApp"); email = b.text_input("Email")
        website = a.text_input("Website"); address = b.text_input("Address")
        la, lo = a.number_input("Latitude (optional)", value=0.0, format="%.5f"), b.number_input("Longitude (optional)", value=0.0, format="%.5f")
        notes = st.text_area("Notes")
        if st.form_submit_button("Add business", type="primary"):
            res = P.import_businesses(conn, [dict(name=name, category=category, phone=phone, email=email, website=website, address=address, lat=la, lng=lo, notes=notes)])
            if res["skipped"]: st.error("Name is required")
            else: st.success(f"Added: {res['added']}, updated: {res['updated']}")
            for w in res["warnings"]: st.warning(w)

with tabs[2]:
    st.subheader("Import")
    st.caption('Format: {"businesses":[{"name":"...","category":"...","phone":"...","email":"...","website":"...","address":"...","lat":0,"lng":0,"notes":"..."}]} (a plain list also works; only "name" is required)')
    st.download_button("⬇ Download sample / template", json.dumps(P.SAMPLE, indent=2), "sample_businesses.json")
    up = st.file_uploader("Upload .json", type="json"); pasted = st.text_area("...or paste JSON", height=120)
    if st.button("Import JSON", type="primary"):
        try:
            raw = up.getvalue().decode("utf-8-sig") if up else pasted
            res = P.import_businesses(conn, json.loads(raw))
            st.success(f"Added {res['added']}, updated {res['updated']}, unchanged {res['same']}, skipped {res['skipped']}")
            for w in res["warnings"]: st.warning(w)
        except (json.JSONDecodeError, ValueError, AttributeError) as e: st.error(f"Invalid JSON: {e}")
    st.subheader("Export / backup")
    e1, e2 = st.columns(2)
    e1.download_button("All unique leads (JSON)", json.dumps(P.export_json(conn), indent=2), "leads_export.json")
    e2.download_button("Manual entries only (JSON)", json.dumps(P.export_json(conn, True), indent=2), "manual_export.json")

with tabs[3]:
    st.caption("Every detected change to name / phone / website / email / address / status.")
    st.dataframe(pd.read_sql("SELECT c.at,l.name,c.field,c.old,c.new FROM changes c LEFT JOIN leads l ON l.id=c.lead_id ORDER BY c.id DESC", conn))
with tabs[4]:
    st.dataframe(pd.read_sql("SELECT * FROM runs ORDER BY id DESC", conn))
with tabs[5]:
    tpl = st.text_area("Message template ({name}, {category})", P.get_setting(conn, "template"), height=110)
    lim = st.number_input("Daily limit (people-sized batches protect your number)", 1, 100, int(P.get_setting(conn, "daily_limit")))
    if st.button("Save message settings"):
        P.set_setting(conn, "template", tpl); P.set_setting(conn, "daily_limit", lim); st.success("Saved (the Telegram bot uses the same settings)")
    used = P.sent_today(conn); st.metric("Sent today", f"{used}/{lim}")
    st.caption("You press send yourself in WhatsApp. Photo/video is set from the Telegram bot (📝 Message & media), or attach it by hand in WhatsApp.")
    x = P.sendable(conn, max(0, int(lim) - used))
    if x:
        t = pd.DataFrame([dict(name=r["name"], category=r["category"], phone=r["phone"], score=r["score"],
                               whatsapp=P.wa_link(r["phone"], P.render(tpl, r))) for r in x])
        st.dataframe(t, column_config={"whatsapp": st.column_config.LinkColumn("Chat", display_text="Open WhatsApp")})
        st.caption("After sending, set the lead's status to 'messaged' in the Leads tab (or use the bot, which does it with one tap).")
    else: st.info("Nothing to send right now (limit reached or no new mobile leads).")