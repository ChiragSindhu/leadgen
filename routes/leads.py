"""Leads: stats, filtered/sorted list, facets, bulk actions, import, detail, queue priority."""
import time
from flask import Blueprint, request, jsonify
import pipeline as P
import wa
from core import OUTREACH, busy_state, rows, clamp
from templating import render_tpl

bp = Blueprint("leads", __name__)

SORTS = {
    "score": "score DESC, first_seen DESC, id",
    "new": "first_seen DESC, id",
    "old": "first_seen ASC, id",
    "name": "LOWER(name) ASC, id",
    "rating": "rating DESC NULLS LAST, reviews DESC NULLS LAST, id",
    "reviews": "reviews DESC NULLS LAST, id",
    "contacted": "contacted_at DESC NULLS LAST, id",
}


def lead_filter(src):
    """Build a WHERE clause from query args or a plain dict. Every filter is optional.
    q, status (comma list), category, mobile, phone, website, email, ready (1),
    contacted (1 = contacted, 0 = not yet), min_score, min_rating."""
    def g(k):
        v = src.get(k)
        return "" if v is None else str(v).strip()
    w, a = ["dup_of IS NULL"], []
    if q := g("q"):
        w.append("(name ILIKE ? OR phone LIKE ? OR address ILIKE ? OR category ILIKE ?)"); a += [f"%{q}%"] * 4
    if s := g("status"):
        sts = [x for x in s.split(",") if x in OUTREACH]
        if sts: w.append("outreach = ANY(?)"); a.append(sts)
    if cat := g("category"): w.append("LOWER(category) = LOWER(?)"); a.append(cat)
    if g("mobile") == "1": w.append("is_mobile=1")
    if g("phone") == "1": w.append("phone IS NOT NULL")
    if g("website") == "1": w.append("website IS NOT NULL AND website != ''")
    if g("email") == "1": w.append("email IS NOT NULL AND email != ''")
    if g("ready") == "1": w.append(f"({P.SENDABLE})")
    if g("contacted") == "1": w.append("outreach != 'new'")
    elif g("contacted") == "0": w.append("outreach = 'new'")
    try:
        if ms := g("min_score"):
            if int(ms) > 0: w.append("score >= ?"); a.append(int(ms))
        if mr := g("min_rating"):
            if float(mr) > 0: w.append("rating >= ?"); a.append(float(mr))
    except ValueError: pass
    return " AND ".join(w), a


@bp.get("/api/stats")
def stats():
    c = P.db(); q = lambda s: c.execute(s).fetchone()[0]
    out = dict(total=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL"), ready=P.sendable_count(c),
               with_phone=q("SELECT COUNT(*) FROM leads WHERE dup_of IS NULL AND phone IS NOT NULL"),
               contacted=q("SELECT COUNT(*) FROM leads WHERE outreach!='new'"),
               warm=q("SELECT COUNT(*) FROM leads WHERE outreach IN ('replied','interested')"),
               sent_today=P.sent_today(c), limit=int(P.get_setting(c, "daily_limit")),
               wa=wa.state["status"], busy=busy_state())   # global status for every page
    c.close(); return jsonify(out)


@bp.get("/api/leads")
def leads():
    where, a = lead_filter(request.args)
    order = SORTS.get(request.args.get("sort"), SORTS["score"])
    lim = clamp(request.args.get("limit", 50, type=int), 1, 200); off = max(0, request.args.get("offset", 0, type=int))
    c = P.db()
    try:
        total = c.execute(f"SELECT COUNT(*) FROM leads WHERE {where}", a).fetchone()[0]
        items = [dict(x) for x in c.execute(
            f"SELECT id,name,category,phone,is_mobile,score,outreach FROM leads WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?", a + [lim, off])]
    finally: c.close()
    return jsonify(items=items, total=total)


@bp.get("/api/leads/facets")
def facets():
    """Distinct business types (with counts) for the category filter."""
    return jsonify(categories=rows("SELECT category AS name, COUNT(*) AS n FROM leads WHERE dup_of IS NULL AND category IS NOT NULL AND category != '' "
                                   "GROUP BY category ORDER BY COUNT(*) DESC, category LIMIT 100"))


@bp.get("/api/leads/phones")
def phones(): return jsonify([r["phone"] for r in rows("SELECT phone FROM leads WHERE dup_of IS NULL AND phone IS NOT NULL")])


@bp.post("/api/leads/bulk")
def bulk():
    b = request.json or {}; act = b.get("action")
    if act not in ("delete", "status"): return jsonify(error="Unknown action"), 400
    if act == "status" and b.get("outreach") not in OUTREACH: return jsonify(error="Unknown status"), 400
    c = P.db()
    try:
        if b.get("all"):
            where, a = lead_filter(b.get("filters") or {})
            ids = [r[0] for r in c.execute(f"SELECT id FROM leads WHERE {where} LIMIT 5001", a)]
        else: ids = [str(i) for i in (b.get("ids") or [])]
        if len(ids) > 5000: return jsonify(error="Too many leads at once (max 5000). Narrow the filter."), 400
        if not ids: return jsonify(ok=True, n=0)
        if act == "delete":
            c.execute("UPDATE leads SET dup_of=NULL WHERE dup_of = ANY(?)", (ids,))
            c.execute("DELETE FROM changes WHERE lead_id = ANY(?)", (ids,))
            n = c.execute("DELETE FROM leads WHERE id = ANY(?)", (ids,)).rowcount
        else:
            st = b["outreach"]
            n = c.execute("UPDATE leads SET contacted_at = CASE WHEN outreach='new' AND ? != 'new' THEN ? ELSE contacted_at END, outreach=? "
                          "WHERE id = ANY(?)", (st, P.now(), st, ids)).rowcount
        c.commit()
    finally: c.close()
    return jsonify(ok=True, n=n)


@bp.post("/api/leads")
def add():
    c = P.db()
    try: res = P.import_businesses(c, request.json)
    except ValueError as e: return jsonify(error=str(e)), 400
    finally: c.close()
    return jsonify(res)


@bp.patch("/api/leads/<path:lid>")
def patch(lid):
    c = P.db()
    try:
        r = c.execute("SELECT outreach,notes FROM leads WHERE id=?", (lid,)).fetchone()
        if not r: return jsonify(error="not found"), 404
        b = request.json or {}; P.set_outreach(c, lid, b.get("outreach", r["outreach"]), b.get("notes", r["notes"]))
        if "outreach" in b: c.execute("UPDATE leads SET priority=0 WHERE id=?", (lid,)); c.commit()
    finally: c.close()
    return jsonify(ok=True)


@bp.delete("/api/leads/<path:lid>")
def remove(lid):
    c = P.db(); P.delete_leads(c, [lid]); c.close(); return jsonify(ok=True)


@bp.post("/api/leads/<path:lid>/front")
def front(lid):
    c = P.db()
    try:
        if not c.execute(f"SELECT 1 FROM leads WHERE id=? AND {P.SENDABLE}", (lid,)).fetchone():
            return jsonify(error="This lead is not in the send queue (already contacted, no mobile number, or excluded)."), 409
        c.execute("UPDATE leads SET priority=? WHERE id=?", (int(time.time() * 1000), lid)); c.commit()
    finally: c.close()
    return jsonify(ok=True)


@bp.get("/api/leads/<path:lid>")
def detail(lid):
    c = P.db(); r = c.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    if not r: c.close(); return jsonify(error="not found"), 404
    d = {k: r[k] for k in r.keys() if k != "hash"}
    d["link"] = P.wa_link(d["phone"], render_tpl(P.get_setting(c, "template"), d)) if d["phone"] else None
    d["changes"] = [dict(x) for x in c.execute("SELECT at,field,old,new FROM changes WHERE lead_id=? ORDER BY id DESC LIMIT 20", (lid,))]
    c.close(); return jsonify(d)
