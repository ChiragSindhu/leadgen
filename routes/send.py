"""Send queue and automatic WhatsApp sending."""
import threading
from flask import Blueprint, request, jsonify
import pipeline as P
import wa
from sbstore import local_media
from core import SJ, claim, num
from templating import render_tpl
from .media import media_list, pub
from .whatsapp import wa_cfg

bp = Blueprint("send", __name__)


@bp.get("/api/queue")
def queue():
    c = P.db(); lim, used = int(P.get_setting(c, "daily_limit")), P.sent_today(c)
    tpl = P.get_setting(c, "template"); ms = [pub(m) for m in media_list(c, True)]
    items = [{**dict(r), "link": P.wa_link(r["phone"], render_tpl(tpl, dict(r)))} for r in P.sendable(c, max(0, lim - used))]
    c.close(); return jsonify(used=used, limit=lim, items=items, media=ms, wa=wa.state["status"])


def rlog(rid, kind, text):
    c = P.db()
    try: c.execute("INSERT INTO run_events(run_id,at,kind,text) VALUES(?,?,?,?)", (rid, P.now(), kind, text)); c.commit()
    finally: c.close()


def deliver(lid, step):
    """Returns 'sent' (server-acknowledged) or 'unconfirmed'. Raises on failure."""
    c = P.db()
    try:
        r = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        if not r or not r["phone"]: raise wa.WAError("No phone number")
        lead = dict(r); text = render_tpl(P.get_setting(c, "template"), lead)
        files = [local_media(m) for m in media_list(c, True)]
        cfg = wa_cfg(c)
    finally: c.close()
    res = wa.send(lead["phone"], text, files, step, cfg)
    c = P.db()
    try: P.set_outreach(c, lid, "messaged", lead.get("notes"))
    finally: c.close()
    return res


@bp.post("/api/send")
def send_start():
    b = request.json or {}
    if wa.state["status"] != "ready": return jsonify(error="WhatsApp is not connected. Scan the QR code in Settings."), 400
    busy = claim("send")
    if busy: return jsonify(error=busy), 409
    c = P.db()
    try:
        room = max(0, int(P.get_setting(c, "daily_limit")) - P.sent_today(c))
        if b.get("ids"): ids = [str(i) for i in b["ids"]][:100]; label = "Auto send"
        else:
            n = num(b.get("n"), 1, 100, "How many"); ids = [str(r["id"]) for r in P.sendable(c, min(n, room))]; label = "Send all"
        ids = ids[:room]
        if not ids: SJ["running"] = False; return jsonify(error="Daily limit reached" if not room else "No leads ready to send"), 400
        label += f" ({len(ids)} lead{'s' if len(ids) > 1 else ''})"
        rid = c.execute("INSERT INTO runs(at,query,source,requested,fetched,added,changed,calls,status) VALUES(?,?,?,?,?,0,0,0,'running') RETURNING id",
                        (P.now(), label, "whatsapp", len(ids), len(ids))).fetchone()[0]; c.commit()
    except ValueError as e: SJ["running"] = False; return jsonify(error=str(e)), 400
    except Exception as e: SJ["running"] = False; return jsonify(error=str(e)), 500
    finally: c.close()
    SJ.update(running=True, stop=False, msg=label, total=len(ids), done=0, sent=0, failed=0, unconfirmed=0, current="", step="Starting", phase="Sending", run_id=rid, last=None)
    rlog(rid, "info", f"Started: {len(ids)} lead(s) queued")

    def work():
        sent = failed = unc = 0; err = None
        try:
            for i, lid in enumerate(ids):
                if SJ.get("stop"): rlog(rid, "warn", "Stopped by you"); break
                c = P.db(); r = c.execute("SELECT name FROM leads WHERE id=?", (lid,)).fetchone(); c.close(); name = r["name"] if r else lid
                SJ.update(current=name, step="Starting", phase=f"Sending {i + 1} of {len(ids)}"); rlog(rid, "info", f"Sending to {name}")
                try:
                    res = deliver(lid, lambda s: (SJ.update(step=s), rlog(rid, "info", f"{name}: {s}")))
                    sent += 1
                    if res == "unconfirmed": unc += 1; rlog(rid, "warn", f"{name}: sent but WhatsApp never confirmed delivery to its server")
                    else: rlog(rid, "info", f"Sent to {name} (confirmed)")
                except Exception as e:
                    failed += 1; msg = str(e) if isinstance(e, wa.WAError) else f"{type(e).__name__}: {str(e)[:150]}"
                    rlog(rid, "warn", f"{name}: {msg}")
                    if "not connected" in msg or "restarted" in msg: err = msg; break
                SJ.update(done=i + 1, sent=sent, failed=failed, unconfirmed=unc, last=lid)
        except Exception as e: err = str(e)
        finally:
            try:
                c = P.db()
                try:
                    c.execute("UPDATE runs SET status=?, added=?, changed=?, finished_at=?, error=? WHERE id=?",
                              ("failed" if err else "done", sent, failed, P.now(),
                               err or "; ".join(x for x in (f"{failed} failed" if failed else "", f"{unc} unconfirmed" if unc else "") if x) or None, rid)); c.commit()
                finally: c.close()
            finally:
                SJ.update(running=False, phase="Finished", step="", msg=f"Sent {sent}, failed {failed}" + (f", {unc} unconfirmed" if unc else ""))   # lock always released
    threading.Thread(target=work, daemon=True).start(); return jsonify(ok=True)


@bp.post("/api/send/stop")
def send_stop(): SJ["stop"] = True; return jsonify(ok=True)


@bp.get("/api/send/job")
def send_job():
    if request.args.get("v", type=int) == SJ["v"]: return "", 204
    return jsonify(SJ)
