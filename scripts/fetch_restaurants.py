"""ホットペッパーグルメAPIで、会場に近い宿の周りの飲食店を取得する。

必要な環境変数: HOTPEPPER_API_KEY（未設定なら何もしない）
宿のページの「食事はどうするか」の欄に使う。
"""
import sys
from datetime import date

from common import DATA, distance_m, env, polite_get, read_json, venues, write_json

URL = "https://webservice.recruit.co.jp/hotpepper/gourmet/v1/"
HOTELS_PER_VENUE = 12  # 会場に近い順にこの数の宿を調べる
RANGE = 2  # 2は半径500m


def fetch_around(lat, lng):
    params = {"key": env("HOTPEPPER_API_KEY"), "lat": lat, "lng": lng, "range": RANGE,
              "order": 4, "count": 20, "format": "json"}
    res = polite_get(URL, params, min_interval=0.5)
    if res is None:
        return []
    shops = res.json().get("results", {}).get("shop", [])
    out = []
    for s in shops:
        try:
            d = distance_m(lat, lng, float(s["lat"]), float(s["lng"]))
        except (KeyError, ValueError, TypeError):
            continue
        out.append({
            "id": s.get("id"),
            "name": s.get("name", ""),
            "genre": (s.get("genre") or {}).get("name", ""),
            "budget": (s.get("budget") or {}).get("name", ""),
            "open": s.get("open", ""),
            "access": s.get("mobile_access") or s.get("access", ""),
            "url": (s.get("urls") or {}).get("pc", ""),
            "photo": ((s.get("photo") or {}).get("pc") or {}).get("l", ""),
            "distance_m": d,
        })
    return sorted(out, key=lambda x: x["distance_m"])


def main():
    if not env("HOTPEPPER_API_KEY"):
        print("ホットペッパーのキーが未設定のため、飲食店の取得を飛ばします")
        return 0
    failed = False
    for venue in venues():
        hotels = read_json(DATA / "hotels" / f"{venue['slug']}.json", {"hotels": []})["hotels"]
        result = {}
        for h in hotels[:HOTELS_PER_VENUE]:
            try:
                result[h["hotelNo"]] = fetch_around(h["lat"], h["lng"])
            except Exception as exc:
                failed = True
                print(f"  {h['name']}: 飲食店の取得に失敗 {exc}", file=sys.stderr)
        write_json(DATA / "restaurants" / f"{venue['slug']}.json",
                   {"updated": date.today().isoformat(), "by_hotel": result})
        print(f"{venue['name']}: {len(result)}軒の宿の周りの飲食店を取得")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
