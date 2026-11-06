"""一度だけの調べもの。ポートメッセなごやの周りに宿が少ないので、港区・港北駅（旧 名古屋競馬場前）・聚楽園の周りの宿を探す。"""
import math
from fetch_hotels import base_params, headers, flatten_hotel
from common import polite_get

VENUE = (35.047825, 136.844147)  # ポートメッセなごや（設定の位置）
from fetch_hotels import HOTEL_URL
areas = [("港北駅の周り（旧 名古屋競馬場前）", 35.1225, 136.8720), ("名古屋港・築地口の周り", 35.0930, 136.8845),
         ("荒子川公園・稲永の周り", 35.1000, 136.8600), ("聚楽園駅の周り（東海市）", 35.0412, 136.9087)]
seen = {}
for label, la, lo in areas:
    p = dict(base_params({"lat": la, "lng": lo}), searchRadius=3.0, hits=30, datumType=1)
    p.pop("checkinDate", None)
    res = polite_get(HOTEL_URL, p, headers())
    hs = [flatten_hotel(h) for h in (res.json().get("hotels", []) if res is not None else [])]
    print(f"AREA {label}: {len(hs)}軒")
    for h in hs:
        if not h.get("latitude"): continue
        m = math.hypot((float(h["latitude"]) - VENUE[0]) * 111000, (float(h["longitude"]) - VENUE[1]) * 91000)
        seen.setdefault(h["hotelNo"], (round(m), h.get("hotelName"), h.get("address1", "") + h.get("address2", ""), h.get("nearestStation"), h.get("hotelMinCharge"), h.get("reviewAverage"), label))
rows = sorted(seen.values())
print("HOTELS 合計", len(rows))
for r in rows[:60]:
    print(f"HOTEL 直線{r[0]/1000:.1f}km {r[1]}｜{r[2]}｜最寄り {r[3]}｜最安 {r[4]}円｜評価 {r[5]}｜{r[6]}")
