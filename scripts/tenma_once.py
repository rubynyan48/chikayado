"""一度だけの調べもの。11/14（土）に大人1人1泊で、JR天満駅から直線2〜4km（歩いて30〜60分）の宿を安い順に出す。"""
import math
from datetime import date, timedelta
from fetch_hotels import VACANT_URL, base_params, headers, flatten_hotel, room_charges
from common import polite_get

LAT, LNG = 34.7048, 135.5124  # JR天満駅
d = date(2026, 11, 14)
# 天満駅と、そこから3km離れた8方向の点を中心に、半径3kmずつ調べて合わせる
centers = [(LAT, LNG)] + [(LAT + 3000 * math.cos(math.radians(a)) / 111000, LNG + 3000 * math.sin(math.radians(a)) / 91000) for a in range(0, 360, 45)]
best = {}
for la, lo in centers:
    p = dict(base_params({"lat": la, "lng": lo}), searchRadius=3.0, checkinDate=d.isoformat(),
             checkoutDate=(d + timedelta(days=1)).isoformat(), adultNum=1, roomNum=1, hits=30, sort="+roomCharge")
    for page in (1, 2):
        p["page"] = page
        res = polite_get(VACANT_URL, p, headers())
        if res is None:
            break
        body = res.json()
        for entry in body.get("hotels", []):
            h, plans = flatten_hotel(entry), room_charges(entry)
            if not plans or not h.get("latitude"):
                continue
            m = math.hypot((float(h["latitude"]) - LAT) * 111000, (float(h["longitude"]) - LNG) * 91000)
            if not 2000 <= m <= 4000:
                continue
            c = min(plans, key=lambda x: x["total"])
            k = h.get("hotelNo")
            if k not in best or c["total"] < best[k][0]:
                best[k] = (c["total"], round(m), h.get("hotelName"), h.get("nearestStation"), c.get("roomName", ""), h.get("reviewAverage"))
        if page >= int(body.get("pagingInfo", {}).get("pageCount", 1) or 1):
            break
rows = sorted(best.values())
print("直線2〜4kmで空きのある宿（安い順に見つかった分）", len(rows))
for r in rows[:30]:
    print(f"{r[0]:>7,}円 直線{r[1]}m 歩いて約{round(r[1] * 1.2 / 80)}分 {r[2]}（最寄り {r[3]}・評価 {r[5]}）部屋 {r[4]}")
