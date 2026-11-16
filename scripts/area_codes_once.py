"""会場の周りの宿の楽天の地区コード（中・小・詳細）を数える一回きりの下調べ。"""
import collections, json, time
from common import DATA, venues
from fetch_hotels import HOTEL_URL, base_params, headers
from common import polite_get

def walk(x, out):
    if isinstance(x, dict):
        if "middleClassCode" in x or "smallClassCode" in x:
            out.append((x.get("middleClassCode"), x.get("smallClassCode"), x.get("detailClassCode") or ""))
        for v in x.values(): walk(v, out)
    elif isinstance(x, list):
        for v in x: walk(v, out)

res = {}
for v in venues():
    p = dict(base_params(dict(v, search_radius_km=1.5)), responseType="large", hits=20, page=1)
    r = polite_get(HOTEL_URL, p, headers())
    codes = []
    if r is not None:
        walk(r.json(), codes)
    res[v["slug"]] = collections.Counter("/".join(c) for c in codes).most_common(3)
    print(v["slug"], res[v["slug"]])
(DATA / "probe").mkdir(exist_ok=True)
json.dump(res, open(DATA / "probe" / "areas.json", "w"), ensure_ascii=False, indent=1)
