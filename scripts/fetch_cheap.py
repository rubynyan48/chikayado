"""会場から少し離れてもいいから安く泊まりたい人向けに、地域ごとの安い宿を楽天から取る。

会場の周り3kmの宿（fetch_hotels.py）とは別に、東京23区・大阪市・横浜市・千葉市を楽天の地区ごとに、
イベントの夜に大人1人で泊まれる宿を安い順に30軒ずつ取る。同じ地域の会場は同じデータを使う。
保存先は data/cheap/<地域>/<日付>.json。どの会場から近いかはページを作るとき（build.py）に計算する。
"""
import re
import sys
import time
from datetime import date, timedelta

from common import DATA, polite_get, read_json, venues, write_json
from fetch_hotels import VACANT_URL, base_params, flatten_hotel, headers, room_charges, tidy, tidy_station

# 楽天の地区コード。東京23区と大阪市は詳細地区まで指定しないと検索できない（11/4に確かめた）
REGIONS = {
    "tokyo": ("tokyo", "tokyo", list("ABCDEFGHI")),
    "osaka": ("osaka", "shi", list("ABCD")),
    "yokohama": ("kanagawa", "yokohama", [""]),
    "chiba": ("tiba", "chiba", [""]),
}
DAYS_AHEAD = 45  # サイトマップに載せるイベントと同じ範囲
TIME_LIMIT = 15 * 60  # 毎朝の更新全体が長くなりすぎないよう、15分で打ち切る（残りは翌日）
# 誰でも使えるわけではないプラン（年齢・会員・性別などの条件付きや連泊が前提）は、安くても外す。11/4に「80歳以上限定」の1円プランが出た
RESTRICTED = re.compile(r"歳以上|才以上|歳以下|限定.*身分証|身分証.*限定|会員限定|会員様限定|学生|女性限定|男性限定|レディース|カップル|ご夫婦|連泊|[2-9２-９]泊以上|シニア|誕生日|記念日")
MIN_PRICE = 1000
DORM = re.compile(r"ドミトリー|ドミ|相部屋|カプセル|キャビン|CABIN|Cabin|dormitory|Dormitory|ベッド1台|女性専用フロア.*ベッド")


def regions_of(venue):
    """会場の「少し離れた宿」の地域コードから、どの地域の安い宿を使うかを決める。"""
    codes = {(a["chu"], a["shou"]) for a in venue.get("far_areas", [])}
    return [k for k, (mid, small, _) in REGIONS.items() if (mid, small) in codes]


def stay_date(e, today):
    """イベントのページで宿を出す夜（開催中なら今日の夜、そうでなければ初日の夜）。"""
    return max(date.fromisoformat(e["start"]), today)


def fetch_day(region, d):
    mid, small, details = REGIONS[region]
    found = {}
    for det in details:
        p = {k: v for k, v in base_params({"lat": 0, "lng": 0}).items() if k not in ("latitude", "longitude", "searchRadius")}
        p.update(largeClassCode="japan", middleClassCode=mid, smallClassCode=small, datumType=1,
                 checkinDate=d.isoformat(), checkoutDate=(d + timedelta(days=1)).isoformat(),
                 adultNum=1, roomNum=1, hits=30, page=1, sort="+roomCharge")
        if det:
            p["detailClassCode"] = det
        res = polite_get(VACANT_URL, p, headers())
        if res is None:  # 空室なし（404）や通信の失敗
            continue
        for entry in res.json().get("hotels", []):
            h = flatten_hotel(entry)
            plans = [x for x in room_charges(entry)
                     if int(x["total"]) >= MIN_PRICE and not RESTRICTED.search(x.get("planName") or "")]
            if not h.get("hotelNo") or not plans or not h.get("latitude"):
                continue
            c = min(plans, key=lambda x: x["total"])
            room, plan = tidy(c.get("roomName", "")), tidy(c.get("planName", ""))
            found[str(h["hotelNo"])] = {
                "hotelNo": str(h["hotelNo"]), "name": tidy(h.get("hotelName", "")),
                "lat": float(h["latitude"]), "lng": float(h["longitude"]),
                "station": tidy_station(h.get("nearestStation") or ""), "review_avg": h.get("reviewAverage"),
                "image": h.get("hotelImageUrl", ""), "price": int(c["total"]), "room": room, "plan": plan,
                "dorm": bool(DORM.search(room + " " + plan)), "reserve_url": c.get("reserveUrl", ""),
            }
    return found


def main():
    today = date.today()
    want = {}
    for venue in venues():
        regions = regions_of(venue)
        for e in read_json(DATA / "events" / f"{venue['slug']}.json", {"events": []})["events"]:
            if e["end"] < today.isoformat() or e["start"] > (today + timedelta(days=DAYS_AHEAD)).isoformat():
                continue
            for r in regions:
                want.setdefault(r, set()).add(stay_date(e, today))
    failed = False
    for region in want:
        folder = DATA / "cheap" / region
        if folder.exists():  # 過ぎた日付は消す
            for f in folder.glob("*.json"):
                if f.stem < today.isoformat():
                    f.unlink()
    started, done, skipped = time.time(), 0, 0
    # 地域をまたいで近い日付から取る（打ち切ったときに、近い日付が古いまま残らないように）
    for d, region in sorted((d, r) for r, ds in want.items() for d in ds):
        path = DATA / "cheap" / region / f"{d.isoformat()}.json"
        old = read_json(path)
        # 近い日付は毎日、3週間より先は3日おきに取り直す（楽天への問い合わせを減らすため）
        if old and (today - date.fromisoformat(old["checked"])).days < (1 if (d - today).days <= 21 else 3):
            continue
        if time.time() - started > TIME_LIMIT:
            skipped += 1
            continue
        try:
            hotels = fetch_day(region, d)
        except Exception as exc:
            failed = True
            print(f"{region} {d}: 取得に失敗 {exc}", file=sys.stderr)
            continue
        write_json(path, {"checked": today.isoformat(), "checkin": d.isoformat(),
                          "hotels": sorted(hotels.values(), key=lambda h: h["price"])})
        done += 1
        cheapest = min((h["price"] for h in hotels.values() if not h["dorm"]), default=None)
        print(f"{region} {d}: 空き{len(hotels)}軒 個室の最安 {cheapest}")
    print(f"取り直し {done}件" + (f"、時間切れで明日に回した分 {skipped}件" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
