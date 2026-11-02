"""新しい会場の候補について、楽天トラベルの近くの宿の数と、開催日になりそうな日の空室を数える（下調べ用）。"""
from datetime import date, timedelta

from common import distance_m
from fetch_hotels import HOTEL_URL, base_params, fetch_vacancy_day, flatten_hotel, headers, polite_get

CANDIDATES = [
    ("京セラドーム大阪", 34.6694, 135.4761),
    ("大阪城ホール", 34.6899, 135.5340),
    ("バンテリンドーム ナゴヤ", 35.1859, 136.9475),
    ("みずほPayPayドーム福岡", 33.5953, 130.3622),
]
today = date.today()
sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
days = [sat, sat + timedelta(days=4), sat + timedelta(days=28)]
for name, lat, lng in CANDIDATES:
    v = {"name": name, "lat": lat, "lng": lng, "search_radius_km": 3.0}
    hotels, page = {}, 1
    while True:
        res = polite_get(HOTEL_URL, dict(base_params(v), responseType="small", hits=30, page=page), headers())
        if res is None:
            break
        body = res.json()
        for entry in body.get("hotels", []):
            h = flatten_hotel(entry)
            if h.get("hotelNo") and h.get("latitude") not in (None, ""):
                hotels[str(h["hotelNo"])] = distance_m(lat, lng, float(h["latitude"]), float(h["longitude"]))
        if page >= int(body.get("pagingInfo", {}).get("pageCount", 1) or 1):
            break
        page += 1
    ds = list(hotels.values())
    print(f"{name}: 3km以内 {sum(d <= 3000 for d in ds)}軒 2km以内 {sum(d <= 2000 for d in ds)}軒 1km以内 {sum(d <= 1000 for d in ds)}軒 500m以内 {sum(d <= 500 for d in ds)}軒")
    for d in days:
        one = fetch_vacancy_day(v, d, 1)
        two = fetch_vacancy_day(v, d, 2)
        near1 = sum(1 for k in one if hotels.get(k, 9999) <= 1000)
        cheap = min((o["per_person"] for o in one.values()), default=None)
        print(f"  {d}: 空室あり 1人{len(one)}軒（1km以内{near1}軒） 2人{len(two)}軒 1人の最安 {cheap}円")
