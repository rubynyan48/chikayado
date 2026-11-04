"""一度だけの調べもの。11/14（土）に大人1人1泊で、JR天満駅から1km以内の宿を安い順に出す。"""
import math
from datetime import date, timedelta
from fetch_hotels import VACANT_URL, base_params, headers, flatten_hotel, room_charges
from common import polite_get

LAT, LNG = 34.7048, 135.5124  # JR天満駅
d = date(2026, 11, 14)
p = dict(base_params({"lat": LAT, "lng": LNG}), searchRadius=1.0, checkinDate=d.isoformat(),
         checkoutDate=(d + timedelta(days=1)).isoformat(), adultNum=1, roomNum=1, hits=30, sort="+roomCharge")
rows = []
for page in (1, 2, 3):
    p["page"] = page
    res = polite_get(VACANT_URL, p, headers())
    if res is None:
        break
    body = res.json()
    for entry in body.get("hotels", []):
        h, plans = flatten_hotel(entry), room_charges(entry)
        if not plans:
            continue
        c = min(plans, key=lambda x: x["total"])
        m = round(math.hypot((float(h.get("latitude", LAT)) - LAT) * 111000, (float(h.get("longitude", LNG)) - LNG) * 91000))
        rows.append((c["total"], m, h.get("hotelName"), h.get("nearestStation"), c.get("roomName", ""), c.get("planName", ""), h.get("reviewAverage")))
    if page >= int(body.get("pagingInfo", {}).get("pageCount", 1) or 1):
        break
rows.sort()
print("空きのある宿", len(rows))
for r in rows[:25]:
    print(f"{r[0]:>7,}円 天満駅から約{r[1]}m {r[2]}（最寄り {r[3]}・評価 {r[6]}）部屋 {r[4]} プラン {r[5]}")
