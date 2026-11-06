"""一度だけの調べもの。名古屋市と福岡市の楽天の詳細地区コード（A〜Z）と、その地区の宿の住所・最寄り駅を確かめる。"""
from datetime import date, timedelta
from fetch_hotels import VACANT_URL, base_params, headers, flatten_hotel
import requests, time, string

p = {k: v for k, v in base_params({"lat": 0, "lng": 0}).items() if k in ("applicationId", "accessKey", "format", "formatVersion")}
d = date(2026, 11, 25)
for mid, small in (("aichi", "nagoya"), ("fukuoka", "fukuoka")):
    q = dict(p, largeClassCode="japan", middleClassCode=mid, smallClassCode=small, datumType=1,
             checkinDate=d.isoformat(), checkoutDate=(d + timedelta(days=1)).isoformat(), adultNum=1, roomNum=1, hits=1)
    r = requests.get(VACANT_URL, params=q, headers=headers(), timeout=30)
    print("CODE", mid, small, "詳細なし", r.status_code, r.text[:120] if r.status_code != 200 else r.json()["pagingInfo"].get("recordCount"))
    time.sleep(1.2)
    for c in string.ascii_uppercase[:12]:
        q["detailClassCode"] = c
        q["hits"] = 3
        r = requests.get(VACANT_URL, params=q, headers=headers(), timeout=30)
        time.sleep(1.2)
        if r.status_code == 200:
            b = r.json()
            hs = [flatten_hotel(h) for h in b["hotels"]]
            print("CODE", mid, small, c, b["pagingInfo"].get("recordCount"), " / ".join(f"{h.get('address2','')[:12]}({h.get('nearestStation')})" for h in hs))
