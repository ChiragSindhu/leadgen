"""OpenStreetMap (Overpass) source. Standalone: no database, no env, no module-level mutable state.
    from osm_source import fetch_osm
    res = fetch_osm("gym", 12.97, 77.64, 3000)      # -> OSMResult(rows, mirror, raw, unnamed)
CLI: python osm_source.py gym 12.97 77.64 3000"""
import re, sys, time, json
from dataclasses import dataclass, field
import requests

UA = {"User-Agent": "leadpipe/1.2 (personal lead tool)"}

class OSMUnavailable(RuntimeError):
    """Every Overpass mirror failed. This is an outage, NOT 'zero results'."""

@dataclass
class OSMResult:
    rows: list = field(default_factory=list)
    mirror: str = ""
    raw: int = 0          # elements returned by Overpass
    unnamed: int = 0      # dropped because they had no name

OSM_TAGS = {
    "real estate": ['["office"~"^(estate_agent|real_estate)$"]', '["shop"="estate_agent"]', '["office"="property_management"]'],
    "pg": ['["tourism"~"^(hostel|guest_house)$"]', '["amenity"="boarding_house"]', '["building"="dormitory"]',
           '["name"~"(^|[^A-Za-z])(PG|paying guest)([^A-Za-z]|$)",i]'],
    "hostel": ['["tourism"="hostel"]'], "gym": ['["leisure"="fitness_centre"]'],
    "clinic": ['["amenity"~"^(clinic|doctors|dentist)$"]'], "salon": ['["shop"~"^(hairdresser|beauty)$"]'],
    "restaurant": ['["amenity"="restaurant"]'], "school": ['["amenity"="school"]'],
    "cafe": ['["amenity"="cafe"]'], "pharmacy": ['["amenity"="pharmacy"]'], "coaching": ['["amenity"~"^(college|training)$"]']}
OSM_ALIASES = {"real estate agent": "real estate", "estate agent": "real estate", "property": "real estate", "realtor": "real estate",
               "property dealer": "real estate", "paying guest": "pg", "fitness": "gym", "doctor": "clinic", "beauty parlour": "salon"}
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter", "https://overpass.openstreetmap.fr/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]

def osm_selectors(category):
    k = category.lower().strip(); k = OSM_ALIASES.get(k, k)
    if k in OSM_TAGS: return OSM_TAGS[k]
    m = re.fullmatch(r"([\w:]+)=([\w:|]+)", category.strip())      # raw tag, e.g. shop=bakery or shop=a|b
    if m: return [f'["{m[1]}"~"^({m[2]})$"]' if "|" in m[2] else f'["{m[1]}"="{m[2]}"]']
    for key in OSM_TAGS:
        if len(key) > 3 and key in k: return OSM_TAGS[key]
    return None

def build_query(sels, lat, lng, radius_m):
    around = f"(around:{int(radius_m)},{lat},{lng})"
    return "[out:json][timeout:60];(" + "".join(f"nwr{s}{around};" for s in sels) + ");out center tags;"

def parse_elements(els, category):
    out, unnamed = [], 0
    for e in els:
        t = e.get("tags", {}); c = e.get("center", e)
        if not (t.get("name") or "").strip(): unnamed += 1; continue
        out.append(dict(id=f"o:{e['type']}{e['id']}", source="osm", name=t["name"], category=category,
            address=t.get("addr:full") or " ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:city")])) or None,
            lat=c.get("lat"), lng=c.get("lon"), phone=t.get("phone") or t.get("contact:phone") or t.get("contact:mobile"),
            website=t.get("website") or t.get("contact:website"), email=t.get("email") or t.get("contact:email"),
            maps_url=f"https://www.openstreetmap.org/{e['type']}/{e['id']}", status="active"))
    return out, unnamed

def fetch_osm(category, lat, lng, radius_m, mirrors=None, timeout=90):
    sels = osm_selectors(category)
    if not sels: raise RuntimeError(f"OSM: unknown category '{category}'. Use one of {list(OSM_TAGS)} or key=value (e.g. shop=bakery)")
    q = build_query(sels, lat, lng, radius_m); mirrors = mirrors or OVERPASS
    els, last, host = None, "", ""
    for url in mirrors:
        host = url.split("/")[2]
        for attempt in range(2):
            try:
                resp = requests.post(url, data={"data": q}, headers=UA, timeout=timeout)
                js = resp.json() if resp.status_code == 200 else {}
                if resp.status_code == 200 and "elements" in js and not (js.get("remark", "").lower().startswith("runtime error") and not js["elements"]):
                    els = js["elements"]; break
                last = f"{host}: HTTP {resp.status_code} {(js.get('remark') or resp.text)[:120]!r}"
            except Exception as e: last = f"{host}: {type(e).__name__}: {str(e)[:120]}"
            time.sleep(2 * (attempt + 1))
        if els is not None: break
    if els is None: raise OSMUnavailable(f"All {len(mirrors)} Overpass servers failed. Last error -> {last}")
    rows, unnamed = parse_elements(els, category)
    return OSMResult(rows=rows, mirror=host, raw=len(els), unnamed=unnamed)

if __name__ == "__main__":
    if len(sys.argv) != 5: sys.exit(__doc__)
    r = fetch_osm(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
    print(f"{r.mirror}: {r.raw} elements, {len(r.rows)} named, {r.unnamed} unnamed"); print(json.dumps(r.rows[:5], indent=2))
