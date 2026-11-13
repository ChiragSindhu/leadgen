"""Telegram control panel for the lead pipeline (button-based, made for non-technical users).
Setup: put TELEGRAM_TOKEN and ADMIN_IDS in a .env file next to this script, then run:  python bot.py
The PC running this must stay on. Only chat IDs listed in ADMIN_IDS can use the bot."""
import os, re, sys, html, time, threading, requests
import pipeline as P

HERE = os.path.dirname(os.path.abspath(__file__))
def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8-sig"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
load_env()
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
API = f"https://api.telegram.org/bot{TOKEN}/"
CATS = ["real estate", "pg", "gym", "clinic", "salon", "restaurant"]
STATUS = {"s": "messaged", "d": "do_not_contact", "b": "bad_number", "r": "replied", "i": "interested", "n": "not_interested"}
STATE, SCRAPE_LOCK = {}, threading.Lock()

esc = lambda s: html.escape(str(s or ""))
def S(chat): return STATE.setdefault(chat, {"step": None, "skipped": set(), "mode": "send"})
def B(text, data=None, url=None): return {"text": text, **({"url": url} if url else {"callback_data": data})}
HOME = [B("🏠 Menu", "home")]

def api(method, **kw):
    try: r = requests.post(API + method, json=kw, timeout=70).json()
    except Exception as e: print("network error:", e); return None
    if not r.get("ok"): print("Telegram error:", method, r.get("description"))
    return r.get("result")

def say(chat, text, rows=None):
    kw = {"reply_markup": {"inline_keyboard": rows}} if rows else {}
    return api("sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview=True, **kw)

def menu(chat, text="What would you like to do?"):
    S(chat)["step"] = None
    say(chat, text, [[B("🔎 Find businesses", "find"), B("📤 Send messages", "send")],
                     [B("📥 Follow-ups", "fu"), B("📊 Stats", "stats")],
                     [B("📝 Message & media", "msg"), B("➕ Add business", "add")]])

# ---------- send / follow-up cards ----------
def card(chat, mode):
    c = P.db(); st = S(chat); st["mode"] = mode
    if mode == "send":
        used, lim = P.sent_today(c), int(P.get_setting(c, "daily_limit"))
        if used >= lim:
            return say(chat, f"✅ Daily limit reached ({used}/{lim}). Take a break: sending too many in one day can get your WhatsApp blocked. Continue tomorrow!", [HOME])
        rows = P.sendable(c, 1, st["skipped"])
        if not rows: return say(chat, "No new leads ready. Tap Find businesses to get more.", [[B("🔎 Find businesses", "find")], HOME])
    else:
        rows = [r for r in c.execute("SELECT * FROM leads WHERE outreach='messaged' ORDER BY contacted_at DESC LIMIT 60") if r["id"] not in st["skipped"]][:1]
        if not rows: return say(chat, "No follow-ups waiting 🎉", [HOME])
    l = rows[0]; i = l["id"]
    head = f"<b>{esc(l['name'])}</b>\n{esc(l['category'])} · {esc(l['phone'])}\n{esc(l['address'])}"
    if mode == "send":
        btn = [[B("💬 Open WhatsApp", url=P.wa_link(l["phone"], P.render(P.get_setting(c, "template"), l)))]]
        if P.get_setting(c, "media_id"): btn.append([B("📎 Get photo/video to attach", "media")])
        btn += [[B("✅ I sent it", f"s|{i}"), B("⏭ Skip", f"k|{i}")], [B("🚫 Don't contact", f"d|{i}"), B("❌ Bad number", f"b|{i}")]]
        say(chat, f"📤 <b>Message {used + 1} of {lim} today</b>\n\n{head}\n\n1) Tap Open WhatsApp\n2) Read it, press send yourself\n3) Come back and tap ✅", btn)
    else:
        say(chat, f"📥 <b>Follow-up</b>\n\n{head}", [[B("💬 Open chat", url=P.wa_link(l["phone"] or ""))],
            [B("↩ Replied", f"r|{i}"), B("⭐ Interested", f"i|{i}")], [B("👎 Not interested", f"n|{i}"), B("⏭ Next", f"k|{i}")], HOME])

def msg_menu(chat):
    c = P.db()
    say(chat, f"<b>Your message:</b>\n{esc(P.get_setting(c, 'template'))}\n\n<b>Photo/video:</b> {P.get_setting(c, 'media_type') or 'none'}\n<b>Daily limit:</b> {P.get_setting(c, 'daily_limit')}",
        [[B("✏ Edit text", "tpl")], [B("🖼 Set photo/video", "setmedia"), B("🗑 Remove media", "clrmedia")], [B("➖5 daily limit", "lim|-5"), B("➕5 daily limit", "lim|5")], HOME])

def send_media(chat):
    c = P.db(); t, fid = P.get_setting(c, "media_type"), P.get_setting(c, "media_id")
    if not fid: return say(chat, "No photo/video saved yet.", [HOME])
    api("sendPhoto" if t == "photo" else "sendVideo", chat_id=chat, **{t: fid}, caption="Save this to your gallery, then attach it in WhatsApp (it shows at the top of the attach menu).")

def stats(chat):
    c = P.db()
    def q(sql): return c.execute(sql).fetchone()[0]
    total = q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL")
    contacted = q("SELECT COUNT(*) FROM leads WHERE outreach != 'new'")
    warm = q("SELECT COUNT(*) FROM leads WHERE outreach IN ('replied','interested')")
    say(chat, "📊 <b>Stats</b>\n"
        f"Total leads: {total}\nReady to message: {len(P.sendable(c, 100000))}\n"
        f"Sent today: {P.sent_today(c)}/{P.get_setting(c, 'daily_limit')}\n"
        f"Contacted (all time): {contacted}\nReplied / interested: {warm}", [HOME])

# ---------- find businesses ----------
def ask_loc(chat):
    last = P.get_setting(P.db(), "last_location"); S(chat)["step"] = "find_loc"
    say(chat, "📍 Which area and city? Type it, e.g. <i>Indiranagar, Bengaluru</i>", [[B(f"📍 {last}", "fl")]] if last else None)

def ask_n(chat):
    S(chat)["step"] = None
    say(chat, "How many businesses to check? (more = slower)", [[B("10", "fn|10"), B("20", "fn|20"), B("30", "fn|30")], HOME])

def start_scrape(chat, cat, loc, n):
    if not cat or not loc: return menu(chat)
    if not SCRAPE_LOCK.acquire(blocking=False): return say(chat, "⏳ A search is already running. I'll message you when it finishes.", [HOME])
    say(chat, f"🔎 Searching <b>{esc(cat)}</b> in {esc(loc)}. This takes a few minutes, I'll message you when done.")
    def work():
        try:
            f, a, _ = P.run_scrape(cat, loc, n); ready = len(P.sendable(P.db(), 100000))
            warn = f"\n⚠️ Stopped early: {esc(P.LAST_WARNING)}" if P.LAST_WARNING else ""
            say(chat, f"✅ Search finished. {f} businesses with contact info, <b>{a} new</b>.\n{ready} leads ready to message.{warn}", [[B("📤 Start sending", "send")], HOME])
        except Exception as e: say(chat, f"⚠️ Search failed: {esc(str(e))[:300]}", [HOME])
        finally: SCRAPE_LOCK.release()
    threading.Thread(target=work, daemon=True).start()

# ---------- routing ----------
def on_callback(chat, data):
    st = S(chat); act, _, arg = data.partition("|"); c = P.db()
    if act == "home": return menu(chat)
    if act in STATUS:
        r = c.execute("SELECT notes FROM leads WHERE id=?", (arg,)).fetchone()
        if r: P.set_outreach(c, arg, STATUS[act], r["notes"])
        return card(chat, st["mode"])
    if act == "k": st["skipped"].add(arg); return card(chat, st["mode"])
    if act in ("send", "fu"): st["skipped"] = set(); return card(chat, act)
    if act == "stats": return stats(chat)
    if act == "msg": return msg_menu(chat)
    if act == "media": return send_media(chat)
    if act == "tpl": st["step"] = "tpl"; return say(chat, "Type your new message. Use {name} for the business name and {category} for its type. Mention who you are and add 'reply STOP to opt out'.")
    if act == "setmedia": st["step"] = "media"; return say(chat, "Send me the photo or video now.")
    if act == "clrmedia": P.set_setting(c, "media_id", ""); P.set_setting(c, "media_type", ""); return msg_menu(chat)
    if act == "lim":
        P.set_setting(c, "daily_limit", max(5, min(100, int(P.get_setting(c, "daily_limit")) + int(arg)))); return msg_menu(chat)
    if act == "add": st["step"] = "add"; return say(chat, "Send details, one business per line:\n<code>Name, phone, type</code>\nor share a contact from your phone.", [HOME])
    if act == "find":
        rows = [[B(x, f"fc|{x}") for x in CATS[i:i + 2]] for i in range(0, len(CATS), 2)]
        return say(chat, "What kind of business?", rows + [[B("✏ Other (type it)", "fo")], HOME])
    if act == "fo": st["step"] = "find_cat"; return say(chat, "Type the business type (e.g. bakery, coaching, tailor):")
    if act == "fc": st["cat"] = arg; return ask_loc(chat)
    if act == "fl": st["loc"] = P.get_setting(c, "last_location"); return ask_n(chat)
    if act == "fn": return start_scrape(chat, st.get("cat"), st.get("loc"), int(arg))
    menu(chat)

def add_items(chat, items):
    if not items: return say(chat, "I couldn't read that. Use: <code>Name, phone, type</code>", [HOME])
    res = P.import_businesses(P.db(), items)
    say(chat, f"✅ Added {res['added']}, updated {res['updated']}." + "".join(f"\n⚠️ {esc(w)}" for w in res["warnings"][:5]), [[B("➕ Add more", "add")], HOME])

def on_text(chat, text):
    st = S(chat); step = st["step"]; c = P.db(); text = text.strip()
    if step == "find_cat": st["cat"] = text[:40]; return ask_loc(chat)
    if step == "find_loc": st["loc"] = text[:100]; P.set_setting(c, "last_location", st["loc"]); return ask_n(chat)
    if step == "tpl":
        if len(text) < 5: return say(chat, "That's too short, try again.")
        P.set_setting(c, "template", text); st["step"] = None; return msg_menu(chat)
    if step == "add":
        items = []
        for ln in text.splitlines():
            p = [x.strip() for x in re.split(r"[,|]", ln) if x.strip()]
            if len(p) >= 2: items.append({"name": p[0], "phone": p[1], "category": p[2] if len(p) > 2 else None})
        return add_items(chat, items)
    menu(chat)

def handle(u):
    cb = u.get("callback_query"); msg = u.get("message") or {}
    chat = cb["message"]["chat"]["id"] if cb else msg.get("chat", {}).get("id")
    if chat is None: return
    if chat not in ADMINS:
        return say(chat, f"🔒 Not authorised.\nYour chat ID is <code>{chat}</code>. Put it in ADMIN_IDS in the .env file and restart the bot.")
    if cb: api("answerCallbackQuery", callback_query_id=cb["id"]); return on_callback(chat, cb.get("data", ""))
    st = S(chat)
    if msg.get("photo") or msg.get("video"):
        if st["step"] != "media": return say(chat, "To set the photo/video, tap 📝 Message & media first.", [HOME])
        t, fid = ("photo", msg["photo"][-1]["file_id"]) if msg.get("photo") else ("video", msg["video"]["file_id"])
        P.set_setting(P.db(), "media_type", t); P.set_setting(P.db(), "media_id", fid); st["step"] = None
        return msg_menu(chat)
    if msg.get("contact") and st["step"] == "add":
        ct = msg["contact"]; return add_items(chat, [{"name": ((ct.get("first_name") or "") + " " + (ct.get("last_name") or "")).strip(), "phone": ct.get("phone_number")}])
    text = msg.get("text") or ""
    if text.startswith("/"): return menu(chat, "👋 Hi! What would you like to do?")
    on_text(chat, text)

def main():
    if not TOKEN: sys.exit("Set TELEGRAM_TOKEN in .env (create a bot with @BotFather on Telegram).")
    print("Bot running. Admins:", ADMINS or "NONE YET (message the bot to get your chat ID)")
    api("setMyCommands", commands=[{"command": "menu", "description": "Open the menu"}])
    offset = None
    while True:
        try: ups = requests.post(API + "getUpdates", json={"offset": offset, "timeout": 50}, timeout=65).json().get("result", [])
        except Exception as e: print("poll error:", e); time.sleep(5); continue
        for u in ups:
            offset = u["update_id"] + 1
            try: handle(u)
            except Exception as e: print("handler error:", repr(e))

if __name__ == "__main__": main()
