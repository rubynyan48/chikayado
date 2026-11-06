"""一度だけの調べもの。楽天の地区一覧から、愛知県と福岡県の小地区・詳細地区のコードと名前を出す。"""
from fetch_hotels import base_params, headers
import requests, json

p = {k: v for k, v in base_params({"lat": 0, "lng": 0}).items() if k in ("applicationId", "accessKey", "format")}
for ver in ("20131024",):
    r = requests.get(f"https://openapi.rakuten.co.jp/engine/api/Travel/GetAreaClass/{ver}", params=p, headers=headers(), timeout=60)
    print("AREA", ver, r.status_code, r.text[:300] if r.status_code != 200 else "ok")
    if r.status_code != 200:
        continue
    b = r.json()
    def walk(x, mid=None, small=None):
        if isinstance(x, dict):
            if "middleClassCode" in x: mid = x["middleClassCode"]
            if "smallClassCode" in x:
                small = x["smallClassCode"]
                if mid in ("aichi", "fukuoka"): print("AREA SMALL", mid, small, x.get("smallClassName"))
            if "detailClassCode" in x and mid in ("aichi", "fukuoka"):
                print("AREA DETAIL", mid, small, x["detailClassCode"], x.get("detailClassName"))
            for v in x.values(): walk(v, mid, small)
        elif isinstance(x, list):
            for v in x: walk(v, mid, small)
    walk(b)
