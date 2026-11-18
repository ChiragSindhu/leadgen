"""Media library: upload, toggle, delete, serve."""
import uuid
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
import pipeline as P
import sbstore
from sbstore import local_media

bp = Blueprint("media", __name__)

MEDIA_MAX = {"image": 5 << 20, "video": 16 << 20}
MAX_FILES, MAX_TOTAL = 10, 100 << 20


def sniff(b):
    if b[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    if b[4:8] == b"ftyp": return "video/3gpp" if b[8:11] == b"3gp" else "video/mp4"


def media_list(c, only_on=False):
    return [dict(r) for r in c.execute("SELECT id,path,type,name,size,enabled FROM media " + ("WHERE enabled=1 " if only_on else "") + "ORDER BY at, id")]


pub = lambda m: dict(id=m["id"], name=m["name"], type=m["type"], size=m["size"] or 0, on=bool(m["enabled"]))


@bp.errorhandler(413)
def too_big(e): return jsonify(error="File is too large (max 16 MB)"), 413


@bp.get("/api/media")
def media_all():
    c = P.db()
    try: return jsonify([pub(m) for m in media_list(c)])
    finally: c.close()


@bp.post("/api/media")
def media_up():
    if not sbstore.configured(): return jsonify(error="Storage is not configured on the server"), 503
    f = request.files.get("file"); data = f.read() if f else b""
    if not data: return jsonify(error="Choose a file"), 400
    kind = sniff(data[:16])
    if kind not in sbstore.MEDIA_EXT: return jsonify(error="Only JPG, PNG, WebP images and MP4 or 3GP videos are allowed"), 400
    cap = MEDIA_MAX[kind.split("/")[0]]
    if len(data) > cap: return jsonify(error=f"{kind.split('/')[0].title()} files must be under {cap >> 20} MB"), 400
    c = P.db()
    try:
        cur = media_list(c)
        if len(cur) >= MAX_FILES: return jsonify(error=f"You can keep up to {MAX_FILES} files. Delete one first."), 400
        if sum(m["size"] or 0 for m in cur) + len(data) > MAX_TOTAL: return jsonify(error="Library is full (100 MB total)"), 400
        mid = uuid.uuid4().hex; path = f"{mid}.{sbstore.MEDIA_EXT[kind]}"
        try: sbstore.upload(path, data, kind)
        except Exception: return jsonify(error="Upload to storage failed. Check the bucket name and key."), 502
        name = secure_filename(f.filename or path)[:80] or path
        c.execute("INSERT INTO media(id,path,type,name,size,enabled,at) VALUES(?,?,?,?,?,1,?)", (mid, path, kind, name, len(data), P.now())); c.commit()
        return jsonify(pub(dict(id=mid, name=name, type=kind, size=len(data), enabled=1)))
    finally: c.close()


@bp.patch("/api/media/<mid>")
def media_toggle(mid):
    on = bool((request.json or {}).get("on"))
    c = P.db()
    try: c.execute("UPDATE media SET enabled=? WHERE id=?", (1 if on else 0, mid)); c.commit()
    finally: c.close()
    return jsonify(ok=True, id=mid, on=on)          # echo the saved state so the UI can reconcile


@bp.delete("/api/media/<mid>")
def media_rm(mid):
    c = P.db()
    try:
        r = c.execute("SELECT path FROM media WHERE id=?", (mid,)).fetchone()
        c.execute("DELETE FROM media WHERE id=?", (mid,)); c.commit()
    finally: c.close()
    if r: sbstore.delete(r["path"]); sbstore.purge_cache(mid)
    return jsonify(ok=True)


@bp.get("/api/media/<mid>/file")
def media_file(mid):
    c = P.db()
    try: m = next((x for x in media_list(c) if x["id"] == mid), None)
    finally: c.close()
    if not m: return jsonify(error="not found"), 404
    return send_file(local_media(m), mimetype=m["type"], conditional=True)
