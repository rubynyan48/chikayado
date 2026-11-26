"""新しい会場の設定（config/venues/会場.json）に、緯度経度と駅の場所と、宿を足す駅（town → extra_areas）を入れる（11/26〜）。

使い方: python geocode_venues.py 会場のslug ...
楽天の地区（far_areas に使う）も、会場の県の分を画面に出す。新しい会場を足したときだけ動かす。
"""
import json
import sys

import requests

from common import CONFIG, env
from fetch_hotels import headers
from geocode_exams import geocode, station

AREA_URLS = ["https://openapi.rakuten.co.jp/engine/api/Travel/GetAreaClass/20131024",
             "https://app.rakuten.co.jp/services/api/Travel/GetAreaClass/20131024"]
PREF = {"東京都": "tokyo", "埼玉県": "saitama", "愛知県": "aichi"}


def areas(pref_code):
    for url in AREA_URLS:
        try:
            r = requests.get(url, params={"applicationId": env("RAKUTEN_APP_ID"), "accessKey": env("RAKUTEN_ACCESS_KEY"),
                                          "format": "json", "formatVersion": 2}, headers=headers(), timeout=30)
        except Exception as exc:
            print("地区の取得に失敗", type(exc).__name__)
            continue
        if r.status_code != 200:
            print("地区の取得に失敗", r.status_code, r.text[:200])
            continue
        data = r.json()
        for large in data["areaClasses"]["largeClasses"]:
            for mid in large[1]["middleClasses"] if isinstance(large, list) else large["largeClass"][1]["middleClasses"]:
                m = mid["middleClass"] if "middleClass" in mid else mid
                info = m[0] if isinstance(m, list) else m
                if info.get("middleClassCode") != pref_code:
                    continue
                for sm in (m[1]["smallClasses"] if isinstance(m, list) else []):
                    s = sm["smallClass"] if "smallClass" in sm else sm
                    sinfo = s[0] if isinstance(s, list) else s
                    details = []
                    if isinstance(s, list) and len(s) > 1:
                        for d in s[1].get("detailClasses", []):
                            dd = d["detailClass"] if "detailClass" in d else d
                            details.append(f"{dd['detailClassCode']}={dd['detailClassName']}")
                    print("楽天の地区", pref_code, sinfo["smallClassCode"], sinfo["smallClassName"], " ".join(details))
        return


def main():
    seen = set()
    for slug in sys.argv[1:]:
        path = CONFIG / "venues" / f"{slug}.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if not cfg.get("lat"):
            got = geocode(cfg["address"])
            if got:
                cfg["lat"], cfg["lng"] = got
        for s in cfg.get("stations", []):
            if not s.get("lat"):
                got = station(s["name"], (cfg["lat"], cfg["lng"]))
                if got:
                    s["lat"], s["lng"] = got
        if cfg.get("town") and not cfg.get("extra_areas"):
            cfg["extra_areas"] = []
            for t in cfg["town"]:
                got = station(t["name"], (cfg["lat"], cfg["lng"]))
                if got:
                    cfg["extra_areas"].append({"name": t["name"].removesuffix("駅"), "lat": got[0], "lng": got[1], "radius_km": t["radius_km"]})
            del cfg["town"]
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(cfg["name"], cfg["lat"], cfg["lng"], [(s["name"], s.get("lat")) for s in cfg["stations"]], cfg.get("extra_areas"))
        pref = next((v for k, v in PREF.items() if cfg["address"].startswith(k)), None)
        if pref and pref not in seen:
            seen.add(pref)
            areas(pref)


if __name__ == "__main__":
    main()
