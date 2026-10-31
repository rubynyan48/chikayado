"""楽天トラベルAPIで会場周辺の宿と、イベント開催日の空室・料金を取得する。

必要な環境変数: RAKUTEN_APP_ID, RAKUTEN_ACCESS_KEY
アフィリエイトIDは config/site.json の rakuten_affiliate_id に入れると、予約リンクが自動で切り替わる。
"""
import re
import sys
import unicodedata
from datetime import date, timedelta

from common import DATA, REFERER, SITE, clinics, distance_m, env, polite_get, read_json, venues, write_json

HOTEL_URL = "https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20260731"
VACANT_URL = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
VACANCY_DAYS_AHEAD = 120  # これより先の開催日は空室を調べない


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


def collect_texts(entry, keys):
    """指定した項目の中にある文字を、入れ子をたどってすべて集める。"""
    out = []

    def walk(x, inside):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, inside or k in keys)
        elif isinstance(x, list):
            for v in x:
                walk(v, inside)
        elif inside and isinstance(x, str) and x.strip():
            out.append(tidy(x))

    walk(entry, False)
    return out


SMOKE_OK = re.compile(r"喫煙(ルーム|室|所|可|スペース|ブース|コーナー|できる)")
NO_SMOKE_ALL = re.compile(r"(全館|全室|館内全面|全面)禁煙")


def smoking_status(texts):
    joined = " ".join(texts)
    if NO_SMOKE_ALL.search(joined):
        return "全館禁煙"
    if SMOKE_OK.search(joined):
        return "喫煙できる場所あり"
    return ""


def squeeze_ids(venue, condition):
    """条件（大浴場・温泉・禁煙ルーム）に合う宿の番号を集める。"""
    ids, page = set(), 1
    while True:
        params = dict(base_params(venue), responseType="small", hits=30, page=page, squeezeCondition=condition)
        res = polite_get(HOTEL_URL, params, headers())
        if res is None:
            break
        body = res.json()
        for entry in body.get("hotels", []):
            no = flatten_hotel(entry).get("hotelNo")
            if no:
                ids.add(str(no))
        if page >= int(body.get("pagingInfo", {}).get("pageCount", 1) or 1) or page >= 10:
            break
        page += 1
    return ids


def fetch_hotels(venue):
    hotels = {}
    page = 1
    while True:
        params = dict(base_params(venue), responseType="large", hits=30, page=page)
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
                "special": tidy(h.get("hotelSpecial", "")),
                "ratings": {k: h.get(f"{k}Average") for k in ("service", "location", "room", "equipment", "bath", "meal")
                            if h.get(f"{k}Average") not in (None, "", 0)},
                "facilities": collect_texts(entry, {"hotelFacilities"}),
                "room_facilities": collect_texts(entry, {"roomFacilities"}),
                "bath_type": tidy(h.get("bathType", "")),
                "checkin": h.get("checkinTime", ""),
                "checkout": h.get("checkoutTime", ""),
                "rooms": h.get("hotelRoomNum"),
                "smoking": smoking_status(collect_texts(entry, {"hotelFacilities", "roomFacilities", "note", "otherInformation"})),
            }
        paging = body.get("pagingInfo", {})
        if page >= int(paging.get("pageCount", 1) or 1) or page >= 10:
            break
        page += 1
    # 大浴場・温泉・禁煙ルームの有無は絞り込み検索で確かめる
    for cond, key in (("daiyoku", "daiyoku"), ("onsen", "onsen"), ("kinen", "kinen_room")):
        try:
            ids = squeeze_ids(venue, cond)
        except Exception as exc:
            print(f"  {cond}の絞り込みに失敗 {exc}", file=sys.stderr)
            continue
        for no, h in hotels.items():
            h[key] = no in ids
    for h in hotels.values():
        # 絞り込みに出なくても、館内設備に大浴場とあれば大浴場ありとする
        if not h.get("daiyoku") and any("大浴場" in t for t in h["facilities"] + [h["bath_type"]]):
            h["daiyoku"] = True
    result = sorted(hotels.values(), key=lambda h: h["distance_m"])[:venue.get("max_hotels", 200)]
    write_json(DATA / "hotels" / f"{venue['slug']}.json",
               {"venue": venue["slug"], "updated": date.today().isoformat(), "hotels": result})
    print(f"{venue['name']}: 周辺の宿 {len(result)}件")
    return result


PEOPLE = (1, 2, 3, 4)  # 人数別に空室を調べる


def fetch_vacancy_day(venue, checkin, adults):
    """その日に大人adults人で1室に泊まれる宿の、いちばん安いプランを宿ごとに取る。"""
    params = dict(base_params(venue), checkinDate=checkin.isoformat(),
                  checkoutDate=(checkin + timedelta(days=1)).isoformat(),
                  adultNum=adults, roomNum=1, hits=30, sort="+roomCharge", responseType="small")
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
                "per_person": round(cheapest["total"] / adults),
                "plan": tidy(cheapest.get("planName", "")),
                "room": tidy(cheapest.get("roomName", "")),
                "reserve_url": cheapest.get("reserveUrl", ""),
            }
        if page >= int(body.get("pagingInfo", {}).get("pageCount", 1) or 1):
            break
    return found


def fresh_enough(venue, checkin, today):
    """近い日付は毎日、先の日付は3日おきに調べ直す（楽天APIの呼び出しを減らすため）。"""
    old = read_json(DATA / "vacancy" / venue["slug"] / f"{checkin.isoformat()}.json")
    if not old or not old.get("checked"):
        return False
    age = (today - date.fromisoformat(old["checked"])).days
    return age < (1 if (checkin - today).days <= 21 else 3)


def fetch_date(venue, checkin):
    by_people = {}
    for n in PEOPLE:
        by_people[str(n)] = fetch_vacancy_day(venue, checkin, n)
    write_json(DATA / "vacancy" / venue["slug"] / f"{checkin.isoformat()}.json",
               {"checked": date.today().isoformat(), "checkin": checkin.isoformat(), "by_people": by_people})
    # 空いている宿の数と最安値を毎日記録して、埋まっていく様子を見られるようにする
    hist_path = DATA / "vacancy_history" / venue["slug"] / f"{checkin.isoformat()}.json"
    hist = read_json(hist_path, {"checkin": checkin.isoformat(), "log": []})
    today = date.today().isoformat()
    hist["log"] = [x for x in hist["log"] if x["checked"] != today]
    hist["log"].append({"checked": today, **{
        f"open{n}": len(v) for n, v in by_people.items()}, **{
        f"min{n}": min((o["per_person"] for o in v.values()), default=None) for n, v in by_people.items()}})
    write_json(hist_path, hist)
    print(f"  {checkin}: 空室あり " + " ".join(f"{n}人{len(v)}軒" for n, v in by_people.items()))


def next_saturday(today):
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def main():
    if not env("RAKUTEN_APP_ID") or not env("RAKUTEN_ACCESS_KEY"):
        print("楽天のアプリIDかアクセスキーが未設定のため、宿の取得を飛ばします")
        return 0
    failed = False
    today = date.today()
    all_venues = venues()
    for venue in all_venues:
        # 有明アリーナなどはビッグサイトの宿と空室をそのまま使う
        if venue.get("hotel_area"):
            continue
        try:
            fetch_hotels(venue)
        except Exception as exc:
            failed = True
            print(f"{venue['name']}: 宿の取得に失敗 {exc}", file=sys.stderr)
            continue
        events = [dict(e, _kind=v.get("kind")) for v in all_venues if v["slug"] == venue["slug"] or v.get("hotel_area") == venue["slug"]
                  for e in read_json(DATA / "events" / f"{v['slug']}.json", {"events": []})["events"]]
        # イベントの初日と、人数別ページに使う次の土曜日。同じ日は1回だけ調べる
        dates = {next_saturday(today)}
        # 料金を比べるための「イベントのない日」を、週末（土曜の夜）と平日（水曜の夜）で1日ずつ選ぶ
        own = read_json(DATA / "events" / f"{venue['slug']}.json", {"events": []})["events"]

        def busy(d):
            return any(e["start"] <= d.isoformat() <= e["end"] for e in own)
        base = {}
        for kind, wd in (("weekend", 5), ("weekday", 2)):
            d = today + timedelta(days=7)
            while d.weekday() != wd or busy(d):
                d += timedelta(days=1)
                if d > today + timedelta(days=90):
                    break
            if d <= today + timedelta(days=90):
                base[kind] = d.isoformat()
                dates.add(d)
        write_json(DATA / "baseline" / f"{venue['slug']}.json", base)
        for event in events:
            start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
            if not (today <= start <= today + timedelta(days=VACANCY_DAYS_AHEAD)):
                continue
            # 泊まる夜ごとに調べる。展示会と業界向けのイベントは、設営や前泊のある前日の夜も
            trade = event.get("_kind") == "exhibition" or any(k in (event.get("audience") or "") for k in ("商談", "関係者"))
            days = (end - start).days
            count = max(days, 1) if trade else days + 1  # ライブは公演のあった夜にも泊まる
            nights = [start + timedelta(days=i) for i in range(count)][:3]
            if trade:
                nights = [start - timedelta(days=1)] + nights
            dates.update(n for n in nights if n >= today)
        # 古い日付のファイルは消す
        folder = DATA / "vacancy" / venue["slug"]
        if folder.exists():
            for f in folder.glob("*.json"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.stem) or f.stem < today.isoformat():
                    f.unlink()
        for d in sorted(dates):
            if fresh_enough(venue, d, today):
                continue
            try:
                fetch_date(venue, d)
            except Exception as exc:
                failed = True
                print(f"  {d}: 空室の取得に失敗 {exc}", file=sys.stderr)
    # クリニックの近くの宿は、次の土曜と次の水曜の夜だけ空室を調べる（日程が人それぞれなので）
    sat = next_saturday(today)
    wed = today + timedelta(days=(2 - today.weekday()) % 7 or 7)
    for clinic in clinics():
        try:
            fetch_hotels(clinic)
        except Exception as exc:
            failed = True
            print(f"{clinic['name']}: 宿の取得に失敗 {exc}", file=sys.stderr)
            continue
        folder = DATA / "vacancy" / clinic["slug"]
        if folder.exists():
            for f in folder.glob("*.json"):
                if f.stem < today.isoformat():
                    f.unlink()
        for d in sorted({sat, wed}):
            if fresh_enough(clinic, d, today):
                continue
            try:
                fetch_date(clinic, d)
            except Exception as exc:
                failed = True
                print(f"  {clinic['name']} {d}: 空室の取得に失敗 {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
