"""一度だけの調べもの。楽天の空室検索を地域コードで呼べるか（詳細地区が要るか）を確かめる。"""
from datetime import date, timedelta
from fetch_hotels import VACANT_URL, base_params, headers, flatten_hotel, room_charges, REFERER
from common import env
import requests, time

d = date(2026, 11, 14)
for mid, small, det in [("osaka", "shi", ""), ("osaka", "shi", "B"), ("tokyo", "tokyo", ""), ("tokyo", "tokyo", "A"), ("kanagawa", "yokohama", ""), ("tiba", "chiba", "")]:
    p = {k: v for k, v in base_params({"lat": 0, "lng": 0}).items() if k not in ("latitude", "longitude", "datumType", "searchRadius")}
    p.update(largeClassCode="japan", middleClassCode=mid, smallClassCode=small, checkinDate=d.isoformat(),
             checkoutDate=(d + timedelta(days=1)).isoformat(), adultNum=1, roomNum=1, hits=30, sort="+roomCharge")
    if det:
        p["detailClassCode"] = det
    r = requests.get(VACANT_URL, params=p, headers=headers(), timeout=30)
    time.sleep(1.3)
    try:
        b = r.json()
    except Exception:
        print(mid, small, det, r.status_code, r.text[:200]); continue
    if "error" in b or "errors" in b:
        print(mid, small, det, r.status_code, b); continue
    hs = b.get("hotels", [])
    info = b.get("pagingInfo", {})
    first = flatten_hotel(hs[0]) if hs else {}
    print(mid, small, det, r.status_code, "件数", info.get("recordCount"), "先頭", first.get("hotelName"), min(x["total"] for x in room_charges(hs[0])) if hs else None, first.get("latitude"), first.get("longitude"))
