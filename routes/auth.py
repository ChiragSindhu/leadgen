"""Login, logout, the API guard and the index page."""
import os, secrets
from flask import Blueprint, request, jsonify, session, send_from_directory
from core import BASE

bp = Blueprint("auth", __name__)
PW = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(8)
if not os.getenv("ADMIN_PASSWORD"): print("ADMIN_PASSWORD not set. Temporary password:", PW)


@bp.before_app_request
def guard():
    if request.path.startswith("/api/") and request.path != "/api/login" and not session.get("ok"):
        return jsonify(error="login required"), 401


@bp.get("/")
def home():
    for d in (os.path.join(BASE, "static"), BASE):
        if os.path.exists(os.path.join(d, "index.html")): return send_from_directory(d, "index.html")
    return f"index.html not found. Put it in {os.path.join(BASE, 'static')} (folder named 'static' next to server.py).", 404


@bp.post("/api/login")
def login():
    if secrets.compare_digest((request.json or {}).get("password", ""), PW): session["ok"] = True; return jsonify(ok=True)
    return jsonify(error="Wrong password"), 403


@bp.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)
