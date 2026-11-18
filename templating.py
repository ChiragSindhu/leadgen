"""Message template rendering ({name}, {type}, ...)."""
import re
import datetime as dt

VARS = lambda l: {"name": l.get("name"), "type": l.get("category"), "category": l.get("category"), "phone": l.get("phone"),
                  "address": l.get("address"), "rating": l.get("rating"), "reviews": l.get("reviews"), "website": l.get("website"),
                  "date": dt.date.today().strftime("%d %b")}


def render_tpl(tpl, lead):
    v = VARS(lead)
    return re.sub(r"\{(\w+)\}", lambda m: ("" if v[m[1]] is None else str(v[m[1]])) if m[1] in v else m[0], tpl or "")
