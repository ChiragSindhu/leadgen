"""Message templates (several, one active), daily limit and Google key usage."""
import os, re, json, uuid
from flask import Blueprint, request, jsonify
import pipeline as P
from core import clamp
from .media import media_list, pub

bp = Blueprint("settings", __name__)

MAX_TEMPLATES, MAX_BODY, MAX_NAME = 20, 1500, 40


def get_templates(c):
    """Returns (items, active_id). Older installs only have one 'template' setting, which becomes 'Default'."""
    try: items = json.loads(P.get_setting(c, "templates") or "[]")
    except Exception: items = []
    items = [t for t in items if isinstance(t, dict) and t.get("id") and t.get("body")]
    if not items: items = [{"id": "t1", "name": "Default", "body": P.get_setting(c, "template") or ""}]
    active = P.get_setting(c, "active_template")
    if active not in [t["id"] for t in items]: active = items[0]["id"]
    return items, active


def clean_templates(raw):
    out, seen = [], set()
    for t in (raw or [])[:MAX_TEMPLATES]:
        if not isinstance(t, dict): continue
        body = str(t.get("body") or "").strip()[:MAX_BODY]
        if not body: continue
        tid = re.sub(r"[^A-Za-z0-9_-]", "", str(t.get("id") or ""))[:30] or uuid.uuid4().hex[:8]
        while tid in seen: tid = uuid.uuid4().hex[:8]
        seen.add(tid)
        out.append({"id": tid, "name": str(t.get("name") or "").strip()[:MAX_NAME] or "Untitled", "body": body})
    return out


@bp.route("/api/settings", methods=["GET", "PUT"])
def settings():
    c = P.db()
    try:
        items, active = get_templates(c)
        if request.method == "PUT":
            b = request.json or {}
            if "templates" in b:
                items = clean_templates(b["templates"])
                if not items: return jsonify(error="Add at least one template with some text"), 400
            if b.get("active") in [t["id"] for t in items]: active = b["active"]
            elif active not in [t["id"] for t in items]: active = items[0]["id"]
            if "templates" in b or "active" in b:
                P.set_setting(c, "templates", json.dumps(items)); P.set_setting(c, "active_template", active)
                P.set_setting(c, "template", next(t["body"] for t in items if t["id"] == active))   # the sender reads this key
            if b.get("daily_limit"): P.set_setting(c, "daily_limit", clamp(int(b["daily_limit"]), 1, 9999))
        out = {k: P.get_setting(c, k) for k in ("daily_limit", "last_location")}
        out.update(templates=items, active_template=active, template=next(t["body"] for t in items if t["id"] == active),
                   has_google_key=bool(P.get_setting(c, "google_key") or os.getenv("GOOGLE_API_KEY")),
                   google_cap=int(P.get_setting(c, "google_cap") or 900), google_used=P.google_used(c))
        out["media"] = [pub(m) for m in media_list(c)]
        return jsonify(out)
    finally: c.close()
