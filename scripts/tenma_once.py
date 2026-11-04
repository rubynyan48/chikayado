"""一度だけの調べもの。東京23区と大阪市の詳細地区コード（A〜Z）のうち、使えるものを確かめる。"""
from datetime import date, timedelta
from fetch_hotels import VACANT_URL, base_params, headers, flatten_hotel
import requests, time, string

p = {k: v for k, v in base_params({"lat": 0, "lng": 0}).items() if k in ("applicationId", "accessKey", "format", "formatVersion")}
d = date(2026, 11, 25)
for mid, small in (("tokyo", "tokyo"), ("osaka", "shi")):
    for c in string.ascii_uppercase:
        q = dict(p, largeClassCode="japan", middleClassCode=mid, smallClassCode=small, detailClassCode=c, datumType=1,
                 checkinDate=d.isoformat(), checkoutDate=(d + timedelta(days=1)).isoformat(), adultNum=1, roomNum=1, hits=1)
        r = requests.get(VACANT_URL, params=q, headers=headers(), timeout=30)
        time.sleep(1.2)
        if r.status_code == 200:
            b = r.json(); h = flatten_hotel(b["hotels"][0])
            print("CODE", mid, small, c, b["pagingInfo"].get("recordCount"), h.get("address1"), h.get("address2"), h.get("nearestStation"))
        elif r.status_code == 404:
            print("CODE", mid, small, c, "空きなし（コードは有効）")
