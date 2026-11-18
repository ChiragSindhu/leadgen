"""WhatsApp connection status, backup/reset, and delivery pipeline config."""
import json
from flask import Blueprint, request, jsonify
import pipeline as P
import wa, sbstore
from core import JOB, SJ, busy_state, clamp

bp = Blueprint("whatsapp", __name__)

WA_DEFAULT = dict(order="caption", album=False, step_delay=2, gap=25, jitter=15)


def wa_cfg(c=None):
    own = c is None; c = c or P.db()
    try: raw = P.get_setting(c, "wa_cfg")
    finally:
        if own: c.close()
    try: d = json.loads(raw) if raw else {}
    except Exception: d = {}
    return {**WA_DEFAULT, **{k: d[k] for k in d if k in WA_DEFAULT}}


@bp.route("/api/wa/config", methods=["GET", "PUT"])
def wa_config():
    c = P.db()
    try:
        cur = wa_cfg(c)
        if request.method == "PUT":
            b = request.json or {}
            if b.get("order", cur["order"]) not in ("caption", "text_first", "media_first"): return jsonify(error="Unknown order"), 400
            try:
                cur = dict(order=b.get("order", cur["order"]), album=bool(b.get("album", cur["album"])),
                           step_delay=clamp(float(b.get("step_delay", cur["step_delay"])), 0, 30),
                           gap=clamp(float(b.get("gap", cur["gap"])), 10, 300), jitter=clamp(float(b.get("jitter", cur["jitter"])), 0, 120))
            except (TypeError, ValueError): return jsonify(error="Delays must be numbers"), 400
            P.set_setting(c, "wa_cfg", json.dumps(cur))
        return jsonify(cur)
    finally: c.close()


@bp.get("/api/wa/status")
def wa_status(): return jsonify({**wa.state, "busy": busy_state()})


def _wa_action(name):
    if JOB["running"] or SJ["running"]: return jsonify(error="Wait for the running search or send to finish first."), 409
    if name == "sync" and not sbstore.configured(): return jsonify(error="Supabase storage is not configured on the server"), 503
    if name == "sync" and wa.state["status"] != "ready": return jsonify(error="WhatsApp is not connected, so there is nothing to back up."), 400
    wa.request_action(name); return jsonify(ok=True)


@bp.post("/api/wa/sync")
def wa_sync(): return _wa_action("sync")


@bp.post("/api/wa/reset")
def wa_reset(): return _wa_action("reset")
