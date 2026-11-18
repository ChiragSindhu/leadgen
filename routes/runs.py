"""Run history (searches and WhatsApp sends) and their event logs."""
from flask import Blueprint, request, jsonify
import pipeline as P
from core import rows, clamp

bp = Blueprint("runs", __name__)


@bp.get("/api/runs")
def runs():
    lim = clamp(request.args.get("limit", 30, type=int), 1, 100); off = max(0, request.args.get("offset", 0, type=int))
    c = P.db()
    try: total = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally: c.close()
    return jsonify(items=rows("SELECT id,at,query,source,fetched,added,changed,calls,location,status,finished_at,requested,error,no_contact "
                              "FROM runs ORDER BY id DESC LIMIT ? OFFSET ?", lim, off), total=total)


@bp.get("/api/runs/<int:rid>")
def run_detail(rid):
    r = rows("SELECT * FROM runs WHERE id=?", rid)
    if not r: return jsonify(error="not found"), 404
    return jsonify(run=r[0], events=rows("SELECT * FROM (SELECT id,at,kind,text FROM run_events WHERE run_id=? ORDER BY id DESC LIMIT 300) ORDER BY id", rid))
