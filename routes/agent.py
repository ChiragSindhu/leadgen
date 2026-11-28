"""Boss v2.3: Groq tool-calling agent. Memory, insights, lead search, queue control, settings.
Token savers: per-message tool routing, slim tool outputs, no-LLM fast paths, trimmed history, cache-friendly prompt order.
Proactive: deterministic "Boss can do" suggestion chips (zero tokens) + one-line offers from the model.
Live status: /api/agent/thinking shows what Boss is doing while a reply is being built.
Debug: BOSS_DEBUG=1 in dev. Leave unset/0 in production (no content logged, no trace, /api/agent/debug is 404)."""
import os, re, ast, json, uuid, time, logging, collections, threading, datetime as dt, requests
from flask import Blueprint, request, jsonify
import pipeline as P
import wa
from core import JOB, claim, rows, clamp
from .settings import get_templates, clean_templates
from .leads import lead_filter
from .whatsapp import wa_cfg

bp = Blueprint("agent", __name__)
GROQ = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
AG = dict(running=False, stop=False, city="", category="", target=0, added=0, areas=[], i=-1, done=[], msg="idle", v=0)
REFRESH = set()   # what the UI must reload after a turn

# ---------- live "what is Boss doing" status, polled by the UI ----------
TH = dict(on=False, step="")
STEPS = dict(list_templates="reading your templates", save_template="rewriting the template", find_lead="looking up the lead",
             propose_send="building the send card", search_leads="searching your leads", get_overview="checking your numbers",
             next_actions="working out what's next", run_insights="checking area coverage", search_status="checking the search",
             plan_campaign="planning the campaign", start_multi_find="setting up the search", queue_front="queueing the lead",
             update_settings="preparing the settings change", ask_user="working out what to ask", remember="noting that down",
             stop_search="preparing the stop", activate_template="preparing the switch", delete_template="preparing the delete")


def think(step): TH.update(on=True, step=step)


# ---------- debug (off unless BOSS_DEBUG=1) ----------
DEBUG = os.getenv("BOSS_DEBUG", "0") == "1"
log = logging.getLogger("boss")
log.setLevel(logging.DEBUG if DEBUG else logging.WARNING)
if not log.handlers:
    _h = logging.StreamHandler(); _h.setFormatter(logging.Formatter("%(asctime)s [boss] %(message)s")); log.addHandler(_h)
TRACE = collections.deque(maxlen=300); SEQ = [0]


def dbg(event, **kw):
    """No-op unless BOSS_DEBUG=1, so nothing sensitive is stored or logged in production."""
    if not DEBUG: return
    SEQ[0] += 1
    TRACE.append(dict(seq=SEQ[0],t=dt.datetime.now().strftime("%H:%M:%S"),kind=event,**kw))
    log.debug("%s %s", event, json.dumps(kw, default=str)[:800])

# Static part first (cache-friendly prefix). Dynamic context goes in a second system message.
SYSTEM = """You are Boss, chief of staff for Vansh's WhatsApp lead-gen app (India, small-business outreach). Call him "Vansh Boss". You read the app and propose changes; every change is an approval card he taps. You cannot change or send anything yourself.

Voice: gen-z hype bro, lowercase ok, slang (bro, fr, lowkey), under 50 words, no emoji unless he uses one, exact numbers never percentages, no text menus. Never print [ctx] notes.

Rules:
- Act only through function calling. Never write tool names, "lead_in:" or "warning:" in text. Never say a card is queued unless you called a tool this turn. If he answers about an earlier card ("yes but...", "make it new"), call the tool again with his change; [ctx] notes show earlier cards.
- Resolve with tools/LIVE first; never ask what they can answer. ask_user only for essentials: one card, 1-2 questions, buttons only for short closed sets from real data, text=true for open answers (city, number, name), lead_in = one-line recap. Never invent options, never confirm what the approval card confirms, never re-ask.
- Changing tools only create approval cards: say what you queued, never that it is done. Do exactly what he asked.
- Failed lookups or errors: one line plus one concrete suggestion, no menus.

Intents:
- A person/business name or phone is a lead lookup, never a category. One lead: propose_send(query). Batch: propose_send(n). Sends use the active template. Already-messaged leads still go through propose_send; the card warns.
- WhatsApp off: propose_send already shows the lead and a queue card. You cannot enable WhatsApp; never ask him to with buttons.
- "first in queue": queue_front(query). Only ready leads qualify, else tell him to tap the lead and send by hand.
- "what next / how am I doing": next_actions, then his top 2 moves with exact numbers.
- Find leads: start_multi_find (one type, one city; ask only for the missing type/city/count). Several types/cities or "everything": plan_campaign (cities list; pick 3-6 types if none given). Real estate builders / 3D clients: category "real estate builders".
- Lists: search_leads (ready=true only if he wants to message). Progress/coverage: search_status, run_insights, get_overview.
- Templates: never ask him to paste. list_templates, rewrite the ACTIVE one keeping language (Hinglish), tone, emoji, links and last line "Reply STOP to opt out.", change only what he asked, then save_template as NEW (no id, name "<old> v2", activate=false). Edit in place or activate only if he says replace/use. Variables {name} {type} {rating} {reviews} {address} {website} {date}; include {name}; under 600 chars; brand-new templates: no emoji, no [brackets].
- Settings: update_settings; refuse gap under 20s or daily limit over 60 unless he insists twice. Durable preference: remember.
- If a search is running mention it in one line; search_status when asked.

Offers: when a clear next step exists that your tools can really do, end with ONE short offer ("want me to ...?"). Never offer what you cannot do, and make no offer while a card is waiting."""

DYN = "Today {today}. LIVE: {live}\nMEMORY:\n{mem}"


class ToolFail(RuntimeError): pass


def _wait(r):
    """Seconds to wait on a 429: Groq says 'try again in 2.17s' in the message."""
    m = re.search(r"try again in ([\d.]+)\s*(ms|s)", r.text or "")
    w = (float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)) if m else float(r.headers.get("retry-after") or 2)
    return min(w + 0.5, 15)


def groq(messages, tools=None, json_mode=False, effort="low", cap=1500):
    key = os.getenv("GROQ_API_KEY")
    if not key: raise RuntimeError("GROQ_API_KEY is missing in .env")
    body = dict(model=MODEL, messages=messages, temperature=0.2)
    if "gpt-oss" in MODEL: body.update(reasoning_effort=effort, max_completion_tokens=cap)   # Groq accepts low|medium|high only
    if tools: body.update(tools=tools, tool_choice="auto")
    if json_mode: body["response_format"] = {"type": "json_object"}
    for attempt in range(4):
        t0 = time.time()
        r = requests.post(GROQ, headers={"Authorization": "Bearer " + key}, json=body, timeout=60)
        ms = int((time.time() - t0) * 1000)
        if r.status_code == 429 and attempt < 3:
            think("hit the rate limit, retrying"); wait = _wait(r); dbg("groq_429", model=MODEL, wait=wait); time.sleep(wait); continue
        break
    if r.status_code >= 400:
        err = {}
        try: err = r.json()["error"]; msg = err["message"]
        except Exception: msg = f"Groq error {r.status_code}"
        log.warning("groq %s %s code=%s", MODEL, r.status_code, err.get("code"))   # always logged, no content
        dbg("groq_error", model=MODEL, status=r.status_code, body=r.text[:500])
        if err.get("code") == "tool_use_failed": raise ToolFail(msg)
        raise RuntimeError(msg)
    j = r.json(); m = j["choices"][0]["message"]
    dbg("groq", model=MODEL, ms=ms, usage=j.get("usage"), tools=[c["function"]["name"] for c in (m.get("tool_calls") or [])], text=(m.get("content") or "")[:300])
    return m


def kvj(k, d):
    c = P.db()
    try: return json.loads(P.get_setting(c, k) or "null") or d
    except Exception: return d
    finally: c.close()


def kvs(k, v):
    c = P.db()
    try: P.set_setting(c, k, json.dumps(v))
    finally: c.close()


def pub(): return {k: v for k, v in AG.items() if k != "stop"}
def bump(**kw): AG.update(kw); AG["v"] += 1


# ---------- memory ----------
def t_remember(a):
    m = kvj("agent_mem", []); f = str(a.get("fact", "")).strip()[:300]
    if not f: return dict(error="empty")
    m = (m + [f])[-40:]; kvs("agent_mem", m); return dict(ok=True, memories=len(m))


def t_forget(a):
    m = kvj("agent_mem", []); k = str(a.get("contains", "")).lower()
    n = [x for x in m if k not in x.lower()]; kvs("agent_mem", n); return dict(removed=len(m) - len(n))


# ---------- read tools ----------
def t_overview(_):
    c = P.db()
    try:
        q = lambda s, *a: c.execute(s, a or None).fetchone()[0]
        day = (dt.datetime.now() - dt.timedelta(hours=24)).isoformat(timespec="seconds")
        return dict(total=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL"), ready_to_message=P.sendable_count(c),
                    with_phone=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL AND phone IS NOT NULL"),
                    contacted=q("SELECT COUNT(*) FROM leads WHERE outreach!='new'"),
                    warm=q("SELECT COUNT(*) FROM leads WHERE outreach IN ('replied','interested')"),
                    new_last_24h=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL AND first_seen>?", day),
                    sent_today=P.sent_today(c), daily_limit=int(P.get_setting(c, "daily_limit")),
                    whatsapp=wa.state["status"], search_running=bool(JOB["running"]), plan=pub())
    finally: c.close()


def covered():
    out = {}
    for r in rows("SELECT query, location, COALESCE(SUM(added),0) AS new, COUNT(*) AS runs, MAX(at) AS last FROM runs "
                  "WHERE source!='whatsapp' AND location IS NOT NULL AND location!='' GROUP BY query, location ORDER BY MAX(at) DESC LIMIT 150"):
        out.setdefault(r["query"].lower(), []).append(dict(area=r["location"], new=int(r["new"]), runs=r["runs"], last=r["last"][:10]))
    return out


def t_insights(a):
    cov = covered(); cat = (a.get("category") or "").lower()
    recent = rows("SELECT query, location, added, status, at FROM runs WHERE source!='whatsapp' ORDER BY id DESC LIMIT 8")
    return dict(covered_by_category={k: v[:25] for k, v in cov.items() if not cat or cat in k},
                saturated=[f"{k} / {x['area']}" for k, v in cov.items() for x in v if x["runs"] >= 2 and x["new"] < 3],
                last_runs=[dict(r) for r in recent], overview=t_overview(None))


def t_next(_):
    """Facts + ranked hints for 'what should I do next / how am I doing'."""
    o = t_overview(None); room = max(0, o["daily_limit"] - o["sent_today"]); tips = []
    if o["whatsapp"] != "ready": tips.append(f"WhatsApp is {o['whatsapp']}: connect it in Settings, nothing sends until then")
    if o["ready_to_message"] and room: tips.append(f"{min(o['ready_to_message'], room)} ready leads can go out today ({room} sends left)")
    if o["ready_to_message"] < 50: tips.append("send queue is thin: run a search for more leads")
    if o["contacted"] >= 100 and o["warm"] == 0: tips.append(f"{o['contacted']} contacted and 0 replies: the template is the weak spot, test a new version")
    sat = t_insights({})["saturated"]
    if sat: tips.append("saturated, skip these: " + ", ".join(sat[:4]))
    if o["search_running"]: tips.append("a search is running, check its progress")
    return dict(overview=o, tips=tips)


def t_search(a):
    src = dict(q=a.get("q"), category=a.get("category"), min_score=a.get("min_score"), ready=1 if a.get("ready") else None,
               status=a.get("status"), mobile=1 if a.get("mobile") else None)
    w, p = lead_filter({k: v for k, v in src.items() if v})
    lim = clamp(int(a.get("limit") or 8), 1, 15)
    c = P.db()
    try:
        total = c.execute(f"SELECT COUNT(*) FROM leads WHERE {w}", p).fetchone()[0]
        items = [dict(x) for x in c.execute(f"SELECT id,name,category,phone,score,outreach,address FROM leads WHERE {w} ORDER BY score DESC LIMIT ?", p + [lim])]
    finally: c.close()
    return dict(total_matching=total, top=items)


def osm_areas(city, n):
    """Fallback for places the LLM does not know: OpenStreetMap suburbs/neighbourhoods inside the place's bounding box."""
    try:
        g = requests.get("https://nominatim.openstreetmap.org/search", params=dict(q=city, format="json", limit=1), headers={"User-Agent": "leadpipe/1.3"}, timeout=20).json()
        if not g: return []
        s_, n_, w_, e_ = g[0]["boundingbox"]
        q = f'[out:json][timeout:25];(node["place"~"suburb|neighbourhood|quarter"]({s_},{w_},{n_},{e_}););out tags 120;'
        els = requests.post("https://overpass-api.de/api/interpreter", data=dict(data=q), timeout=40).json().get("elements", [])
        return list(dict.fromkeys(x["tags"]["name"] for x in els if x.get("tags", {}).get("name")))[:n]
    except Exception: return []


def t_areas(a):
    city, n = a["city"], clamp(int(a.get("count") or 14), 3, 30)
    m = groq([{"role": "user", "content": f'List {n} distinct sectors, localities or neighbourhoods inside {city}, India, with many local shops and offices, densest first. '
              'Short names only. If you do not know this place, return an empty list. Reply with JSON only: {"areas":["..."]}'}], effort="low")
    try: out = json.loads(re.search(r"\{.*\}", m.get("content") or "", re.S).group(0)).get("areas", [])
    except Exception: out = []
    return dict(areas=list(dict.fromkeys(str(x).strip() for x in out if str(x).strip())))


def find_areas(city, n):
    """LLM first, then OpenStreetMap, then areas used in earlier runs, finally the city itself."""
    try: out = t_areas(dict(city=city, count=n))["areas"]
    except Exception: out = []
    if len(out) < 5: out = list(dict.fromkeys(out + osm_areas(city, n)))
    if len(out) < 3:
        out += [r["location"].split(",")[0] for r in rows("SELECT DISTINCT location FROM runs WHERE LOWER(location) LIKE ? AND source!='whatsapp' LIMIT 20", f"%{city.lower()}%")]
    return list(dict.fromkeys(out)) or [city]


PEND = {}   # approved-by-tap plans


def start_steps(cities, steps, per=25):
    """cities: list of city names. Every step (business type) runs once per city, one after another."""
    if isinstance(cities, str): cities = [cities]
    busy = claim("find")
    if busy: return dict(error=busy)
    plan = [dict(st, city=c) for c in cities for st in steps]
    label = " & ".join(cities); total = sum(x["target"] for x in plan)
    cats = list(dict.fromkeys(x["category"] for x in steps))
    JOB.update(running=True, msg=f"Boss: {label}", total=total, done=0, collected=0, skipped=0, phase="Planning", run_id=None)
    bump(running=True, stop=False, city=label, category=" + ".join(cats), target=total, added=0, areas=[], i=0, done=[], msg="Started")
    threading.Thread(target=steps_work, args=(plan, per), daemon=True).start()
    REFRESH.update(["runs", "stats"]); return dict(started=True, city=label, steps=plan)


def steps_work(plan, per):
    multi = len(plan) > 1
    try:
        for st in plan:
            if AG["stop"]: break
            cat, city, target, got = st["category"], st["city"], st["target"], 0
            sat = {x["area"].split(",")[0].strip().lower() for x in covered().get(cat.lower(), []) if x["runs"] >= 2 and x["new"] < 3}
            bump(msg=f"Finding areas for {cat} in {city}")
            for ar in [a for a in (st.get("areas") or find_areas(city, clamp(target // per + 8, 8, 30))) if a.lower() not in sat]:
                if AG["stop"] or got >= target: break
                lab = f"{ar} · {cat} · {city}" if multi else ar
                AG["areas"].append(lab); bump(i=len(AG["areas"]) - 1, msg=f"Searching {lab}")
                JOB.update(phase=f"{lab}", msg=f"Boss: {cat} in {ar}")
                try:
                    _, added, _ = P.run_scrape(cat, f"{ar}, {city}", min(per, target - got), on_progress=lambda p: JOB.update(p))
                    got += added; AG["added"] += added; AG["done"].append(dict(area=lab, new=added, ok=True))
                except Exception as e: AG["done"].append(dict(area=lab, new=0, ok=False, err=str(e)[:120]))
                bump(); JOB.update(done=min(AG["added"], AG["target"]), collected=AG["added"], total=AG["target"])
    finally:
        bump(running=False, i=-1, msg=f"Finished: {AG['added']} new of {AG['target']} wanted across {len(AG['done'])} areas")
        JOB.update(running=False, phase="Finished", msg=AG["msg"])


def t_find(a):
    cat, city = (a.get("category") or "").strip(), (a.get("city") or "").strip()
    if not cat or not city: return dict(error="category and city are required")
    return start_steps([city], [dict(category=cat, target=clamp(int(a.get("target") or 50), 1, 2000), areas=[x for x in (a.get("areas") or []) if str(x).strip()])], clamp(int(a.get("per_area") or 25), 5, 60))


def t_campaign(a):
    cities = [str(c).strip() for c in (a.get("cities") or []) if str(c).strip()]
    one = (a.get("city") or "").strip()
    if one and one not in cities: cities.insert(0, one)
    cities = cities[:4]
    steps = [dict(category=str(x.get("category", "")).strip(), target=clamp(int(x.get("target") or 30), 1, 500)) for x in (a.get("steps") or [])[:8] if str(x.get("category", "")).strip()]
    if not cities or not steps: return dict(error="cities and steps are required")
    uid = uuid.uuid4().hex[:8]; PEND[uid] = dict(cities=cities, steps=steps, per=clamp(int(a.get("per_area") or 25), 5, 60))
    return dict(ok=True, id=uid, cities=cities, steps=steps)


def t_find_lead(a):
    """Look up ONE person/business by name or phone, any status (not limited to ready leads)."""
    q = str(a.get("query", "")).strip(); toks = [t for t in re.split(r"\s+", q) if t][:5]; digits = re.sub(r"\D", "", q)
    if not toks: return dict(error="query required")
    w = "dup_of IS NULL AND ((" + " AND ".join(["name ILIKE ?"] * len(toks)) + ")" + (" OR phone LIKE ?" if len(digits) >= 6 else "") + ")"
    args = [f"%{t}%" for t in toks] + ([f"%{digits[-10:]}%"] if len(digits) >= 6 else [])
    c = P.db()
    try: rs = [dict(x) for x in c.execute(f"SELECT id,name,category,phone,is_mobile,score,outreach,contacted_at FROM leads WHERE {w} ORDER BY score DESC LIMIT 6", args)]
    finally: c.close()
    return dict(count=len(rs), matches=rs)


def t_propose_send(a):
    ids = [str(i) for i in (a.get("ids") or [])][:100]
    if wa.state["status"] != "ready":
        ms = t_find_lead(dict(query=a["query"]))["matches"] if a.get("query") and not ids else []
        return dict(error="WhatsApp is not connected, so nothing can send right now.", wa_off=True, matches=ms[:5])
    if a.get("query") and not ids:
        m = t_find_lead(dict(query=a["query"]))
        if not m.get("matches"): return dict(error=f"No saved lead matches '{a['query']}'.")
        if len(m["matches"]) > 1: return dict(error="Several leads match. Ask which one.", matches=m["matches"])
        ids = [str(m["matches"][0]["id"])]
    c = P.db()
    try:
        room = max(0, int(P.get_setting(c, "daily_limit")) - P.sent_today(c))
        if not room: return dict(error="Daily limit reached")
        if ids: rs = c.execute("SELECT id,name,outreach,is_mobile FROM leads WHERE id = ANY(?) AND phone IS NOT NULL AND outreach NOT IN ('do_not_contact','bad_number')", (ids,)).fetchall()
        else: rs = P.sendable(c, min(clamp(int(a.get("n") or 10), 1, 100), room))
        rs = list(rs)[:room]
        if not rs: return dict(error="Nothing sendable: no phone, marked do-not-contact or bad number, or nothing ready")
        items, act = get_templates(c); cfg = wa_cfg(c); warn = []
        again = [r["name"] for r in rs if r["outreach"] != "new"]
        if again: warn.append("Already messaged before, this is a resend: " + ", ".join(again[:3]))
        if any(not r["is_mobile"] for r in rs): warn.append("Includes a landline, WhatsApp may fail")
        return dict(ok=True, count=len(rs), ids=[str(r["id"]) for r in rs], names=[r["name"] for r in rs][:4], room_left=room - len(rs), warnings=warn,
                    template=next((t["name"] for t in items if t["id"] == act), "?"), est_min=max(1, round(len(rs) * (cfg["gap"] + cfg["jitter"] / 2 + 10) / 60)))
    finally: c.close()


def t_queue_front(a):
    """Move ready lead(s) to the front of the send queue (same logic as /api/leads/<id>/front)."""
    ids = [str(i) for i in (a.get("ids") or [])][:50]
    if a.get("query") and not ids:
        m = t_find_lead(dict(query=a["query"]))["matches"]
        if len(m) != 1: return dict(error="Need exactly one matching lead.", matches=m)
        ids = [str(m[0]["id"])]
    if not ids: return dict(error="No lead given")
    c = P.db(); moved = 0; base = int(time.time() * 1000)
    try:
        for k, lid in enumerate(ids):
            if c.execute(f"SELECT 1 FROM leads WHERE id=? AND {P.SENDABLE}", (lid,)).fetchone():
                c.execute("UPDATE leads SET priority=? WHERE id=?", (base + len(ids) - k, lid)); moved += 1
        c.commit()
    finally: c.close()
    if not moved: return dict(error="Not in the send queue (already contacted, no mobile number, or excluded). Open the lead and send it by hand.")
    REFRESH.add("queue"); return dict(ok=True, moved=moved)


def t_stop(_): AG["stop"] = True; return dict(ok=True, note="Stops after the current area")


# ---------- templates + settings ----------
def _save(c, items, active):
    P.set_setting(c, "templates", json.dumps(items)); P.set_setting(c, "active_template", active)
    P.set_setting(c, "template", next(t["body"] for t in items if t["id"] == active)); REFRESH.update(["settings", "queue"])


def t_tpl_list(a):
    """Full body only for the active template (or the requested id) to keep prompts small."""
    c = P.db()
    try:
        items, act = get_templates(c); want = {act, (a or {}).get("id")}
        return dict(active=act, templates=[dict(id=t["id"], name=t["name"], **({"body": t["body"]} if t["id"] in want else {})) for t in items])
    finally: c.close()


def t_tpl_save(a):
    """Create (no id) or edit (id) a template; optional activate."""
    c = P.db()
    try:
        items, active = get_templates(c); tid = a.get("id")
        if tid:
            t = next((x for x in items if x["id"] == tid), None)
            if not t: return dict(error="Unknown template id")
            t["name"] = a.get("name") or t["name"]; t["body"] = a.get("body") or t["body"]
        else:
            if len(items) >= 20: return dict(error="Template limit (20) reached")
            tid = "ai" + uuid.uuid4().hex[:6]; items.append(dict(id=tid, name=a.get("name") or "Boss draft", body=a.get("body") or ""))
        items = clean_templates(items)
        if not any(x["id"] == tid for x in items): return dict(error="Template body was empty")
        if a.get("activate"): active = tid
        t2 = next(x for x in items if x["id"] == tid); _save(c, items, active); return dict(ok=True, id=tid, active=active == tid, name=t2["name"], body=t2["body"])
    finally: c.close()


def t_tpl_use(a):
    c = P.db()
    try:
        items, _ = get_templates(c)
        if a.get("id") not in [t["id"] for t in items]: return dict(error="Unknown template id")
        _save(c, items, a["id"]); return dict(ok=True)
    finally: c.close()


def t_tpl_del(a):
    c = P.db()
    try:
        items, active = get_templates(c)
        if len(items) < 2: return dict(error="Keep at least one template")
        items = [t for t in items if t["id"] != a.get("id")]; _save(c, items, active if active in [t["id"] for t in items] else items[0]["id"]); return dict(ok=True)
    finally: c.close()


def t_settings(a):
    c = P.db(); done = {}
    try:
        if a.get("daily_limit") is not None:
            v = clamp(int(a["daily_limit"]), 1, 2000); P.set_setting(c, "daily_limit", v); done["daily_limit"] = v
        cfg = wa_cfg(c); ch = {}
        for k, lo, hi in (("step_delay", 0, 30), ("gap", 10, 300), ("jitter", 0, 120)):
            if a.get(k) is not None: ch[k] = clamp(float(a[k]), lo, hi)
        if a.get("order") in ("caption", "text_first", "media_first"): ch["order"] = a["order"]
        if a.get("album") is not None: ch["album"] = bool(a["album"])
        if ch: P.set_setting(c, "wa_cfg", json.dumps({**cfg, **ch})); done.update(ch)
        REFRESH.update(["settings", "wa", "stats", "queue"]); return dict(updated=done, current_pipeline={**cfg, **ch})
    finally: c.close()


def live():
    c = P.db()
    try: items, act = get_templates(c); tp = "; ".join(f"{t['name']}[{t['id']}]{'*' if t['id'] == act else ''}" for t in items)
    except Exception: tp = "?"
    finally: c.close()
    return live_search() + f" | templates(*=active): {tp}"


def live_search():
    if not AG["running"]: return "no search running" + (f" (last: {AG['msg']})" if AG["city"] else "") + f", whatsapp {wa.state['status']}"
    cur = AG["areas"][AG["i"]] if 0 <= AG["i"] < len(AG["areas"]) else ""
    return (f"RUNNING {AG['category']} in {AG['city']}: {AG['added']}/{AG['target']} new, area {AG['i'] + 1}/{len(AG['areas'])} ({cur}), "
            f"last done {[(d['area'], d['new']) for d in AG['done'][-4:]]}, whatsapp {wa.state['status']}")


def t_status(_):
    ev = [dict(r) for r in rows("SELECT at,kind,text FROM run_events WHERE run_id=? ORDER BY id DESC LIMIT 6", JOB["run_id"])] if JOB.get("run_id") else []
    return dict(plan=pub(), job={k: JOB.get(k) for k in ("running", "phase", "msg", "total", "done", "collected", "skipped")}, recent_events=ev, whatsapp=wa.state["status"])


MUTATING = {"start_multi_find", "stop_search", "save_template", "activate_template", "delete_template", "update_settings", "remember", "forget", "queue_front"}
CARD_TOOLS = MUTATING | {"propose_send", "plan_campaign"}   # tools whose result is an approval card


def tpl_names():
    c = P.db()
    try: return {t["id"]: t["name"] for t in get_templates(c)[0]}
    finally: c.close()


def describe(n, a):
    nm = tpl_names() if "template" in n else {}
    if n == "start_multi_find": return f"Search {a.get('target', 50)} new {a.get('category')} in {a.get('city')}?", ["Areas are picked automatically", "Stops when the target is hit or you press stop"]
    if n == "stop_search": return "Stop the running search?", ["It finishes the current area first"]
    if n == "save_template":
        t = f"Update '{a.get('name') or nm.get(a.get('id'), '?')}'?" if a.get("id") else f"Save new template '{a.get('name')}'?"
        return t, [(a.get("body") or "")[:200], "Will be set active" if a.get("activate") else "Will NOT change the active template"]
    if n == "activate_template": return f"Make '{nm.get(a.get('id'), '?')}' the active template?", ["Every send uses it from now on"]
    if n == "delete_template": return f"Delete '{nm.get(a.get('id'), '?')}'?", ["This cannot be undone"]
    if n == "update_settings": return "Change settings?", [f"{k}: {v}" for k, v in a.items() if v is not None]
    if n == "remember": return "Remember this?", [str(a.get("fact", ""))]
    if n == "queue_front": return "Put this lead first in the send queue?", ["Nothing is sent yet", "It goes out first once WhatsApp is connected"]
    return "Forget memories?", [f"containing: {a.get('contains', '')}"]


def run_tool(name, raw):
    """Returns (result for the model, UI block or list of blocks, lead_in). Mutating tools NEVER run here: they queue an approval card."""
    try: a = json.loads(raw or "{}")
    except Exception: return dict(error="bad arguments"), None, None
    if not isinstance(a, dict): return dict(error="arguments must be an object"), None, None
    if name == "ask_user":
        qs = [dict(question=str(q.get("question", ""))[:140], options=[str(o)[:60] for o in (q.get("options") or [])][:6], multi=bool(q.get("multi")), text=bool(q.get("text")) and not q.get("options"))
              for q in (a.get("questions") or [])[:2] if q.get("options") or q.get("text")]
        if not qs: return dict(error="questions need options"), None, None
        return dict(status="shown to user; wait for the answer"), dict(t="ask", questions=qs), str(a.get("lead_in") or "quick q's before i touch anything")
    if name in MUTATING:
        uid = uuid.uuid4().hex[:8]; PEND[uid] = dict(fn=name, args=a); t, lines = describe(name, a)
        return dict(status="pending_user_approval", note="NOT executed. Approval card shown. Do not say it is done."), dict(t="confirm", kind="act", id=uid, title=t, lines=lines), None
    if name not in FN: return dict(error=f"unknown tool {name}"), None, None
    try: out = FN[name](a)
    except Exception as e: out = dict(error=f"{type(e).__name__}: {e}"[:200])
    if name == "propose_send" and out.get("matches"):
        # WhatsApp off or several matches: show the lead(s) as clickable rows, plus a queue card when there is exactly one
        bls = [dict(t="leads", total=len(out["matches"]), items=out["matches"])]
        if out.get("wa_off") and len(out["matches"]) == 1:
            uid = uuid.uuid4().hex[:8]; PEND[uid] = dict(fn="queue_front", args=dict(ids=[str(out["matches"][0]["id"])]))
            bls.append(dict(t="confirm", kind="act", id=uid, title=f"Put {out['matches'][0]['name']} first in the send queue?", lines=["Nothing is sent yet", "It goes out first once WhatsApp is connected"]))
        return out, bls, ("whatsapp is off bro. tap the lead to send it yourself, or approve to put it first in the queue" if out.get("wa_off") else None)
    return out, blockify(name, out), None


def blockify(n, o):
    """A2UI-lite: tool results become typed UI components (fixed catalog, built server-side, never LLM-written)."""
    if not isinstance(o, dict) or o.get("error"): return None
    if n == "get_overview":
        return dict(t="stats", items=[["Leads", o["total"]], ["Ready", o["ready_to_message"]], ["Contacted", o["contacted"]], ["Warm", o["warm"]],
                                      ["New 24h", o["new_last_24h"]], ["Sent today", f"{o['sent_today']}/{o['daily_limit']}"]])
    if n == "next_actions": return blockify("get_overview", o["overview"])
    if n == "search_leads": return dict(t="leads", total=o["total_matching"], items=o["top"]) if o["total_matching"] else None
    if n == "find_lead": return dict(t="leads", total=o["count"], items=o["matches"]) if o["count"] else None
    if n == "run_insights": return dict(t="coverage", data=o["covered_by_category"], saturated=o["saturated"])
    if n == "propose_send":
        return dict(t="confirm", kind="send", title=f"Send to {o['count']} lead{'s' if o['count'] > 1 else ''}?",
                    lines=[", ".join(o["names"]) + (" ..." if o["count"] > len(o["names"]) else ""), "Template: " + o["template"], f"~{o['est_min']} min, {o['room_left']} sends left today"] + o.get("warnings", []), payload=dict(ids=o["ids"]))
    if n == "plan_campaign":
        each = " in each city" if len(o["cities"]) > 1 else ""
        return dict(t="confirm", kind="find", id=o["id"], title=f"Run campaign in {' & '.join(o['cities'])}?", lines=[f"{x['category']}: {x['target']} new leads{each}" for x in o["steps"]] + ["Approve starts it. You can stop anytime."])
    if n == "save_template": return dict(t="tpl", id=o["id"], name=o["name"], body=o["body"], active=o["active"])


FN = dict(find_lead=t_find_lead, plan_campaign=t_campaign, propose_send=t_propose_send, search_status=t_status, remember=t_remember, forget=t_forget, get_overview=t_overview, run_insights=t_insights, search_leads=t_search,
          suggest_areas=t_areas, start_multi_find=t_find, stop_search=t_stop, list_templates=t_tpl_list,
          save_template=t_tpl_save, activate_template=t_tpl_use, delete_template=t_tpl_del, update_settings=t_settings,
          queue_front=t_queue_front, next_actions=t_next)

# ---------- rescue for models that write tool calls as plain text ----------
CALL_RE = re.compile(r"\b(" + "|".join(list(FN) + ["ask_user"]) + r")\s*\((.*)\)\s*$", re.S | re.M)


def salvage(text):
    """Model wrote `propose_send(query="x")` as text -> turn it into a real call."""
    m = CALL_RE.search(text or "")
    if not m: return None
    name, argstr = m.groups()
    try:
        node = ast.parse(f"f({argstr})", mode="eval").body
        args = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    except Exception:
        try: args = json.loads(argstr)
        except Exception: return None
    return name, json.dumps(args)


def clean_reply(t):
    """Strip [ctx] notes, leaked 'lead_in:' / 'warning:' labels and tool-call text from anything shown or fed back to the model."""
    t = re.sub(r"\[ctx:.*", "", t or "", flags=re.S)
    t = CALL_RE.sub("", t)
    return re.sub(r"^(lead_in|warning)\s*:\s*", "", t, flags=re.M | re.I).strip()


# ---------- tools the model sees (short descriptions = fewer tokens) ----------
T, N, I, B = (dict(type=t) for t in ("string", "number", "integer", "boolean"))
def S(p=None, req=()): return dict(type="object", properties=p or {}, required=list(req))
def L(x=T): return dict(type="array", items=x)
TOOLS = [dict(type="function", function=dict(name=n, description=d, parameters=s)) for n, d, s in [
    ("remember", "Save a durable fact or preference.", S(dict(fact=T), ["fact"])),
    ("forget", "Delete memories containing a phrase.", S(dict(contains=T), ["contains"])),
    ("get_overview", "Dashboard counts: leads, ready, contacted, warm, sent today, limit, WhatsApp.", S()),
    ("next_actions", "Facts and ranked hints for 'what next / how am I doing'.", S()),
    ("run_insights", "Covered areas per business type, saturated areas, last runs.", S(dict(category=T))),
    ("search_leads", "List saved leads by type/score/status/ready. Not for one named person.", S(dict(q=T, category=T, min_score=I, ready=B, mobile=B, status=T, limit=I))),
    ("start_multi_find", "ONE type in ONE city across many areas until target new leads. Several types/cities: plan_campaign.", S(dict(category=T, city=T, target=I, per_area=I, areas=L()), ["category", "city", "target"])),
    ("search_status", "Progress of the running or last search.", S()),
    ("ask_user", "Ask 1-2 questions (buttons for closed sets, text=true for open answers). lead_in = one-line recap. Never for template text or enabling WhatsApp.", S(dict(lead_in=T, questions=L(S(dict(question=T, options=L(), multi=B, text=B), ["question"]))), ["questions"])),
    ("find_lead", "Find one lead by name or phone, any status.", S(dict(query=T), ["query"])),
    ("plan_campaign", "Plan types x cities. Approval card.", S(dict(cities=L(), steps=L(S(dict(category=T, target=I), ["category", "target"])), per_area=I), ["steps"])),
    ("propose_send", "Propose sends: query (name/phone), ids, or n next ready leads. Approval card. Uses active template.", S(dict(query=T, ids=L(), n=I))),
    ("queue_front", "Move a ready lead to the front of the send queue. query or ids. Approval card.", S(dict(query=T, ids=L()))),
    ("stop_search", "Stop the running search.", S()),
    ("list_templates", "Template names and ids, plus the active body.", S(dict(id=T))),
    ("save_template", "Create (no id) or edit (id) a template; body = full text. Rewrites: new one, activate=false.", S(dict(id=T, name=T, body=T, activate=B))),
    ("activate_template", "Set the active template.", S(dict(id=T), ["id"])),
    ("delete_template", "Delete a template.", S(dict(id=T), ["id"])),
    ("update_settings", "daily_limit, order, album, step_delay, gap, jitter.", S(dict(daily_limit=I, order=T, album=B, step_delay=N, gap=N, jitter=N)))]]

CORE = {"ask_user", "get_overview", "next_actions", "find_lead", "search_leads"}
TG = {"send": ({"propose_send", "queue_front"}, r"send|messag|whatsapp|queue|ping|blast|contact|first"),
      "find": ({"start_multi_find", "plan_campaign", "stop_search", "search_status", "run_insights"}, r"find|search|campaign|stop|progress|coverage|saturat|areas?|new leads|more leads|scrape"),
      "tpl": ({"list_templates", "save_template", "activate_template", "delete_template"}, r"templat|funn|better|rewrite|shorter|improv|wording|pitch|prompt|reply stop|v2"),
      "set": ({"update_settings", "remember", "forget"}, r"limit|setting|gap|delay|jitter|album|remember|forget|prefer|always|never")}


def pick_tools(text, last):
    """Send only the tool groups this message can need. Unclear or follow-up-after-a-question: send everything (same smarts)."""
    if last and any(b.get("t") == "ask" for b in last.get("blocks") or []): return TOOLS
    prior = {x.split(" ")[0] for x in ((last or {}).get("ctx") or "").split(" | ") if x}
    keep, hit = set(CORE), False
    for names, rx in TG.values():
        if re.search(rx, text, re.I) or names & prior: keep |= names; hit = True
    if not hit: return TOOLS
    return [t for t in TOOLS if t["function"]["name"] in keep]


def slim(name, o):
    """What the model sees of a tool result: no ids lists, phones, plans or addresses it never uses."""
    if not isinstance(o, dict): return o
    o = dict(o)
    if name == "propose_send": o.pop("ids", None)
    elif name == "get_overview": o.pop("plan", None)
    elif name == "next_actions": o["overview"] = slim("get_overview", o["overview"])
    elif name == "run_insights":
        o.pop("overview", None); o["last_runs"] = o.get("last_runs", [])[:4]
        o["covered_by_category"] = {k: [dict(area=x["area"], new=x["new"]) for x in v[:8]] for k, v in o.get("covered_by_category", {}).items()}
    elif name in ("find_lead", "propose_send") and o.get("matches"): o["matches"] = [{k: m.get(k) for k in ("id", "name", "outreach", "is_mobile")} for m in o["matches"]]
    elif name == "search_leads": o["top"] = [{k: m.get(k) for k in ("name", "category", "score", "outreach")} for m in o.get("top", [])]
    elif name == "search_status":
        p = o.get("plan", {}); o["plan"] = {k: p.get(k) for k in ("running", "city", "category", "target", "added", "msg")}; o["plan"]["last_done"] = [(d["area"], d["new"]) for d in p.get("done", [])[-5:]]
        o["recent_events"] = o.get("recent_events", [])[:4]
    return o


# ---------- proactive "Boss can do this for you" chips (deterministic, zero tokens) ----------
def suggest(used, blocks, text):
    """Each msg is a normal chat message Boss already understands; tapping a chip just sends it."""
    if any(b.get("t") == "confirm" for b in blocks): return []      # a card is waiting, don't distract
    try: o = t_overview(None)
    except Exception: return []
    out = []

    def add(label, msg=None):
        if len(out) < 3 and all(x["label"] != label for x in out): out.append(dict(label=label, msg=msg or label))

    ready, room, wa_ok = o["ready_to_message"], max(0, o["daily_limit"] - o["sent_today"]), o["whatsapp"] == "ready"
    for b in blocks:
        if b.get("t") == "leads" and len(b.get("items") or []) == 1:
            l = b["items"][0]; add(f"Send to {l['name']}")
            if l.get("outreach") == "new": add(f"Put {l['name']} first in the queue")
        if b.get("t") == "tpl" and not b.get("active"): add(f"Use {b['name']} as my active template")
    if o["search_running"]: add("How is the search going?"); add("Stop the search")
    if wa_ok and ready and room: add(f"Message the next {min(10, ready, room)} ready leads")
    if ready < 50 and not o["search_running"]:
        cat, city = AG["category"].split(" + ")[0], AG["city"].split(" & ")[0]
        add(f"Find 50 {cat} in {city}" if cat and city else "Find new leads")
    if o["contacted"] >= 100 and o["warm"] == 0: add("Make my template better")
    if not wa_ok and "next_actions" not in used: add("What should I do next?")
    if "get_overview" not in used: add("How am I doing today?")
    return out


# ---------- no-LLM fast paths for trivial, unambiguous asks ----------
FAST_OVERVIEW = re.compile(r"^\s*(how am i doing( today)?|stats?|overview|dashboard|my numbers)\s*[?.!]*\s*$", re.I)
FAST_STOP = re.compile(r"^\s*stop( the)?( search)?\s*[?.!]*\s*$", re.I)


def fast_overview():
    o = t_overview(None)
    s = f"{o['total']} leads total bro. {o['ready_to_message']} ready, {o['contacted']} contacted, {o['warm']} warm, {o['sent_today']}/{o['daily_limit']} sent today."
    if AG["running"]: s += f" search running: {AG['added']}/{AG['target']} new."
    if o["whatsapp"] != "ready": s += f" whatsapp is {o['whatsapp']}, connect it before sending."
    return s, blockify("get_overview", o)


CLAIM_RE = re.compile(r"tap approve|approval card|queued it|on the card|approve (it|the card)", re.I)


@bp.post("/api/agent/chat")
def chat():
    think("reading your message")
    try: return _chat()
    finally: TH.update(on=False, step="")


def _chat():
    text = str((request.json or {}).get("message", "")).strip()[:4000]
    if not text: return jsonify(error="Say something first"), 400
    seq0 = SEQ[0]; dbg("user", text=text)
    hist = kvj("agent_chat", []); last = hist[-1] if hist and hist[-1].get("role") == "assistant" else None
    hist.append(dict(role="user", content=text)); REFRESH.clear(); used = []; blocks = []; ctx = []

    def done(reply):
        hist.append(dict(role="assistant", content=reply, blocks=blocks, ctx=" | ".join(ctx)[:600])); kvs("agent_chat", hist[-40:])
        try: sug = suggest(used, blocks, text)
        except Exception: sug = []
        return jsonify(reply=reply, actions=used, refresh=sorted(REFRESH), blocks=blocks, suggest=sug,
                       **({"trace": [x for x in TRACE if x["seq"] > seq0]} if DEBUG else {}))

    # --- fast paths: no model call at all ---
    if FAST_OVERVIEW.match(text):
        reply, bl = fast_overview(); used.append("get_overview"); blocks.append(bl); dbg("fast_path", kind="overview"); return done(reply)
    if FAST_STOP.match(text):
        dbg("fast_path", kind="stop")
        if not AG["running"]: return done("no search running bro, nothing to stop")
        _, bl, _ = run_tool("stop_search", "{}"); used.append("stop_search"); blocks.append(bl); ctx.append("stop_search {}")
        return done("queued it, tap approve on the card")

    # --- model path ---
    def as_msg(h):
        if h["role"] != "assistant": return dict(role="user", content=h["content"][:500])
        c = (clean_reply(h["content"]) or "ok")[:350]
        if h.get("ctx"): c += "\n[ctx: " + h["ctx"][:300] + "]"      # what the cards of that turn contained
        return dict(role="assistant", content=c)

    dyn = DYN.replace("{today}", dt.date.today().isoformat()).replace("{live}", live()).replace("{mem}", "\n".join("- " + m for m in kvj("agent_mem", [])) or "(empty)")
    msgs = [dict(role="system", content=SYSTEM), dict(role="system", content=dyn)] + [as_msg(h) for h in hist[-6:]]
    tools = pick_tools(text, last); dbg("tools", n=len(tools), of=len(TOOLS))
    effort = "medium" if re.search(r"templat|funn|better|rewrite|shorter|improv|campaign|plan", text, re.I) else "low"
    cap = 3000 if effort == "medium" else 1500
    try:
        reply, nudged, claimed = None, False, False
        for _ in range(7):
            think("thinking" if not used else "writing it up")
            try: m = groq(msgs, tools, effort=effort, cap=cap)
            except ToolFail:
                if nudged: raise
                nudged = True
                msgs.append(dict(role="user", content="SYSTEM: your last tool call was malformed. Call the tool again through function calling with valid JSON arguments. Do not write calls as text."))
                continue
            calls = m.get("tool_calls")
            if not calls:
                sv = salvage(m.get("content"))
                if sv:
                    dbg("salvaged_text_call", name=sv[0], args=sv[1])
                    calls = [dict(id="s" + uuid.uuid4().hex[:6], type="function", function=dict(name=sv[0], arguments=sv[1]))]
                else:
                    txt = clean_reply(m.get("content"))
                    if CLAIM_RE.search(txt) and not any(b.get("t") == "confirm" for b in blocks) and not claimed:
                        claimed = True; tools = TOOLS; dbg("claimed_without_tool", text=txt[:200])
                        msgs += [dict(role="assistant", content=txt), dict(role="user", content="SYSTEM: you said a card is queued but you called no tool. Call the right tool now through function calling. For 'make it a new template' use save_template with no id and activate false.")]
                        continue
                    reply = txt; break
            msgs.append(dict(role="assistant", content="" if not m.get("tool_calls") else (m.get("content") or ""), tool_calls=calls))
            lead = None; rnd = []; has_card = False
            for tc in calls:
                name = tc["function"]["name"].split(".")[-1]          # "functions.find_lead" -> "find_lead"
                think(STEPS.get(name, name.replace("_", " ")))
                out, bl, ld = run_tool(name, tc["function"]["arguments"])
                bls = bl if isinstance(bl, list) else ([bl] if bl else [])
                lead = ld or lead; used.append(name); rnd.append(name); blocks.extend(bls)
                has_card = has_card or any(b.get("t") == "confirm" for b in bls)
                if name in CARD_TOOLS: ctx.append(f"{name} {tc['function']['arguments'][:300]}")
                dbg("tool", name=name, args=tc["function"]["arguments"][:300], out=json.dumps(out, default=str)[:400], blocks=[b.get("t") for b in bls])
                msgs.append(dict(role="tool", tool_call_id=tc["id"], content=json.dumps(slim(name, out), default=str, separators=(",", ":"))[:2500]))
            if lead is not None: reply = lead; break
            if has_card and all(n in CARD_TOOLS for n in rnd): reply = "queued it, tap approve on the card"; break
        if not reply:
            reply = "queued it, tap approve on the card" if any(b.get("t") == "confirm" for b in blocks) else "that took too many steps, try a smaller ask Vansh Boss"
        return done(reply)
    except Exception as e:
        dbg("chat_error", err=str(e)[:300])
        if not blocks: return jsonify(error=str(e)), 502
        return done("queued it, tap approve on the card")


@bp.get("/api/agent/thinking")
def thinking(): return jsonify(TH)


@bp.get("/api/agent/history")
def history():
    msgs = kvj("agent_chat", [])
    for m in msgs:
        if m.get("role") == "assistant": m["content"] = clean_reply(m.get("content")) or "ok"
    return jsonify(messages=msgs, memory=kvj("agent_mem", []))


@bp.post("/api/agent/reset")
def reset():
    kvs("agent_chat", [])
    if (request.get_json(silent=True) or {}).get("memory"): kvs("agent_mem", [])
    return jsonify(ok=True)


@bp.post("/api/agent/approve")
def approve():
    p = PEND.pop((request.get_json(silent=True) or {}).get("id"), None)
    if not p: return jsonify(error="That card expired. Ask Boss again."), 410
    if p.get("fn"):
        REFRESH.clear(); out = FN[p["fn"]](p["args"])
        if out.get("error"): return jsonify(error=out["error"]), 409
        return jsonify(ok=True, result=out, refresh=sorted(REFRESH), block=blockify(p["fn"], out))
    r = start_steps(p["cities"], p["steps"], p["per"])
    return (jsonify(r), 409) if r.get("error") else jsonify(r)


@bp.get("/api/agent/plan")
def plan():
    if request.args.get("v", type=int) == AG["v"]: return "", 204
    return jsonify(pub())


@bp.post("/api/agent/stop")
def stop(): return jsonify(t_stop(None))


@bp.get("/api/agent/debug")
def debug_view():
    if not DEBUG: return "", 404
    return jsonify(trace=list(TRACE))