import os, re, shutil, time, random, queue, threading, base64, tempfile, traceback
from urllib.parse import quote, urlparse
from playwright.sync_api import sync_playwright
import sbstore

PROFILE      = os.getenv("WA_PROFILE", os.path.join(tempfile.gettempdir(), "wa-profile"))
MIN_GAP      = int(os.getenv("WA_MIN_GAP", "25"))
BACKUP_EVERY = int(os.getenv("WA_BACKUP_EVERY", "1800"))
DEFAULT_CC   = os.getenv("WA_CC", "91")
ALBUM        = os.getenv("WA_ALBUM", "0") == "1"
HEADLESS     = os.getenv("WA_HEADLESS", "1") == "1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
# Chromium flags for a 512 MB / 0.1 vCPU box
ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions", "--disable-sync",
        "--disable-background-networking", "--disable-default-apps", "--disable-translate", "--mute-audio",
        "--no-first-run", "--disable-features=Translate,MediaRouter,OptimizationHints",
        "--renderer-process-limit=1", "--js-flags=--max-old-space-size=256"]
ALLOW_HOSTS = ("whatsapp.com", "whatsapp.net", "facebook.com", "fbcdn.net", "wa.me")

state = dict(status="starting", qr=None, err=None, debug=None, last_ok=None, mem_mb=None)
_q = queue.Queue()

class WAError(Exception): pass

BOX  = "footer div[contenteditable='true']"
ATTACH_SEL = ("button[aria-label='Attach'], [aria-label='Attach'], [title='Attach'], "
              "[data-icon='plus-rounded'], [data-icon='attach-menu-plus'], [data-icon='plus'], "
              "[data-icon='clip'], [data-icon='attach']")
FILE_INPUT = "input[accept*='image']"
INVALID_KEYS = ("invalid", "not on whatsapp", "isn't on whatsapp", "isn\u2019t on whatsapp", "not registered")
OUT_SEL = "div.message-out, [data-id^='true_']"

# ---------------------------------------------------------------- helpers
def _b64(img): return "data:image/png;base64," + base64.b64encode(img).decode()

def _debug_shot(page):
    try: state["debug"] = _b64(page.screenshot())
    except Exception: pass

def _norm(phone):
    d = re.sub(r"\D", "", phone or "").lstrip("0")
    return DEFAULT_CC + d if len(d) == 10 else d

def _say(step, msg):
    try: step(msg)
    except Exception: pass

def _mem_mb():
    """Resident memory of this process tree (Linux); None elsewhere. Cheap, no psutil."""
    try:
        tot = 0
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    with open(f"/proc/{pid}/statm") as f: tot += int(f.read().split()[1])
                except Exception: pass
        return round(tot * os.sysconf("SC_PAGE_SIZE") / 1048576)
    except Exception: return None

def _route(route):
    """Drop fonts, media streams and third-party requests; WhatsApp's own hosts and blob/data pass."""
    req = route.request
    try:
        u = req.url
        if u.startswith(("blob:", "data:")): return route.continue_()
        if req.resource_type in ("font", "media"): return route.abort()
        host = urlparse(u).hostname or ""
        if not any(host == h or host.endswith("." + h) for h in ALLOW_HOSTS): return route.abort()
        return route.continue_()
    except Exception:
        try: route.continue_()
        except Exception: pass

_last_shot = 0
def _refresh(page):
    global _last_shot
    try:
        if page.locator("#pane-side").count():
            state.update(status="ready", qr=None, err=None); return
        use_here = page.get_by_role("button", name="Use here")
        if use_here.count(): use_here.first.click(timeout=2000); return
        qr = page.locator("div[data-ref], canvas[aria-label]")
        if qr.count():
            state.update(status="qr", qr=_b64(qr.first.screenshot())); return
        if time.time() - _last_shot > 8:
            _last_shot = time.time()
            state.update(status="starting", qr=_b64(page.screenshot()))
    except Exception:
        pass

def _wait_ready(page, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        _refresh(page)
        if state["status"] == "ready": return True
        time.sleep(2)
    return False

def _ack(page, timeout=90):
    """True when WhatsApp shows no pending clock icons (server accepted the message)."""
    try: page.wait_for_selector("[data-icon='msg-time']", state="detached", timeout=timeout * 1000); return True
    except Exception: return False

# ---------------------------------------------------------------- chat actions
def _open_chat(page, n, text=""):
    page.goto(f"https://web.whatsapp.com/send?phone={n}" + (f"&text={quote(text)}" if text else ""),
              wait_until="domcontentloaded", timeout=60000)
    end = time.time() + 60
    while time.time() < end:
        if page.locator(BOX).count():
            page.wait_for_timeout(1200); return
        dlg = page.locator("div[role='dialog']")
        if dlg.count():
            try: t = dlg.first.inner_text(timeout=2000).lower()
            except Exception: t = ""
            if any(k in t for k in INVALID_KEYS): raise WAError(f"Number is not on WhatsApp ({n})")
        if not page.locator("#pane-side").count() and page.locator("div[data-ref], canvas[aria-label]").count():
            raise WAError("WhatsApp is not connected. Scan the QR in Settings.")
        page.wait_for_timeout(1000)
    t = ""
    try:
        if page.locator("div[role='dialog']").count(): t = page.locator("div[role='dialog']").first.inner_text(timeout=2000)[:80]
    except Exception: pass
    raise WAError(f"Chat did not open{': ' + t if t else ''}")

def _open_attach(page):
    footer = page.locator("footer")
    for _ in range(3):
        try:
            btn = footer.locator(ATTACH_SEL).first
            try: btn.click(timeout=6000)
            except Exception: btn.click(force=True, timeout=4000)
            page.wait_for_selector(FILE_INPUT, state="attached", timeout=6000)
            return
        except Exception:
            page.keyboard.press("Escape"); page.wait_for_timeout(1500)
    _debug_shot(page)
    icons = page.evaluate("""() => [...document.querySelectorAll('footer [data-icon], footer [aria-label]')]
        .map(e => e.getAttribute('data-icon') || e.getAttribute('aria-label')).slice(0, 15)""")
    raise WAError(f"Attach button not found. Footer has: {icons}")

def _caption_box(page):
    boxes = page.locator("div[contenteditable='true']")
    for i in range(boxes.count() - 1, -1, -1):
        b = boxes.nth(i)
        try:
            if b.is_visible() and not b.evaluate("e => !!e.closest('footer, #side, #pane-side')"): return b
        except Exception: pass
    return None

def _editor_open(page): return _caption_box(page) is not None

def _try_send(page, how):
    if how == 0:
        for loc in (page.locator("[aria-label='Send']"),
                    page.get_by_role("button", name=re.compile(r"^send$", re.I)),
                    page.locator("[data-icon*='send']")):
            try:
                n = loc.count()
                for i in range(n - 1, -1, -1):
                    el = loc.nth(i)
                    if el.is_visible() and not el.evaluate("e => !!e.closest('footer')"):
                        el.click(timeout=3000, force=True); return
            except Exception: pass
    else:
        cap = _caption_box(page)
        if cap: cap.click(timeout=3000)
        page.keyboard.press("Enter")

def _dismiss_popups(page):
    try:
        ok = page.get_by_role("button", name=re.compile(r"^ok$", re.I))
        if ok.count() and ok.first.is_visible(): ok.first.click(timeout=2000)
    except Exception: pass

def _choose_files(page, paths):
    footer = page.locator("footer")
    for _ in range(3):
        try:
            btn = footer.locator(ATTACH_SEL).first
            try: btn.click(timeout=6000)
            except Exception: btn.click(force=True, timeout=4000)
            item = page.get_by_text(re.compile(r"^Photos\s*(&|and)\s*videos$", re.I)).first
            item.wait_for(state="visible", timeout=5000)
            with page.expect_file_chooser(timeout=8000) as fc: item.click()
            fc.value.set_files(paths); return
        except Exception:
            try: page.keyboard.press("Escape")
            except Exception: pass
            page.wait_for_timeout(1500)
    _open_attach(page)
    inp = page.locator("input[accept*='video']")
    if not inp.count(): raise WAError("Photos & videos input not found")
    inp.first.set_input_files(paths)

def _attach_send(page, paths, caption):
    """Returns (captioned, acked). Raises only if nothing was sent, so a retry cannot duplicate."""
    _open_attach(page); _choose_files(page, paths)
    end = time.time() + 20
    while time.time() < end and not _editor_open(page): page.wait_for_timeout(500)
    page.wait_for_timeout(2500)
    captioned = False
    if caption:
        cap = _caption_box(page)
        if cap:
            try: cap.click(timeout=3000); page.keyboard.insert_text(caption); captioned = True
            except Exception: pass
    sent = False
    for how in (0, 1, 2):
        if not _editor_open(page): sent = True; break
        try: _try_send(page, how)
        except Exception: pass
        end = time.time() + 12
        while time.time() < end and _editor_open(page): page.wait_for_timeout(500)
        if not _editor_open(page): sent = True; break
    _dismiss_popups(page)
    if not sent: _debug_shot(page); raise WAError("Send click had no effect")
    acked = _ack(page, 120); page.wait_for_timeout(1000)
    return captioned, acked

def _send_text(page, n, text, step):
    _say(step, "Sending text")
    _open_chat(page, n, text)
    box = page.locator(BOX).first
    end = time.time() + 10
    while time.time() < end and not box.inner_text().strip(): page.wait_for_timeout(300)
    if not box.inner_text().strip(): raise WAError("Message text never appeared in the composer")
    box.click(timeout=3000); page.keyboard.press("Enter")
    end = time.time() + 15
    while time.time() < end and box.inner_text().strip(): page.wait_for_timeout(300)
    if box.inner_text().strip(): _debug_shot(page); raise WAError("Enter did not send the message")
    return _ack(page, 90)

def _send_media(page, n, files, caption, album, step):
    groups = [list(files)] if album else [[f] for f in files]
    captioned, acked = False, True
    for i, g in enumerate(groups):
        label = f"Sending media {i + 1} of {len(groups)}"
        for attempt in (1, 2):
            _say(step, label if attempt == 1 else label + " (retry)")
            try:
                _open_chat(page, n)
                got, ok = _attach_send(page, g, caption if i == 0 else "")
                captioned = captioned or (i == 0 and got); acked = acked and ok
                break
            except WAError as e:
                if "not on WhatsApp" in str(e) or "not connected" in str(e) or attempt == 2: raise
            except Exception:
                if attempt == 2: raise
    return captioned, acked

def _send(page, phone, text, files, step, cfg=None):
    """cfg: order = caption | text_first | media_first; album bool; step_delay seconds between parts.
    Returns 'sent' (server acknowledged every part) or 'unconfirmed'."""
    cfg = cfg or {}
    n = _norm(phone)
    if len(n) < 8: raise WAError(f"Phone number looks wrong ({phone})")
    order = cfg.get("order", "caption"); album = bool(cfg.get("album", ALBUM))
    pause = max(0, min(30, float(cfg.get("step_delay", 2)))) * 1000
    _say(step, "Opening chat")
    if not files: return "sent" if _send_text(page, n, text, step) else "unconfirmed"
    ok = True
    if order == "text_first" and text:
        ok &= _send_text(page, n, text, step); page.wait_for_timeout(pause)
        _, a = _send_media(page, n, files, "", album, step); ok &= a
    elif order == "media_first" and text:
        _, a = _send_media(page, n, files, "", album, step); ok &= a; page.wait_for_timeout(pause)
        ok &= _send_text(page, n, text, step)
    else:
        cap, a = _send_media(page, n, files, text, album, step); ok &= a
        if text and not cap: page.wait_for_timeout(pause); ok &= _send_text(page, n, text, step)
    return "sent" if ok else "unconfirmed"

# ---------------------------------------------------------------- browser session
def _launch(p):
    ctx = p.chromium.launch_persistent_context(PROFILE, headless=HEADLESS, user_agent=UA, locale="en-US",
                                               viewport={"width": 1100, "height": 800}, args=ARGS)
    try: ctx.route("**/*", _route)
    except Exception: pass
    for extra in ctx.pages[1:]:
        try: extra.close()
        except Exception: pass
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("dialog", lambda d: d.accept())
    page.set_default_timeout(30000)
    page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=60000)
    return ctx, page

_act = queue.Queue()
def request_action(name):
    """'sync' = upload profile now; 'reset' = log out locally, delete cloud copy, show a fresh QR."""
    if name not in ("sync", "reset"): raise WAError("Unknown action")
    state["action"] = name; _act.put(name)

def _backup(ctx, p):
    try: ctx.close()
    except Exception: pass
    try: sbstore.backup_profile(PROFILE); state["sync"] = dict(ok=True, at=time.time(), err=None)
    except Exception as e:
        print("profile backup failed:", e); state["sync"] = dict(ok=False, at=time.time(), err=str(e)[:200])
    state.update(status="starting", qr=None)
    return _launch(p)

def _session(p):
    last = 0.0; last_backup = time.time(); backup_at = None; was_qr = False; last_mem = 0
    ctx, page = _launch(p)
    try:
        while True:
            try: job = _q.get(timeout=3)
            except queue.Empty: job = None
            if page.is_closed():
                try: ctx.close()
                except Exception: pass
                ctx, page = _launch(p)
            _refresh(page)
            if time.time() - last_mem > 30: last_mem = time.time(); state["mem_mb"] = _mem_mb()
            st = state["status"]
            if st == "qr": was_qr = True
            if st == "ready" and was_qr: backup_at = time.time() + 30; was_qr = False
            if (sbstore.configured() and st == "ready" and not job and _q.empty() and
                    ((backup_at and time.time() >= backup_at) or time.time() - last_backup > BACKUP_EVERY)):
                backup_at = None; ctx, page = _backup(ctx, p); last_backup = time.time(); continue
            try: act = _act.get_nowait()
            except queue.Empty: act = None
            if act == "sync" and sbstore.configured() and st == "ready" and not job:
                ctx, page = _backup(ctx, p); last_backup = time.time(); state["action"] = None; continue
            if act == "reset" and not job:
                try: ctx.close()
                except Exception: pass
                shutil.rmtree(PROFILE, ignore_errors=True)
                if sbstore.configured():
                    try: sbstore.delete(sbstore.PROFILE_OBJ, sbstore.PROFILE_BUCKET)
                    except Exception: pass
                state.update(status="starting", qr=None, action=None, sync=None); was_qr = False
                ctx, page = _launch(p); continue
            if act and job: _act.put(act)            # a send is in flight: retry after it
            if act: state["action"] = None if act != "reset" and not job else state.get("action")
            if not job: continue
            args, box = job                       # args = (phone, text, files, step, cfg)
            if box.get("cancel"): box["err"] = "Cancelled"; box["done"].set(); continue
            step, cfg = args[3], args[4]
            try:
                if state["status"] != "ready" and not _wait_ready(page, 60):
                    raise WAError("WhatsApp is not connected. Scan the QR in Settings.")
                gap = last + max(5, float(cfg.get("gap", MIN_GAP))) + random.uniform(0, max(0, float(cfg.get("jitter", 15)))) - time.time()
                if gap > 0: _say(step, "Waiting before sending (anti-spam delay)"); time.sleep(gap)
                if box.get("cancel"): raise WAError("Cancelled")
                box["result"] = _send(page, *args); last = time.time(); box["ok"] = True
                state["last_ok"] = time.time()
            except Exception as e:
                _debug_shot(page)
                box["err"] = str(e) if isinstance(e, WAError) else f"Send failed: {type(e).__name__}: {str(e)[:150]}"
                try: page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=30000)
                except Exception: pass
            box["done"].set()
    finally:
        try: ctx.close()
        except Exception: pass

def _run():
    if sbstore.configured():
        try: print("profile restored" if sbstore.restore_profile(PROFILE) else "no saved profile, starting fresh")
        except Exception as e: print("profile restore failed:", e)
    while True:
        try:
            with sync_playwright() as p: _session(p)
        except Exception as e:
            traceback.print_exc()
            state.update(status="error", err=f"{type(e).__name__}: {str(e)[:300]}")
        # fail any queued jobs so callers never hang on a dead browser
        while not _q.empty():
            try: _, b = _q.get_nowait(); b["err"] = "WhatsApp browser restarted"; b["done"].set()
            except Exception: break
        time.sleep(15)
        state.update(status="starting", err=None)

threading.Thread(target=_run, daemon=True).start()

# ---------------------------------------------------------------- public API
def send(phone, text, files=(), step=lambda s: None, cfg=None):
    """Backward compatible. Returns 'sent' or 'unconfirmed'; raises WAError on failure."""
    box = {"done": threading.Event()}
    _q.put(((phone, text, list(files), step, dict(cfg or {})), box))
    if not box["done"].wait(300 + 150 * len(files)):
        box["cancel"] = True
        raise WAError("Timed out")
    if "err" in box: raise WAError(box["err"])
    return box.get("result", "sent")