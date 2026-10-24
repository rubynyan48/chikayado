"""楽天トラベルAPIで会場周辺の宿と、イベント開催日の空室・料金を取得する。

必要な環境変数: RAKUTEN_APP_ID, RAKUTEN_ACCESS_KEY
アフィリエイトIDは config/site.json の rakuten_affiliate_id に入れると、予約リンクが自動で切り替わる。
"""
import re
import sys
import unicodedata
from datetime import date, timedelta

from common import DATA, REFERER, SITE, distance_m, env, polite_get, read_json, venues, write_json

HOTEL_URL = "https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20260731"
VACANT_URL = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
VACANCY_DAYS_AHEAD = 180  # これより先の開催日は空室を調べない


def flatten_hotel(entry):
    """楽天の hotels 配列の1要素から、中の項目を1つの辞書にまとめる。"""
    merged = {}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, (dict, list)):
                    walk(v)
                else:
                    merged.setdefault(k, v)
            # roomInfo の中の料金は別で拾う
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(entry)
    return merged


def room_charges(entry):
    """空室検索の1施設分から、プランごとの1泊料金と予約URLを取り出す。"""
    plans = []

    def walk(x, current):
        if isinstance(x, dict):
            if "roomBasicInfo" in x:
                current = dict(current, **x["roomBasicInfo"])
            if "dailyCharge" in x:
                current = dict(current, **x["dailyCharge"])
                if current.get("total"):
                    plans.append(current)
                return
            for v in x.values():
                walk(v, current)
        elif isinstance(x, list):
            cur = current
            for v in x:
                if isinstance(v, dict) and "roomBasicInfo" in v:
                    cur = dict(current, **v["roomBasicInfo"])
                    continue
                walk(v, cur)

    walk(entry, {})
    return plans


# 楽天のデータに残っている古い駅名を今の駅名に直す
STATION_RENAMES = {"国際展示場正門": "東京ビッグサイト"}


def tidy(text):
    """全角英数字を半角にし、余分な空白を詰める。"""
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", s).strip()


def tidy_station(text):
    s = re.sub(r"[（(][^）)]*[）)]$", "", tidy(text))
    return STATION_RENAMES.get(s, s)


def base_params(venue):
    p = {
        "applicationId": env("RAKUTEN_APP_ID"),
        "accessKey": env("RAKUTEN_ACCESS_KEY"),
        "format": "json",
        "formatVersion": 2,
        "latitude": venue["lat"],
        "longitude": venue["lng"],
        "datumType": 1,
        "searchRadius": venue.get("search_radius_km", 3.0),
    }
    if SITE.get("rakuten_affiliate_id"):
        p["affiliateId"] = SITE["rakuten_affiliate_id"]
    return p


def headers():
    return {"Referer": REFERER, "Origin": REFERER.rstrip("/"), "accessKey": env("RAKUTEN_ACCESS_KEY") or ""}


def fetch_hotels(venue):
    hotels = {}
    page = 1
    while True:
        params = dict(base_params(venue), responseType="middle", hits=30, page=page)
        res = polite_get(HOTEL_URL, params, headers())
        if res is None:
            break
        body = res.json()
        for entry in body.get("hotels", []):
            h = flatten_hotel(entry)
            if not h.get("hotelNo") or h.get("latitude") in (None, ""):
                continue
            d = distance_m(venue["lat"], venue["lng"], float(h["latitude"]), float(h["longitude"]))
            if d > venue.get("search_radius_km", 3.0) * 1000:
                continue
            hotels[str(h["hotelNo"])] = {
                "hotelNo": str(h["hotelNo"]),
                "name": tidy(h.get("hotelName", "")),
                "distance_m": d,
                "lat": float(h["latitude"]),
                "lng": float(h["longitude"]),
                "address": tidy(f"{h.get('address1', '')}{h.get('address2', '')}"),
                "access": tidy(h.get("access", "")),
                "station": tidy_station(h.get("nearestStation", "")),
                "min_charge": h.get("hotelMinCharge"),
                "review_avg": h.get("reviewAverage"),
                "review_count": h.get("reviewCount"),
                "image": h.get("hotelImageUrl", ""),
                "info_url": h.get("hotelInformationUrl", ""),
                "plan_url": h.get("planListUrl", ""),
                "special": h.get("hotelSpecial", ""),
            }
        paging = body.get("pagingInfo", {})
        if page >= int(paging.get("pageCount", 1) or 1) or page >= 10:
            break
        page += 1
    result = sorted(hotels.values(), key=lambda h: h["distance_m"])
    write_json(DATA / "hotels" / f"{venue['slug']}.json",
               {"venue": venue["slug"], "updated": date.today().isoformat(), "hotels": result})
    print(f"{venue['name']}: 周辺の宿 {len(result)}件")
    return result


_vacancy_cache = {}


def fetch_vacancy(venue, event):
    checkin = date.fromisoformat(event["start"])
    key = (venue["slug"], checkin)
    if key in _vacancy_cache:
        write_json(DATA / "vacancy" / venue["slug"] / f"{event['slug']}.json", _vacancy_cache[key])
        return
    params = dict(base_params(venue), checkinDate=checkin.isoformat(),
                  checkoutDate=(checkin + timedelta(days=1)).isoformat(),
                  adultNum=1, hits=30, sort="+roomCharge", responseType="small")
    found = {}
    for page in (1, 2):
        params["page"] = page
        res = polite_get(VACANT_URL, params, headers())
        if res is None:
            break
        body = res.json()
        for entry in body.get("hotels", []):
            h = flatten_hotel(entry)
            plans = room_charges(entry)
            if not h.get("hotelNo") or not plans:
                continue
            cheapest = min(plans, key=lambda p: p["total"])
            found[str(h["hotelNo"])] = {
                "total": cheapest["total"],
                "plan": cheapest.get("planName", ""),
                "reserve_url": cheapest.get("reserveUrl", ""),
            }
        if page >= int(body.get("pagingInfo", {}).get("pageCount", 1) or 1):
            break
    result = {"checked": date.today().isoformat(), "checkin": checkin.isoformat(), "hotels": found}
    _vacancy_cache[key] = result
    write_json(DATA / "vacancy" / venue["slug"] / f"{event['slug']}.json", result)
    print(f"  {event['name']} {checkin}: 空室あり {len(found)}軒")


def main():
    if not env("RAKUTEN_APP_ID") or not env("RAKUTEN_ACCESS_KEY"):
        print("楽天のアプリIDかアクセスキーが未設定のため、宿の取得を飛ばします")
        return 0
    failed = False
    today = date.today()
    for venue in venues():
        try:
            fetch_hotels(venue)
        except Exception as exc:
            failed = True
            print(f"{venue['name']}: 宿の取得に失敗 {exc}", file=sys.stderr)
            continue
        events = read_json(DATA / "events" / f"{venue['slug']}.json", {"events": []})["events"]
        for event in events:
            start = date.fromisoformat(event["start"])
            if start < today or start > today + timedelta(days=VACANCY_DAYS_AHEAD):
                continue
            try:
                fetch_vacancy(venue, event)
            except Exception as exc:
                failed = True
                print(f"  {event['name']}: 空室の取得に失敗 {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
