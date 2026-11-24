"""共通テストの試験場の設定（config/exams/*.json）に、緯度経度がなければ足す（11/24〜）。

試験場の住所は国土地理院の地名検索で、駅は HeartRails Express の駅検索で調べる。
新しい試験場を足したときに1回だけ動かせばよい（毎朝の更新では動かさない）。
"""
import json
import sys

import requests

from common import CONFIG, distance_m

GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch"
STATION = "https://express.heartrails.com/api/json"


def geocode(address):
    res = requests.get(GSI, params={"q": address}, timeout=20)
    res.raise_for_status()
    found = res.json()
    if not found:
        return None
    lng, lat = found[0]["geometry"]["coordinates"]
    return round(lat, 6), round(lng, 6)


def station(name, near):
    res = requests.get(STATION, params={"method": "getStations", "name": name.removesuffix("駅")}, timeout=20)
    res.raise_for_status()
    found = res.json().get("response", {}).get("station", [])
    if not found:
        return None
    # 同じ名前の駅がほかの県にもあるので、試験場にいちばん近いものを選ぶ
    best = min(found, key=lambda s: distance_m(near[0], near[1], float(s["y"]), float(s["x"])))
    return round(float(best["y"]), 6), round(float(best["x"]), 6)


def main():
    for path in sorted((CONFIG / "exams").glob("*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        if not cfg.get("lat"):
            got = geocode(cfg["address"])
            if not got:
                print(f"{cfg['name']}: 住所から場所がわかりませんでした", file=sys.stderr)
                continue
            cfg["lat"], cfg["lng"] = got
            changed = True
        # 試験場の周りに宿が少ないときに宿を足す、宿の多い駅（town）。会場の extra_areas と同じ形にする
        town = cfg.get("town")
        if town and not cfg.get("extra_areas"):
            got = station(town["name"], (cfg["lat"], cfg["lng"]))
            if got:
                cfg["extra_areas"] = [{"name": town["name"], "lat": got[0], "lng": got[1], "radius_km": town.get("radius_km", 1.2)}]
                changed = True
            else:
                print(f"{cfg['name']}: {town['name']}の場所がわかりませんでした", file=sys.stderr)
        for s in cfg.get("stations", []):
            if not s.get("lat"):
                got = station(s["name"], (cfg["lat"], cfg["lng"]))
                if got:
                    s["lat"], s["lng"] = got
                    changed = True
                else:
                    print(f"{cfg['name']}: {s['name']}の場所がわかりませんでした", file=sys.stderr)
        if changed:
            path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{cfg['name']}: {cfg['lat']}, {cfg['lng']}")


if __name__ == "__main__":
    main()
