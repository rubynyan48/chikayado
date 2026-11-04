"""一度だけの調べもの。東京23区と大阪市の詳細地区コードを楽天から取る。緯度経度を度で返すかも確かめる。"""
from datetime import date, timedelta
from fetch_hotels import VACANT_URL, base_params, headers, flatten_hotel
import requests, time, json

p = {k: v for k, v in base_params({"lat": 0, "lng": 0}).items() if k in ("applicationId", "accessKey", "format", "formatVersion")}
r = requests.get("https://openapi.rakuten.co.jp/engine/api/Travel/GetAreaClass/20131024", params=p, headers=headers(), timeout=30)
print("GetAreaClass", r.status_code)
s = r.text
b = r.json()
def walk(x, path):
    if isinstance(x, dict):
        code = x.get("middleClassCode") or x.get("smallClassCode") or x.get("detailClassCode")
        for k, v in x.items():
            walk(v, path + [k])
        if "detailClassCode" in x:
            print("DETAIL", "/".join(path[-6:-1]), x["detailClassCode"], x.get("detailClassName"))
    elif isinstance(x, list):
        for v in x:
            walk(v, path)
# 東京と大阪の部分だけ出す
for mid in ("tokyo", "osaka"):
    i = s.find('"middleClassCode":"%s"' % mid)
    print(mid, "位置", i)
txt = json.dumps(b, ensure_ascii=False)
import re
for mid, small in (("tokyo", "tokyo"), ("osaka", "shi")):
    m = re.search(r'"smallClassCode": "%s", "smallClassName": "([^"]*)"' % small, txt)
    print(mid, small, m.group(1) if m else None)
# 詳細地区は「smallClassCode の直後の detailClasses」に入っている。構造をたどって拾う
def find_small(x, mid_code=None):
    if isinstance(x, dict):
        mc = mid_code
        if "middleClassCode" in x: mc = x["middleClassCode"]
        if x.get("smallClassCode") in ("tokyo", "shi") and mc in ("tokyo", "osaka"):
            yield mc, x
        for v in x.values():
            yield from find_small(v, mc)
    elif isinstance(x, list):
        for v in x:
            yield from find_small(v, mid_code)
for mc, x in find_small(b):
    print("SMALL", mc, x.get("smallClassCode"), x.get("smallClassName"), list(x.keys()))
def details(x):
    if isinstance(x, dict):
        if "detailClassCode" in x: yield x["detailClassCode"], x.get("detailClassName")
        for v in x.values(): yield from details(v)
    elif isinstance(x, list):
        for v in x: yield from details(v)
# small の兄弟に detailClasses が並ぶ形にも備え、tokyo/shi を含む塊を全体から探して出す
def blocks(x, mc=None):
    if isinstance(x, list):
        for i, v in enumerate(x):
            if isinstance(v, dict) and v.get("smallClass"):
                pass
            yield from blocks(v, mc)
    elif isinstance(x, dict):
        if "middleClassCode" in x: mc = x["middleClassCode"]
        for k, v in x.items():
            if k == "smallClass" and isinstance(v, list):
                sc = next((y.get("smallClassCode") for y in v if isinstance(y, dict) and "smallClassCode" in y), None)
                if mc in ("tokyo", "osaka") and sc in ("tokyo", "shi"):
                    print("BLOCK", mc, sc, list(details(v)))
            yield from blocks(v, mc)
list(blocks(b))
time.sleep(1.3)
d = date(2026, 11, 14)
q = dict(p, largeClassCode="japan", middleClassCode="osaka", smallClassCode="shi", detailClassCode="B", datumType=1,
         checkinDate=d.isoformat(), checkoutDate=(d + timedelta(days=1)).isoformat(), adultNum=1, roomNum=1, hits=3, sort="+roomCharge")
r = requests.get(VACANT_URL, params=q, headers=headers(), timeout=30)
h = flatten_hotel(r.json()["hotels"][0])
print("DATUM1", h.get("hotelName"), h.get("latitude"), h.get("longitude"), h.get("nearestStation"))
