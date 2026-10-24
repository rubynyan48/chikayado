"""data/ と templates/ から dist/ にサイトを書き出す。

固定ページ（道順や展示棟の案内）と、イベントごとのページを作る。
写真は static/images/ に日本語ファイル名で置くと、本文の決まった場所に入る。
"""
import json
import math
import re
import shutil
from datetime import date, timedelta
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from common import DATA, ROOT, SITE, read_json, venues

DIST = ROOT / "dist"
IMAGES = ROOT / "static" / "images"
WEEKDAYS = "月火水木金土日"
TODAY = date.today()


# ---- 表示の部品 -------------------------------------------------------

def jdate(iso, weekday=True):
    d = date.fromisoformat(iso)
    s = f"{d.month}月{d.day}日"
    return f"{s}（{WEEKDAYS[d.weekday()]}）" if weekday else s


def period(e, br=False):
    if e["start"] == e["end"]:
        return jdate(e["start"])
    sep = "<br>〜" if br else "〜"
    return f'{jdate(e["start"])}{sep}{jdate(e["end"])}'


def dist_label(m):
    return f"{m / 1000:.1f}km" if m >= 1000 else f"{m}m"


def walk_min(m):
    """直線距離から歩く時間の目安を出す（道のりは直線の約1.25倍、分速80mで計算）。"""
    return max(1, math.ceil(m * 1.25 / 80))


def yen(v):
    try:
        return f"{int(v):,}円"
    except (TypeError, ValueError):
        return ""


def stars(v, count=None):
    """評価を★で見せる。5点満点のうち塗られた割合で表す。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return Markup('<span class="sub">評価なし</span>')
    c = f'<span class="rate-count">（{int(count):,}件）</span>' if count else ""
    return Markup(f'<span class="stars" style="--r:{v / 5 * 100:.0f}%" role="img" aria-label="5点中{v:.2f}点">★★★★★</span>'
                  f'<span class="rate-num">{v:.2f}</span>{c}')


def bath_label(h):
    """大浴場の有無。温泉の大浴場ならそれも書く。"""
    if h.get("onsen"):
        return "あり（温泉）"
    if h.get("daiyoku"):
        return "あり"
    return "なし"


def smoke_label(h):
    if h.get("smoking"):
        return h["smoking"]
    return "要確認"


def chips(h):
    out = []
    if h.get("onsen"):
        out.append('<span class="chip chip-on">温泉</span>')
    elif h.get("daiyoku"):
        out.append('<span class="chip chip-on">大浴場</span>')
    if h.get("kinen_room"):
        out.append('<span class="chip">禁煙ルーム</span>')
    if h.get("smoking") == "喫煙できる場所あり":
        out.append('<span class="chip">喫煙できる場所あり</span>')
    elif h.get("smoking") == "全館禁煙":
        out.append('<span class="chip">全館禁煙</span>')
    return Markup(f'<span class="chips">{"".join(out)}</span>' if out else "")


def photo(filename, alt):
    if (IMAGES / filename).exists():
        return Markup(f'<figure><img src="/images/{escape(filename)}" alt="{escape(alt)}" loading="lazy" width="1200" height="800"></figure>')
    return Markup("")


def badge(m):
    if m <= 1000:
        return f'<span class="walk">徒歩約{walk_min(m)}分</span>'
    if m <= 1600:
        return f'<span class="walk far">徒歩約{walk_min(m)}分</span>'
    return '<span class="walk far">電車で1〜2駅</span>'


def book_url(h, vac=None):
    """予約ボタンのリンク先。もしもアフィリエイトの設定があれば、楽天トラベルの宿のページへの「どこでもリンク」にする。"""
    m = SITE.get("moshimo") or {}
    if m.get("a_id") and h.get("hotelNo"):
        no = h["hotelNo"]
        url = f"https://travel.rakuten.co.jp/HOTEL/{no}/{no}.html"
        from urllib.parse import quote
        return (f"https://af.moshimo.com/af/c/click?a_id={m['a_id']}&p_id={m['p_id']}&pc_id={m['pc_id']}"
                f"&pl_id={m['pl_id']}&url={quote(url, safe='')}")
    if vac and vac.get("reserve_url"):
        return vac["reserve_url"]
    return h.get("plan_url") or h.get("info_url") or "#"


def hotel_table(hotels, limit=None):
    if not hotels:
        return Markup('<p class="note">宿の情報を取得しています。しばらくしてからもう一度ご覧ください。</p>')
    rows = []
    for h in hotels[:limit] if limit else hotels:
        station = f'<span class="sub">{escape(h["station"])}駅</span>' if h.get("station") else ""
        rows.append(
            f'<tr><td><a href="{escape(book_url(h))}" rel="nofollow sponsored noopener" target="_blank">{escape(h["name"])}</a>{station}</td>'
            f'<td class="num">{dist_label(h["distance_m"])}</td><td class="tag">{badge(h["distance_m"])}</td></tr>'
        )
    return Markup(
        '<div class="table-wrap"><table class="t-hotels"><thead><tr><th>ホテル</th>'
        '<th class="num">直線距離</th><th class="tag">会場まで</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div>"
    )


def hotel_cards(hotels, limit=6, vacancy=None, checkin=None, numbered=False):
    """宿を1軒ずつ、大きな写真と予約ボタンで見せる。"""
    out = []
    for i, h in enumerate(hotels[:limit], 1):
        vac = (vacancy or {}).get(h["hotelNo"]) or h.get("offer")
        rows = [f'<tr><th>会場まで</th><td>直線{dist_label(h["distance_m"])}（{badge(h["distance_m"])}）</td></tr>']
        if h.get("station"):
            rows.append(f'<tr><th>最寄り駅</th><td>{escape(h["station"])}駅</td></tr>')
        if vac:
            rows.append(f'<tr><th>{jdate(checkin, False)}の料金</th><td>1人{yen(vac.get("per_person") or vac["total"])}から<span class="sub">{escape(vac.get("room") or "")}</span></td></tr>')
        elif h.get("min_charge"):
            rows.append(f'<tr><th>料金の目安</th><td>{yen(h["min_charge"])}から</td></tr>')
        if h.get("review_avg"):
            rows.append(f'<tr><th>口コミ評価</th><td>{stars(h["review_avg"], h.get("review_count"))}</td></tr>')
        rows.append(f'<tr><th>大浴場</th><td>{bath_label(h)}</td></tr>')
        rows.append(f'<tr><th>たばこ</th><td>{smoke_label(h)}{"（禁煙ルームあり）" if h.get("kinen_room") and h.get("smoking") != "全館禁煙" else ""}</td></tr>')
        if h.get("checkin"):
            out_time = f'（チェックアウト{escape(h["checkout"])}）' if h.get("checkout") else ""
            rows.append(f'<tr><th>チェックイン</th><td>{escape(h["checkin"])}から{out_time}</td></tr>')
        img = f'<img src="{escape(h["image"])}" alt="{escape(h["name"])}" loading="lazy">' if h.get("image") else ""
        access = f'<p class="hotel-access">{escape(h["access"])}</p>' if h.get("access") else ""
        out.append(
            f'<section class="hotel"><h3>{f"<span class=pin-no>{i}</span>" if numbered else ""}{escape(h["name"])}</h3>{img}'
            f'<table class="hotel-facts"><tbody>{"".join(rows)}</tbody></table>{access}'
            f'<div class="book"><p>予約はこちら</p><a class="btn btn-primary btn-block" href="{escape(book_url(h, vac))}" '
            f'rel="nofollow sponsored noopener" target="_blank">楽天トラベルで空室と料金を見る</a></div></section>'
        )
    return Markup("".join(out))


def price_of(h):
    """表示する料金。空室データがあれば1人あたりの料金、なければ最安料金の目安。"""
    if h.get("offer"):
        return h["offer"]["per_person"]
    try:
        return int(h.get("min_charge") or 0) or None
    except (TypeError, ValueError):
        return None


def with_offers(hotels, offers):
    """宿の一覧に、その日・その人数の空室料金を付ける。offersがNoneなら全件をそのまま返す。"""
    if offers is None:
        return [dict(h, offer=None) for h in hotels]
    return [dict(h, offer=offers[h["hotelNo"]]) for h in hotels if h["hotelNo"] in offers]


def best_picks(items):
    """目的別のおすすめを選ぶ。同じ宿がなるべく重ならないようにする。"""
    picks, used = [], set()

    def take(label, reason_fn, candidates, key, reverse=False):
        cands = [h for h in candidates if key(h) is not None]
        cands.sort(key=key, reverse=reverse)
        # いちばん条件に合う宿がすでにほかのおすすめに入っていたら、この項目は出さない
        if cands and cands[0]["hotelNo"] not in used:
            h = cands[0]
            used.add(h["hotelNo"])
            picks.append({"label": label, "reason": reason_fn(h), "hotel": h})

    near = [h for h in items if h["distance_m"] <= 1000]
    rated = [h for h in items if (h.get("review_count") or 0) >= 30]
    take("会場にいちばん近い", lambda h: f"会場まで徒歩約{walk_min(h['distance_m'])}分", items, lambda h: h["distance_m"])
    take("歩いて行けて安い", lambda h: f"{yen(price_of(h))}から", near, price_of)
    take("口コミの評価が高い", lambda h: f"評価{float(h['review_avg']):.2f}（{int(h['review_count']):,}件）", rated,
         lambda h: float(h["review_avg"]) if h.get("review_avg") else None, reverse=True)
    take("大浴場でくつろげる", lambda h: f"{'温泉の大浴場' if h.get('onsen') else '大浴場'}あり　会場まで{dist_label(h['distance_m'])}",
         [h for h in items if h.get("daiyoku") or h.get("onsen")], lambda h: h["distance_m"])
    take("食事の評価が高い", lambda h: f"食事の評価{float(h['ratings']['meal']):.2f}", rated,
         lambda h: float(h["ratings"]["meal"]) if h.get("ratings", {}).get("meal") else None, reverse=True)
    take("とにかく安く泊まる", lambda h: f"{yen(price_of(h))}から", items, price_of)
    return picks


def best_cards(items, per_person_note=""):
    picks = best_picks(items)
    if not picks:
        return Markup("")
    out = []
    for p in picks:
        h = p["hotel"]
        img = f'<img src="{escape(h["image"])}" alt="{escape(h["name"])}" loading="lazy">' if h.get("image") else '<span class="noimg"></span>'
        out.append(
            f'<a class="pick" href="{escape(book_url(h, h.get("offer")))}" rel="nofollow sponsored noopener" target="_blank">'
            f'<span class="pick-label">{p["label"]}</span>{img}'
            f'<span class="pick-name">{escape(h["name"])}</span><span class="pick-reason">{escape(p["reason"])}</span>'
            f'<span class="pick-meta">{stars(h.get("review_avg"))}</span><span class="pick-meta">{chips(h)}</span>'
            f'<span class="pick-btn">空室と料金を見る</span></a>'
        )
    note = f'<p class="note">{per_person_note}</p>' if per_person_note else ""
    return Markup(f'<div class="picks">{"".join(out)}</div>{note}')


def compare_table(items, price_label="料金の目安"):
    """写真つきの比較表。ボタンで近い順・安い順・評価順に並べ替えられる。"""
    if not items:
        return Markup('<p class="note">条件に合う宿が見つかりませんでした。</p>')
    rows = []
    for h in items:
        r = h.get("ratings", {})
        price = price_of(h)
        thumb = f'<img src="{escape(h["image"])}" alt="" loading="lazy">' if h.get("image") else ""
        rate = stars(h.get("review_avg"))
        names = {"location": "立地", "room": "部屋", "meal": "食事"}
        subs = "".join(f'<td class="num" data-label="{names[k]}の評価">{float(r[k]):.1f}</td>' if r.get(k)
                       else f'<td class="num" data-label="{names[k]}の評価">ー</td>' for k in ("location", "room", "meal"))
        rows.append(
            f'<tr data-dist="{h["distance_m"]}" data-price="{price or 999999}" data-rate="{h.get("review_avg") or 0}" '
            f'data-bath="{1 if h.get("daiyoku") or h.get("onsen") else 0}" data-smoke="{1 if h.get("smoking") == "喫煙できる場所あり" else 0}" '
            f'data-walk="{1 if h["distance_m"] <= 1000 else 0}">'
            f'<th scope="row"><a href="{escape(book_url(h, h.get("offer")))}" rel="nofollow sponsored noopener" target="_blank">'
            f'{thumb}<span>{escape(h["name"])}</span></a></th>'
            f'<td class="num" data-label="会場まで">{dist_label(h["distance_m"])}<span class="sub">徒歩約{walk_min(h["distance_m"])}分</span></td>'
            f'<td class="num" data-label="{price_label}">{yen(price) or "なし"}</td><td class="rate" data-label="口コミ評価">{rate}</td>'
            f'<td data-label="大浴場">{bath_label(h)}</td><td data-label="たばこ">{smoke_label(h)}</td>{subs}</tr>'
        )
    return Markup(
        '<div class="compare-block"><div class="sorter" role="group" aria-label="並べ替え"><button type="button" data-sort="dist" aria-pressed="true">近い順</button>'
        '<button type="button" data-sort="price" aria-pressed="false">安い順</button>'
        '<button type="button" data-sort="rate" aria-pressed="false">評価が高い順</button></div>'
        '<div class="filters" role="group" aria-label="絞り込み">'
        '<label><input type="checkbox" data-filter="walk">歩いて行ける</label>'
        '<label><input type="checkbox" data-filter="bath">大浴場・温泉あり</label>'
        + ('<label><input type="checkbox" data-filter="smoke">喫煙できる場所あり</label>'
           if any(h.get("smoking") == "喫煙できる場所あり" for h in items) else "") + '</div>'
        '<div class="table-wrap compare-wrap"><table class="compare"><thead><tr><th scope="col">ホテル</th>'
        f'<th class="num">会場まで</th><th class="num">{price_label}</th><th>口コミ評価</th><th>大浴場</th><th>たばこ</th>'
        '<th class="num">立地</th><th class="num">部屋</th><th class="num">食事</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div></div>"
    )


def hotel_map(items, venue, limit=20):
    """会場とホテルの位置を地図に出す（国土地理院の地図）。"""
    pins = [{"n": i, "name": h["name"], "lat": h["lat"], "lng": h["lng"], "d": dist_label(h["distance_m"]),
             "p": yen(price_of(h)), "url": book_url(h, h.get("offer"))} for i, h in enumerate(items[:limit], 1)]
    data = json.dumps({"venue": {"name": venue["name"], "lat": venue["lat"], "lng": venue["lng"]}, "pins": pins},
                      ensure_ascii=False).replace("</", "<\\/")
    return Markup(f'<div class="map" data-map=\'{escape(data)}\'></div>'
                  '<p class="note">地図の番号は下の一覧の番号と同じです。地図は国土地理院の地理院タイルを使っています。</p>')


def open_time(hours):
    """「10:00-17:00」のような書き方から開始時刻を取り出す。"""
    m = re.search(r"(\d{1,2})[:：](\d{2})", hours or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def move_min(m):
    """宿から会場の入口までにかかる時間の目安（分）。歩ける距離は歩き、それより遠い宿は電車を使う想定。"""
    if m <= 1600:
        return walk_min(m)
    return 35  # 駅まで歩き、ゆりかもめかりんかい線で1〜2駅、駅から会場まで歩く想定


def depart_table(items, hours, limit=10):
    """開場時刻に間に合う、宿を出る時刻の目安。入場の列や手荷物の確認に15分の余裕を見る。"""
    t = open_time(hours)
    if not t or not items:
        return Markup("")
    start = t[0] * 60 + t[1]
    rows = []
    for h in items[:limit]:
        mv = move_min(h["distance_m"])
        dep = start - mv - 15
        how = f"徒歩約{mv}分" if h["distance_m"] <= 1600 else "電車で約35分"
        rows.append(f'<tr><td>{escape(h["name"])}</td><td>{how}</td><td class="num"><strong>{dep // 60}:{dep % 60:02d}</strong>ごろ</td></tr>')
    return Markup(
        f'<div class="table-wrap"><table><thead><tr><th>ホテル</th><th>会場まで</th><th class="num">宿を出る時刻</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def audience_label(text):
    if not text:
        return ""
    if "商談" in text:
        return "業界関係者向け（商談が目的の展示会）"
    if "一般" in text:
        return "一般の方も来場できます"
    return text


def route_map(venue, station_page, hotels, goal_step, via=None, via_step=None):
    """駅から会場の正面までの道のりを地図に描く。viaに宿名の一部を入れると、その宿の前を通る。"""
    st = next(x for x in venue["stations"] if x["page"] == station_page)
    pts = [{"n": 1, "name": f"{st['name']}の改札", "lat": st["lat"], "lng": st["lng"]}]
    if via:
        h = next((x for x in hotels if via in x["name"]), None)
        if h:
            pts.append({"n": via_step, "name": f"{h['name']}の前", "lat": h["lat"], "lng": h["lng"]})
    f = venue["front"]
    pts.append({"n": goal_step, "name": f["name"], "lat": f["lat"], "lng": f["lng"]})
    data = json.dumps({"route": pts}, ensure_ascii=False).replace("</", "<\\/")
    return Markup(f'<div class="map map-route" data-map=\'{escape(data)}\'></div>'
                  '<p class="note">地図の番号は下の道順の番号と同じです。線は道のりのおおよその向きを示した目安です。実際は歩道や階段に沿って進みます。地図は国土地理院の地理院タイルを使っています。</p>')


def quick_cards(items, limit=5, labels=None):
    """スマホで一目で選べる横長のカード。写真、名前、徒歩、評価、料金、予約ボタン。"""
    if not items:
        return Markup('<p class="empty">この条件で空いている宿は見つかりませんでした。日付か人数を変えて探してみてください。</p>')
    out = []
    for i, h in enumerate(items[:limit]):
        price = price_of(h)
        label = f'<span class="qc-label">{escape(labels[i])}</span>' if labels else ""
        img = f'<img src="{escape(h["image"])}" alt="" loading="lazy">' if h.get("image") else '<span class="qc-noimg"></span>'
        bath = '<span class="chip chip-on">大浴場</span>' if h.get("daiyoku") or h.get("onsen") else ""
        price_html = (f'<span class="qc-price">{"1人" if h.get("offer") else ""}<strong>{yen(price)}</strong>から</span>'
                      if price else "")
        out.append(
            f'<a class="qc" href="{escape(book_url(h, h.get("offer")))}" rel="nofollow sponsored noopener" target="_blank">'
            f'{label}<span class="qc-row">{img}<span class="qc-body"><span class="qc-name">{escape(h["name"])}</span>'
            f'<span class="qc-meta"><span class="walk">徒歩{walk_min(h["distance_m"])}分</span>{bath}</span>'
            f'<span class="qc-rate">{stars(h.get("review_avg"))}</span>{price_html}</span></span>'
            f'<span class="qc-btn">空室と料金を見る</span></a>'
        )
    return Markup(f'<div class="qcs">{"".join(out)}</div>')


def people_switch(hotels, by_people, limit=5):
    """人数のボタンを押すと、その人数で泊まれる近い宿に切り替わる。"""
    tabs, panels = [], []
    for i, n in enumerate(("1", "2", "3", "4")):
        items = with_offers(hotels, by_people.get(n, {}))
        tabs.append(f'<button type="button" role="tab" aria-selected="{"true" if i == 0 else "false"}" data-tab="ps{n}">{n}人</button>')
        panels.append(f'<div role="tabpanel" id="ps{n}"{"" if i == 0 else " hidden"}>{quick_cards(items, limit)}</div>')
    return Markup(f'<div class="tabs"><div class="tablist tablist-big" role="tablist" aria-label="泊まる人数">{"".join(tabs)}</div>{"".join(panels)}</div>')


def search_box(venue, default_date, adults="1"):
    """日付と人数を選んで、その場で空室を探すフォーム。結果はサーバーのPHPが楽天に問い合わせて返す。"""
    btns = "".join(f'<label class="pp"><input type="radio" name="adults" value="{n}"{" checked" if str(n) == str(adults) else ""}><span>{n}人</span></label>'
                   for n in (1, 2, 3, 4))
    return Markup(
        f'<form class="search" data-venue="{venue["slug"]}"><label class="search-date"><span>泊まる日</span>'
        f'<input type="date" name="date" value="{default_date}" min="{TODAY.isoformat()}" required></label>'
        f'<div class="search-people" role="group" aria-label="人数">{btns}</div>'
        '<button type="submit" class="btn btn-primary btn-block">空いている宿を探す</button>'
        '<p class="search-note">会場から3km以内の宿を、楽天トラベルの空室から近い順に出します。料金は1人あたりの最安値です。</p>'
        '<div class="search-result" aria-live="polite"></div></form>'
    )


def more_buttons(items):
    """詳しいページへの大きなボタン。items は (リンク先, 見出し, 説明) の並び。"""
    return Markup('<div class="more">' + "".join(
        f'<a class="more-btn" href="{escape(href)}"><strong>{escape(t)}</strong><span>{escape(d)}</span></a>' for href, t, d in items
    ) + "</div>")


def median(xs):
    xs = sorted(x for x in xs if x)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def event_stats(hotels, vacancy, base, history):
    """その日だけの数字。空いている宿の数、ふだんの土曜日と比べた料金、空室の減り方。"""
    if not vacancy:
        return None
    total = len(hotels)
    ids = {h["hotelNo"] for h in hotels}
    near = {h["hotelNo"] for h in hotels if h["distance_m"] <= 1000}
    rows = []
    for n in ("1", "2", "3", "4"):
        v = {k: o for k, o in vacancy["by_people"].get(n, {}).items() if k in ids}
        rows.append({"n": n, "open": len(v), "near": len(set(v) & near),
                     "min": min((o["per_person"] for o in v.values()), default=None),
                     "median": median(o["per_person"] for o in v.values())})
    stats = {"total": total, "near_total": len(near), "rows": rows, "one": rows[0]}
    if base and base.get("checkin") != vacancy.get("checkin"):
        ev, bs = vacancy["by_people"].get("1", {}), base["by_people"].get("1", {})
        common = [k for k in ev if k in bs and k in ids]
        if len(common) >= 3:
            ratio = median(ev[k]["per_person"] for k in common) / median(bs[k]["per_person"] for k in common)
            stats.update(ratio=round(ratio, 1), base_date=base["checkin"], compared=len(common))
    log = (history or {}).get("log", [])
    if len(log) >= 2:
        first, last = log[0], log[-1]
        stats.update(hist_from=first["checked"], hist_open_from=first.get("open1"), hist_open_now=last.get("open1"))
    return stats


def people_tabs(hotels, by_people, checkin):
    """人数を切り替えて、その人数で泊まれる宿の比較表を見せる。"""
    if not by_people:
        return Markup("")
    tabs, panels = [], []
    for i, n in enumerate(("1", "2", "3", "4")):
        items = with_offers(hotels, by_people.get(n, {}))
        tabs.append(f'<button type="button" role="tab" aria-selected="{"true" if i == 0 else "false"}" data-tab="p{n}">{n}人</button>')
        head = f'<p class="note">{jdate(checkin)}に大人{n}人が1部屋に泊まれる宿は{len(items)}軒です。料金は1人あたりの最安値です。</p>'
        panels.append(f'<div role="tabpanel" id="p{n}"{"" if i == 0 else " hidden"}>{head}{compare_table(items, "1人あたり")}</div>')
    return Markup(f'<div class="tabs"><div class="tablist" role="tablist" aria-label="人数">{"".join(tabs)}</div>{"".join(panels)}</div>')


def event_table(events, venue_slug, limit=None):
    rows = events[:limit] if limit else events
    if not rows:
        return Markup('<p class="note">これから開催されるイベントの情報を取得しています。</p>')
    cells = []
    for e in rows:
        hall = f'<span class="sub">{escape(e["hall"])}</span>' if e.get("hall") else ""
        cells.append(f'<tr><td class="date">{period(e, br=True)}</td>'
                     f'<td><a href="/{venue_slug}/{escape(e["slug"])}/">{escape(e["name"])}</a>{hall}</td></tr>')
    body = "".join(cells)
    return Markup('<div class="table-wrap"><table class="t-events"><thead><tr><th class="date">開催日</th><th>イベント</th></tr>'
                  f"</thead><tbody>{body}</tbody></table></div>")


def restaurant_table(shops, limit=3):
    rows = "".join(
        f'<tr><td><a href="{escape(s["url"])}" rel="nofollow noopener" target="_blank">{escape(s["name"])}</a>'
        f'<span class="sub">{escape(s["genre"])}</span></td><td>{escape(s["budget"])}</td><td class="num">{dist_label(s["distance_m"])}</td></tr>'
        for s in shops[:limit]
    )
    return Markup('<div class="table-wrap"><table><thead><tr><th>店</th><th>予算</th><th class="num">宿から</th></tr></thead>'
                  f"<tbody>{rows}</tbody></table></div>")


def buildings(hall):
    """会場ホールの書き方から、どの展示棟かを読み取る。"""
    found = []
    for key, name in (("東", "東展示棟"), ("西", "西展示棟"), ("南", "南展示棟"), ("会議", "会議棟"), ("GYM", "有明GYM-EX")):
        if key in (hall or ""):
            found.append(name)
    return found


# ---- ページの組み立て -------------------------------------------------

H2_RE = re.compile(r'<h2(?: id="([^"]+)")?>(.*?)</h2>', re.S)


def add_toc(body):
    toc = []

    def repl(m):
        n = len(toc) + 1
        hid = m.group(1) or f"s{n}"
        toc.append({"id": hid, "text": re.sub(r"<[^>]+>", "", m.group(2)).strip()})
        return f'<h2 id="{hid}">{m.group(2)}</h2>'

    return H2_RE.sub(repl, body), toc


def breadcrumb_ld(crumbs):
    return json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": c["name"], "item": SITE["base_url"] + c["path"]}
                            for i, c in enumerate(crumbs)],
    }, ensure_ascii=False)


def venue_context(venue):
    hotels = read_json(DATA / "hotels" / f"{venue['slug']}.json", {"hotels": []})["hotels"]
    events = read_json(DATA / "events" / f"{venue['slug']}.json", {"events": []})["events"]
    restaurants = read_json(DATA / "restaurants" / f"{venue['slug']}.json", {"by_hotel": {}})["by_hotel"]
    upcoming = [e for e in events if e["end"] >= TODAY.isoformat()]
    sat = TODAY + timedelta(days=(5 - TODAY.weekday()) % 7 or 7)
    series = []
    for sr in read_json(ROOT / "config" / "series" / f"{venue['slug']}.json", []) or []:
        pat = re.compile(sr["match"])
        matched = [e for e in events if pat.search(e["name"])]
        nxt = next((e for e in matched if e["end"] >= TODAY.isoformat()), None)
        series.append(dict(sr, events=matched, next=nxt))
    for e in events:
        e["series"] = next((sr["slug"] for sr in series if e in sr["events"]), None)
    return {
        "series": series,
        "venue": venue,
        "hotels": hotels,
        "near_hotels": [h for h in hotels if h["distance_m"] <= 1000],
        "all_events": events,
        "events": upcoming,
        "restaurants": restaurants,
        "saturday": sat.isoformat(),
        "sat_vacancy": read_json(DATA / "vacancy" / venue["slug"] / f"{sat.isoformat()}.json"),
    }


PEOPLE_PAGES = [
    ("hitori", "1", "1人"), ("futari", "2", "2人"), ("3nin", "3", "3人"), ("4nin", "4", "4人"),
]


def pages_for(venue, ctx):
    v = f"/{venue['slug']}/"
    home = {"name": "トップ", "path": "/"}
    hub = {"name": venue["name"], "path": v}
    cta = {"href": v + "#hotels", "label": "会場に近いホテルを見る"}
    n = len(ctx["hotels"])
    nearest = ctx["hotels"][0] if ctx["hotels"] else None
    pages = [
        {"path": v, "template": "venue.html",
         "title": f"{venue['name']}に近いホテル 会場から近い順に{n}軒" if n else f"{venue['name']}に近いホテル",
         "description": (f"{venue['name']}にいちばん近いホテルは{nearest['name']}で会場から直線で約{dist_label(nearest['distance_m'])}です。"
                         f"徒歩圏の{len(ctx['near_hotels'])}軒と周辺のホテルを会場から近い順にまとめました。") if nearest
         else f"{venue['name']}の周辺にあるホテルを会場から近い順にまとめています。",
         "breadcrumbs": [home, hub], "float_cta": {"href": "#search", "label": "日付と人数で空室を探す"}},
        {"path": v + "hotels/", "template": "hotels.html",
         "title": f"{venue['name']}周辺のホテルを地図と比較表で選ぶ",
         "description": f"{venue['name']}から3km以内のホテルを、地図と比較表で並べました。距離、料金、口コミの評価、大浴場の有無で並べ替えや絞り込みができます。",
         "breadcrumbs": [home, hub, {"name": "ホテルの比較", "path": v + "hotels/"}],
         "float_cta": {"href": v, "label": "おすすめのホテルを見る"}, "has_map": True},
        {"path": v + "yurikamome/", "template": "yurikamome.html",
         "title": "ゆりかもめ東京ビッグサイト駅から会場までの道順",
         "description": "ゆりかもめの東京ビッグサイト駅から会場までは徒歩約3分です。改札を出てから会議棟の前に着くまでと、東展示棟・西展示棟・南展示棟への進み方を順番に案内します。",
         "breadcrumbs": [home, hub, {"name": "ゆりかもめからの道順", "path": v + "yurikamome/"}], "float_cta": cta},
        {"path": v + "rinkai/", "template": "rinkai.html",
         "title": "りんかい線国際展示場駅から東京ビッグサイトまでの道順",
         "description": "りんかい線の国際展示場駅から東京ビッグサイトまでは徒歩約7分です。改札は1か所で、駅を出て右へ進み、ワシントンホテルの前を通って会場の正面へ出ます。",
         "breadcrumbs": [home, hub, {"name": "りんかい線からの道順", "path": v + "rinkai/"}], "float_cta": cta},
        {"path": v + "halls/", "template": "halls.html",
         "title": "東京ビッグサイトの東展示棟と西展示棟と南展示棟の違い",
         "description": "東京ビッグサイトには東・西・南の3つの展示棟と会議棟があります。ホールの番号、広さ、駅からの近さの違いと、イベントの棟に合わせた宿の選び方をまとめました。",
         "breadcrumbs": [home, hub, {"name": "展示棟の違い", "path": v + "halls/"}], "float_cta": cta},
        {"path": v + "area/", "template": "area.html",
         "title": "東京ビッグサイトに行くなら泊まるエリアは有明か豊洲か台場か",
         "description": "東京ビッグサイトに泊まりで行くなら、朝ゆっくりできるのは歩いて行ける有明、選択肢が多いのは豊洲、観光も楽しむなら台場です。りんかい線や新橋も含めて比べました。",
         "breadcrumbs": [home, hub, {"name": "泊まるエリアの選び方", "path": v + "area/"}], "float_cta": cta},
        {"path": v + "access/", "template": "access.html",
         "title": "東京駅や新宿駅や羽田空港から東京ビッグサイトへの行き方",
         "description": "東京ビッグサイトへは新橋駅からゆりかもめ、大崎駅や新宿駅からりんかい線で乗り換えなしで行けます。東京駅や品川駅、羽田空港や成田空港からの行き方と時間の目安をまとめました。",
         "breadcrumbs": [home, hub, {"name": "主な駅と空港からの行き方", "path": v + "access/"}], "float_cta": cta},
        {"path": v + "exhibitor/", "template": "exhibitor.html",
         "title": "東京ビッグサイトの展示会に出展するときの宿の選び方",
         "description": "東京ビッグサイトの展示会に出展するなら、宿は会場まで歩ける有明がいちばん楽です。前日入りの押さえ方や荷物の預け方、近くが取れなかったときの探し方をまとめました。",
         "breadcrumbs": [home, hub, {"name": "出展者の宿の選び方", "path": v + "exhibitor/"}], "float_cta": cta},
        *[{"path": f"{v}{slug}/", "template": "people.html", "people": n, "people_label": label,
           "title": f"{venue['name']}近くのホテルに{label}で泊まる 1人あたりの料金と空室",
           "description": f"{venue['name']}の近くで{label}で1部屋に泊まれるホテルを、会場からの距離と1人あたりの料金で比べました。近い宿、安い宿、評価の高い宿のおすすめもまとめています。",
           "breadcrumbs": [home, hub, {"name": f"{label}で泊まる", "path": f"{v}{slug}/"}],
           "float_cta": {"href": "#best", "label": f"{label}で泊まれるおすすめを見る"}, "has_map": True}
          for slug, n, label in PEOPLE_PAGES],
        *[{"path": f"{v}{sr['slug']}/", "template": "series.html", "series": sr,
           "vacancy": read_json(DATA / "vacancy" / venue["slug"] / f"{sr['next']['start']}.json") if sr["next"] else None,
           "title": f"{sr['short']}の会場に近いホテル {venue['name']}周辺で空いている宿",
           "description": (f"次の{sr['name']}（{sr['next']['name']}）は{period(sr['next'])}に{venue['name']}で開かれます。" if sr["next"]
                           else f"{sr['name']}は{venue['name']}で開かれるイベントです。")
                          + "会場に近いホテルの空室と1人あたりの料金を、人数を選ぶだけで確かめられます。",
           "breadcrumbs": [home, hub, {"name": f"{sr['short']}の宿", "path": f"{v}{sr['slug']}/"}],
           "float_cta": {"href": "#hotels", "label": "空いている近い宿を見る"}}
          for sr in ctx["series"]],
        {"path": v + "events/", "template": "events.html",
         "title": f"{venue['name']}の開催予定イベント一覧",
         "description": f"{venue['name']}でこれから開催される展示会や一般向けイベントを日付順にまとめています。イベントごとに会場に近いホテルと開催日の空室も確認できます。",
         "breadcrumbs": [home, hub, {"name": "開催予定イベント", "path": v + "events/"}], "float_cta": cta},
    ]
    for e in ctx["all_events"]:
        path = f"{v}{e['slug']}/"
        concurrent = [o for o in ctx["all_events"] if o is not e and o["start"] <= e["end"] and o["end"] >= e["start"]]
        days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days + 1
        vac = read_json(DATA / "vacancy" / venue["slug"] / f"{e['start']}.json") if e["end"] >= TODAY.isoformat() else None
        text = read_json(DATA / "texts" / venue["slug"] / f"{e['slug']}.json")
        hist = read_json(DATA / "vacancy_history" / venue["slug"] / f"{e['start']}.json")
        # 比べる相手は、同じ曜日の種類（金土の夜は週末、それ以外は平日）でイベントのない日
        kind = "weekend" if date.fromisoformat(e["start"]).weekday() in (4, 5) else "weekday"
        base_date = (read_json(DATA / "baseline" / f"{venue['slug']}.json", {}) or {}).get(kind)
        base_vac = read_json(DATA / "vacancy" / venue["slug"] / f"{base_date}.json") if base_date else None
        common = {"event": e, "vacancy": vac, "text": text, "concurrent": concurrent[:12], "days": days, "credit_events": True,
                  "history": hist, "base_vacancy": base_vac, "base_kind": kind}
        pages.append(dict(common, **{
            "path": path, "template": "event.html",
            "title": f"{e['name']}に近いホテル {venue['name']}周辺の宿",
            "description": f"{e['name']}（{period(e)} {venue['name']}）の会場に近いホテルを、開催日の空室と1人あたりの料金で選べます。"
                           "人数を選ぶだけで泊まれる宿がわかり、日付を変えて空室を探すこともできます。",
            "breadcrumbs": [home, hub, {"name": "開催予定イベント", "path": v + "events/"}, {"name": e["name"], "path": path}],
            "float_cta": {"href": "#hotels", "label": "空いている近い宿を見る"},
        }))
    return pages


def common_pages():
    home = {"name": "トップ", "path": "/"}
    return [
        {"path": "/", "template": "home.html", "is_home": True, "no_toc": True,
         "title": "ちか宿 イベント会場に近い宿を距離で探す", "h1": "会場に近い宿を距離で探す",
         "description": "東京ビッグサイトなどイベント会場の近くにあるホテルを、会場からの距離順にまとめています。イベントごとの空室や、駅からの道順も案内します。",
         "breadcrumbs": []},
        {"path": "/about/", "template": "about.html", "no_toc": True, "title": "運営者情報",
         "description": "ちか宿の運営者情報と、サイトに載せている情報の集め方についてです。",
         "breadcrumbs": [home, {"name": "運営者情報", "path": "/about/"}]},
        {"path": "/contact/", "template": "contact.html", "no_toc": True, "title": "お問い合わせ",
         "description": "ちか宿へのお問い合わせ方法です。掲載内容の誤りのご指摘や、会場周辺の情報提供も受け付けています。",
         "breadcrumbs": [home, {"name": "お問い合わせ", "path": "/contact/"}]},
        {"path": "/privacy/", "template": "privacy.html", "no_toc": True, "title": "プライバシーポリシー",
         "description": "ちか宿のプライバシーポリシーです。アクセス解析ツールや広告の取り扱いについて説明しています。",
         "breadcrumbs": [home, {"name": "プライバシーポリシー", "path": "/privacy/"}]},
    ]


def css_version():
    import hashlib
    return hashlib.md5((ROOT / "static" / "style.css").read_bytes()).hexdigest()[:8]


def main():
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    helpers = {"photo": photo, "hotel_table": hotel_table, "hotel_cards": hotel_cards, "best_cards": best_cards,
               "compare_table": compare_table, "hotel_map": hotel_map, "people_tabs": people_tabs,
               "with_offers": with_offers, "price_of": price_of, "event_stats": event_stats, "best_picks": best_picks, "depart_table": depart_table,
               "open_time": open_time, "audience_label": audience_label,
               "event_table": event_table, "restaurant_table": restaurant_table, "dist_label": dist_label,
               "walk_min": walk_min, "yen": yen, "quick_cards": quick_cards, "people_switch": people_switch,
               "search_box": search_box, "more_buttons": more_buttons, "route_map": route_map, "book_url": book_url, "stars": stars, "chips": chips, "jdate": jdate, "period": period, "buildings": buildings,
               "site": SITE, "today": TODAY.isoformat(), "css_v": css_version()}
    all_venues = venues()
    main_venue = all_venues[0]
    main_ctx = venue_context(main_venue)

    jobs = [(p, main_ctx) for p in common_pages()]
    for venue in all_venues:
        ctx = venue_context(venue)
        jobs += [(p, ctx) for p in pages_for(venue, ctx)]

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    updated = f"{TODAY.year}年{TODAY.month}月{TODAY.day}日"
    uses_hotpepper = False

    for page, ctx in jobs:
        page = dict(page)
        raw = env.get_template("pages/" + page["template"]).render(page=page, **ctx, **helpers)
        lead, _, body = raw.partition("<!--body-->")
        body, toc = add_toc(body)
        page.update(lead=lead, body=body, toc=None if page.get("no_toc") else toc,
                    updated=None if page.get("no_toc") else updated,
                    breadcrumb_ld=breadcrumb_ld(page["breadcrumbs"]) if page["breadcrumbs"] else "",
                    events_credit=ctx["venue"] if page.get("credit_events") or page["template"] == "events.html" else None,
                    hotpepper="hotpepper.jp" in body)
        uses_hotpepper |= page["hotpepper"]
        side = {"venue": main_ctx["venue"], "events": main_ctx["events"][:6], "people": PEOPLE_PAGES, "series": main_ctx["series"]}
        html = env.get_template("base.html").render(page=page, has_hotels=bool(ctx["hotels"]), side=side, **helpers)
        out = DIST / page["path"].lstrip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")

    side = {"venue": main_ctx["venue"], "events": main_ctx["events"][:6], "people": PEOPLE_PAGES, "series": main_ctx["series"]}
    nf = {"path": "/404.html", "title": "ページが見つかりません", "description": "", "breadcrumbs": [],
          "lead": '<p>お探しのページは移動したか、開催が終わって削除された可能性があります。</p>',
          "body": '<p><a class="btn btn-primary" href="/">トップへ戻る</a></p>'}
    (DIST / "404.html").write_text(env.get_template("base.html").render(page=nf, has_hotels=False, side=side, **helpers),
                                   encoding="utf-8")
    shutil.copy(ROOT / "static" / "style.css", DIST / "style.css")
    for extra in sorted((ROOT / "static").iterdir()):
        if extra.is_file() and extra.name != "style.css":
            shutil.copy(extra, DIST / extra.name)  # Search Consoleの確認ファイルなど
    if IMAGES.exists():
        shutil.copytree(IMAGES, DIST / "images")
    # 空室検索（PHP）が使う宿の一覧
    shutil.copytree(ROOT / "static" / "api", DIST / "api")
    for venue in all_venues:
        ctx = venue_context(venue)
        (DIST / "api" / f"hotels-{venue['slug']}.json").write_text(json.dumps({
            "lat": venue["lat"], "lng": venue["lng"], "moshimo": SITE.get("moshimo"),
            "hotels": [{"hotelNo": h["hotelNo"], "name": h["name"], "walk": walk_min(h["distance_m"]),
                        "distance": dist_label(h["distance_m"]), "image": h.get("image", ""),
                        "rate": h.get("review_avg"), "bath": bool(h.get("daiyoku") or h.get("onsen"))} for h in ctx["hotels"]],
        }, ensure_ascii=False), encoding="utf-8")

    urls = "".join(f"<url><loc>{SITE['base_url']}{p['path']}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>" for p, _ in jobs)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE['base_url']}/sitemap.xml\n", encoding="utf-8")
    print(f"{len(jobs)}ページを書き出しました")


if __name__ == "__main__":
    main()
