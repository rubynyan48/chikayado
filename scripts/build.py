"""data/ と templates/ から dist/ にサイトを書き出す。

固定ページ（道順や展示棟の案内）と、イベントごとのページを作る。
写真は static/images/ に日本語ファイル名で置くと、本文の決まった場所に入る。
"""
import json
from urllib.parse import quote
import math
import re
import shutil
from datetime import date, timedelta
from html import escape, unescape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from common import DATA, ROOT, SITE, distance_m, read_json, venues
from hero import make_hero
from PIL import Image

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


CHIKA = {"wave": "ちかちゃん手を振る.webp", "check": "ちかちゃんチェック.webp", "food": "ちかちゃん食事処案内.webp", "ok": "ちかちゃんOK.webp"}


def chika(pose, text):
    """案内係のちかちゃんが一言そえる吹き出し。"""
    return Markup(f'<div class="chika"><img src="/images/{CHIKA[pose]}" alt="ちか宿の案内係" width="80" height="100" loading="lazy">'
                  f'<p class="chika-say">{text}</p></div>')


def banner(filename, alt):
    """見出しのすぐ下に置くバナー画像。"""
    return Markup(f'<figure class="banner"><img src="/images/{escape(filename)}" alt="{escape(alt)}" width="1000" height="333" loading="lazy"></figure>')


def photo(filename, alt):
    if (IMAGES / filename).exists():
        with Image.open(IMAGES / filename) as im:
            w, h = im.size
        return Markup(f'<figure><img src="/images/{escape(filename)}" alt="{escape(alt)}" loading="lazy" width="{w}" height="{h}"></figure>')
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
    """会場とホテルの位置を地図に出す（OpenStreetMapの地図）。"""
    pins = [{"n": i, "name": h["name"], "lat": h["lat"], "lng": h["lng"], "d": dist_label(h["distance_m"]),
             "p": yen(price_of(h)), "url": book_url(h, h.get("offer"))} for i, h in enumerate(items[:limit], 1)]
    data = json.dumps({"venue": {"name": venue["name"], "lat": venue["lat"], "lng": venue["lng"]}, "pins": pins},
                      ensure_ascii=False).replace("</", "<\\/")
    return Markup(f'<div class="map" data-map=\'{escape(data)}\'></div>'
                  '<p class="note">地図の番号は下の一覧の番号と同じです。地図はOpenStreetMapを使っています。</p>')


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
    if ("商談" in text or "関係者" in text) and "一般" in text:
        return "業界関係者が中心（一般の人も入場できます。事前登録が必要なことが多いので公式サイトで確認してください）"
    if "商談" in text or "関係者" in text:
        return "業界関係者向け（商談や研究発表が目的です）"
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
                  '<p class="note">地図の番号は下の道順の番号と同じです。線は道のりのおおよその向きを示した目安です。実際は歩道や階段に沿って進みます。地図はOpenStreetMapを使っています。</p>')


def walk_chip(m):
    w = walk_min(m)
    return f'<span class="walk">徒歩{w}分</span>' if w <= 20 else '<span class="walk far">電車で1〜2駅</span>'


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
            f'<span class="qc-meta">{walk_chip(h["distance_m"])}{bath}</span>'
            f'<span class="qc-rate">{stars(h.get("review_avg"))}</span>{price_html}</span></span>'
            f'<span class="qc-btn">空室と料金を見る</span></a>'
        )
    return Markup(f'<div class="qcs">{"".join(out)}</div>')


def rank_tabs(items, limit=5, key="rk"):
    """近さ・レビュー・安さのボタンで、簡易ランキングを切り替える。"""
    def rate(h):
        try:
            return float(h.get("review_avg") or 0)
        except (TypeError, ValueError):
            return 0.0
    orders = [
        ("近さ", sorted(items, key=lambda h: h["distance_m"])),
        ("レビュー", sorted([h for h in items if rate(h) > 0], key=lambda h: (-rate(h), -(h.get("review_count") or 0)))),
        ("安さ", sorted([h for h in items if price_of(h)], key=lambda h: price_of(h))),
    ]
    tabs, panels = [], []
    for i, (name, lst) in enumerate(orders):
        tabs.append(f'<button type="button" role="tab" aria-selected="{"true" if i == 0 else "false"}" data-tab="{key}{i}">{name}</button>')
        labels = [f"{name}で{r + 1}位" for r in range(limit)]
        panels.append(f'<div role="tabpanel" id="{key}{i}"{"" if i == 0 else " hidden"}>{quick_cards(lst, limit, labels)}</div>')
    return Markup(f'<div class="tabs"><div class="tablist tablist-big" role="tablist" aria-label="並べ方">{"".join(tabs)}</div>{"".join(panels)}</div>')


def api_item(h):
    """画面の中で並べ替えるための、宿1軒分の情報（空室検索の返事と同じ形）。"""
    return {"name": h["name"], "walk": walk_min(h["distance_m"]), "image": h.get("image", ""),
            "rate": h.get("review_avg"), "bath": bool(h.get("daiyoku") or h.get("onsen")),
            "per_person": price_of(h), "url": book_url(h, h.get("offer"))}


def stay_nights(e, venue):
    """泊まる日のボタンに出す夜。展示会は設営や前泊のある前日の夜から、会期の最終日の前夜まで。"""
    if not e:
        return []
    start, end = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
    trade = is_trade(e)
    out = []
    md = lambda d: f"{d.month}/{d.day}"
    if venue.get("kind") == "exhibition" or trade:
        d = start - timedelta(days=1)
        if d >= TODAY:
            out.append((d.isoformat(), md(d), "前日・設営" if trade else "前日"))
    days = (end - start).days
    for i in range(max(days, 1)):
        d = start + timedelta(days=i)
        if d >= TODAY:
            out.append((d.isoformat(), md(d), ("初日" if i == 0 else f"{i + 1}日目") if days else "当日"))
    return out[:6] if len(out) > 1 else []


def is_trade(e):
    """業界関係者が中心のイベント（商談の展示会、学会など）。"""
    a = e.get("audience") or ""
    return "商談" in a or "関係者" in a


def rec_box(venue, hotels, by_people, default_date, adults="1", limit=6, nights=None):
    """近いおすすめ宿。日付・人数・並べ方（距離・値段・レビュー）を選ぶと、その場で並べ替えて出し直す。"""
    adults = str(adults)
    preset = {n: [api_item(h) for h in with_offers(hotels, by_people.get(n, {}))] for n in ("1", "2", "3", "4")} if by_people else {}
    first = with_offers(hotels, by_people.get(adults, {})) if by_people else with_offers(hotels, None)
    data = json.dumps({"date": default_date if by_people else "", "people": preset}, ensure_ascii=False).replace("</", "<\\/")
    ppl = "".join(f'<label class="pp"><input type="radio" name="adults" value="{n}"{" checked" if n == adults else ""}><span>{n}人</span></label>'
                  for n in ("1", "2", "3", "4"))
    sorts = "".join(f'<label class="pp"><input type="radio" name="sort" value="{k}"{" checked" if k == "walk" else ""}><span>{v}</span></label>'
                    for k, v in (("walk", "距離"), ("price", "値段"), ("rate", "レビュー")))
    hint = (f'{jdate(default_date)}の夜に{adults}人で1部屋に泊まれる宿が{len(first)}軒あります。会場に近い順です。' if by_people
            else "日付と人数を選ぶと、空いている宿に切り替わります。")
    return Markup(
        f'<form class="search rec" data-venue="{venue["slug"]}" data-limit="{limit}">'
        + (f'<p class="rec-label">泊まる夜</p><div class="search-people rec-nights" role="group" aria-label="泊まる夜">'
           + "".join(f'<label class="pp"><input type="radio" name="night" value="{d}"{" checked" if d == default_date else ""}><span>{md}の夜<small>{escape(l)}</small></span></label>' for d, md, l in nights)
           + '</div>' if nights else '') +
        f'<label class="search-date"><span>{"ほかの日" if nights else "泊まる日"}</span><input type="date" name="date" value="{default_date}" min="{TODAY.isoformat()}"></label>'
        f'<p class="rec-label">人数</p><div class="search-people" role="group" aria-label="人数">{ppl}</div>'
        f'<p class="rec-label">並べ方</p><div class="search-people rec-sort" role="group" aria-label="並べ方">{sorts}</div>'
        f'<script type="application/json" class="rec-data">{data}</script></form>'
        f'<div class="rec-result" aria-live="polite"><p class="hint">{hint}</p>{quick_cards(first, limit)}</div>'
        '<p class="search-note">会場から' + km(venue) + '以内の宿を楽天トラベルの空室から出しています。料金は1部屋に泊まるときの1人あたりの最安値です。</p>'
    )


def food_map(venue, spots, stays=None):
    """飲食店の位置を地図に出す。spotsの番号は表の番号と同じ。staysは宿の位置。"""
    pins = [{"n": i, "name": s["name"], "lat": s["lat"], "lng": s["lng"], "sub": f'{s.get("genre", "")}　{s.get("budget", "")}',
             "url": s["url"]} for i, s in enumerate(spots, 1) if s.get("lat") and s.get("lng")]
    if not pins:
        return Markup("")
    data = json.dumps({"venue": {"name": venue["name"], "lat": venue["lat"], "lng": venue["lng"]}, "spots": pins,
                       "stays": [{"name": h["name"], "lat": h["lat"], "lng": h["lng"]} for h in (stays or [])]},
                      ensure_ascii=False).replace("</", "<\\/")
    return Markup(f'<div class="map map-food" data-map=\'{escape(data)}\'></div>')


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
        '<p class="search-note">会場から' + km(venue) + '以内の宿を、楽天トラベルの空室から近い順に出します。料金は1人あたりの最安値です。</p>'
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


def shop_img(s):
    if not s.get("photo"):
        return ""
    return (f'<a class="shop-img" href="{escape(s["url"])}" rel="nofollow sponsored noopener" target="_blank" tabindex="-1">'
            f'<img src="{escape(s["photo"])}" alt="{escape(s["name"])}の料理" width="64" height="64" loading="lazy"></a>')


def restaurant_table(shops, limit=3, base="宿から", start=1, budget="予算"):
    rows = "".join(
        f'<tr><td><div class="shop">{shop_img(s)}<div><span class="no">{start + i}</span><a href="{escape(s["url"])}" rel="nofollow sponsored noopener" target="_blank">{escape(s["name"])}</a>'
        f'<span class="sub">{escape(s["genre"])}</span></div></div></td><td>{escape(s["budget"])}</td><td class="num">{dist_label(s["distance_m"])}</td></tr>'
        for i, s in enumerate(shops[:limit])
    )
    return Markup(f'<div class="table-wrap"><table><thead><tr><th>店</th><th>{budget}</th><th class="num">{base}</th></tr></thead>'
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
        toc.append({"id": hid, "text": unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()})
        return f'<h2 id="{hid}">{m.group(2)}</h2>'

    return H2_RE.sub(repl, body), toc


def breadcrumb_ld(crumbs):
    return json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": c["name"], "item": SITE["base_url"] + c["path"]}
                            for i, c in enumerate(crumbs)],
    }, ensure_ascii=False)


HERO_DIR = "images/hero"


def hero_tiles(stats, hotels, near):
    if stats:
        tiles = [("空いている宿", str(stats["one"]["open"]), f"/{stats['total']}軒"),
                 ("歩いて行ける宿の空き", str(stats["one"]["near"]), f"/{stats['near_total']}軒")]
        if stats.get("ratio"):
            tiles.append(("料金はイベントのない日の", f"{stats['ratio']}", "倍"))
        elif stats["one"].get("min"):
            tiles.append(("いちばん安い宿", f"{stats['one']['min']:,}", "円"))
        return tiles
    tiles = [("近くの宿", str(len(hotels)), "軒"), ("歩いて行ける宿", str(len(near)), "軒")]
    if hotels:
        tiles.append(("近い宿まで徒歩", str(walk_min(hotels[0]["distance_m"])), "分"))
    return tiles


A_TAG = re.compile(r'<a\b[^>]*>', re.S)


def nofollow_external(html):
    """サイトの外へ出るリンクには、すべて rel="nofollow" を付ける。"""
    def fix(m):
        tag = m.group(0)
        href = re.search(r'href=["\']([^"\']*)', tag)
        if not href or not href.group(1).startswith(("http://", "https://", "//")) or href.group(1).startswith(SITE["base_url"]):
            return tag
        rel = re.search(r'rel=(["\'])([^"\']*)\1', tag)
        if rel:
            if "nofollow" in rel.group(2).split():
                return tag
            return tag[:rel.start()] + f'rel="nofollow {rel.group(2)}"' + tag[rel.end():]
        return tag[:-1] + ' rel="nofollow">'
    return A_TAG.sub(fix, html)


def km(venue):
    r = venue.get("search_radius_km", 3.0)
    return f"{r:g}km"


def station_table(venue):
    rows = "".join(f"<tr><th>{escape(s['name'])}</th><td>{escape(s.get('line', ''))}</td><td>徒歩約{s['walk_min']}分</td></tr>"
                   for s in sorted(venue.get("stations", []), key=lambda s: s["walk_min"]))
    return Markup(f'<div class="table-wrap"><table><thead><tr><th>駅</th><th>路線</th><th>会場まで</th></tr></thead><tbody>{rows}</tbody></table></div>')


def hero_name(text):
    return re.sub(r'[\\/:*?"<>|#%&\s]+', "", text)[:60] + ".jpg"


def vslug(venue):
    """宿と空室のデータを置いている会場（有明アリーナなどはビッグサイトのものを使う）。"""
    return venue.get("hotel_area") or venue["slug"]


def load_hotels(venue):
    hotels = read_json(DATA / "hotels" / f"{vslug(venue)}.json", {"hotels": []})["hotels"]
    if venue.get("hotel_area"):
        # 距離をこの会場から測り直す
        hotels = [dict(h, distance_m=distance_m(venue["lat"], venue["lng"], h["lat"], h["lng"])) for h in hotels]
        hotels = sorted((h for h in hotels if h["distance_m"] <= venue.get("search_radius_km", 3.0) * 1000),
                        key=lambda h: h["distance_m"])[:venue.get("max_hotels", 200)]
    return hotels


def venue_summary(venue):
    hotels = load_hotels(venue)
    return {"slug": venue["slug"], "name": venue["name"], "area_label": venue.get("area_label", ""),
            "hotels": len(hotels), "near": sum(1 for h in hotels if h["distance_m"] <= 1000),
            "stations": venue.get("stations", [])}


AREA_GROUPS = [
    ("有明・お台場エリア", ["tokyo-big-sight", "ariake-arena", "tokyo-garden-theater", "toyota-arena-tokyo"]),
    ("水道橋・九段下エリア", ["tokyo-dome", "nippon-budokan"]),
    ("有楽町・東京駅エリア", ["tokyo-international-forum"]),
    ("両国エリア", ["ryogoku-kokugikan"]),
    ("原宿・渋谷エリア", ["yoyogi-national-gymnasium", "nhk-hall"]),
    ("千駄ヶ谷・青山エリア", ["japan-national-stadium"]),
    ("横浜・みなとみらいエリア", ["pacifico-yokohama", "k-arena-yokohama", "pia-arena-mm"]),
    ("新横浜エリア", ["yokohama-arena"]),
    ("千葉・幕張エリア", ["makuhari-messe"]),
]
VENUE_TAGS = {
    "tokyo-big-sight": ["展示会", "同人誌即売会", "アート"], "ariake-arena": ["ライブ", "スポーツ"],
    "tokyo-garden-theater": ["ライブ"], "tokyo-dome": ["ライブ", "大型イベント"], "nippon-budokan": ["ライブ"],
    "tokyo-international-forum": ["コンサート", "舞台"], "ryogoku-kokugikan": ["大相撲"],
    "yoyogi-national-gymnasium": ["ライブ", "スポーツ"], "nhk-hall": ["コンサート", "公開番組"],
    "japan-national-stadium": ["サッカー", "ライブ", "陸上"],
    "toyota-arena-tokyo": ["ライブ", "バスケットボール"], "makuhari-messe": ["展示会", "ライブ", "ゲーム"],
    "pacifico-yokohama": ["学会", "展示会", "コンサート"], "k-arena-yokohama": ["ライブ"], "pia-arena-mm": ["ライブ"],
    "yokohama-arena": ["ライブ", "スポーツ"],
}
SPORTS = re.compile(r"サッカー|Jリーグ|J1|マラソン|ラグビー|陸上|大相撲|リーグ|選手権|大会|試合|ホームゲーム|開幕戦|vs|VS|BOXING|ボクシング|ONE |格闘|バスケ|バレー|フィギュア|Championship|GAME\.|太極拳")


# 公式サイトの画面がないとき、開催概要に入れるジャンルの写真（ファイル名, 説明）
GENRE_PHOTOS = [
    (re.compile(r"バスケ|B\.LEAGUE|BASKETBALL", re.I), "バスケットボールの試合.jpg", "バスケットボールの試合のイメージ"),
]


def genre_photo(e):
    text = f"{e.get('name', '')} {e.get('content', '')}"
    for pattern, file, alt in GENRE_PHOTOS:
        if pattern.search(text):
            out = DIST / "images" / "photos" / file
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / "assets" / "photos" / file, out)
            return {"src": "/images/photos/" + quote(file), "alt": alt}
    return None


def card_image(v):
    """トップの会場カードに使う写真。会場の写真があれば切り抜いて使い、なければファーストビューの画像。"""
    src = v.get("hero_photos", {}).get("venue")
    path = ROOT / "assets" / "photos" / src if src else None
    if not path or not path.exists():
        return f"/{HERO_DIR}/{hero_name(v['name'] + 'に近いホテル')}"
    out = DIST / "images" / "venues" / f"{v['name']}の外観.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as im:
            im = im.convert("RGB")
            W, H = 640, 336
            r = max(W / im.width, H / im.height)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
            x, y = (im.width - W) // 2, (im.height - H) // 2
            im.crop((x, y, x + W, y + H)).save(out, "JPEG", quality=80, optimize=True, progressive=True)
    return f"/images/venues/{v['name']}の外観.jpg"


def home_data(ctxs):
    """トップページ用に、全会場をまとめた情報を作る。"""
    today = TODAY.isoformat()
    cards, all_up = {}, []
    for ctx in ctxs:
        v = ctx["venue"]
        offers = (ctx["sat_vacancy"] or {}).get("by_people", {}).get("1") or {}
        prices = [o["per_person"] for o in offers.values() if o.get("per_person")]
        nxt = next((e for e in ctx["events"] if e.get("public")), ctx["events"][0] if ctx["events"] else None)
        cards[v["slug"]] = {
            "slug": v["slug"], "name": v["name"], "area_label": v.get("area_label", ""), "tags": VENUE_TAGS.get(v["slug"], []),
            "hotels": len(ctx["hotels"]), "near": len(ctx["near_hotels"]),
            "nearest": walk_min(ctx["hotels"][0]["distance_m"]) if ctx["hotels"] else None,
            "stations": sorted(v.get("stations", []), key=lambda s: s["walk_min"])[:2],
            "min_price": min(prices) if prices else None, "next": nxt, "count": len(ctx["events"]),
            "img": card_image(v),
        }
        for e in ctx["events"]:
            all_up.append(dict(e, venue_slug=v["slug"], venue_name=v["name"], venue_kind=v.get("kind")))
    all_up.sort(key=lambda e: (e["start"], e["name"]))
    soon_end = (TODAY + timedelta(days=21)).isoformat()
    public = [e for e in all_up if e.get("public")]
    genres = [
        ("展示会・見本市", [e for e in all_up if e["venue_kind"] == "exhibition" and not e.get("public")]),
        ("同人誌・アート・ファンイベント", [e for e in all_up if e["venue_kind"] == "exhibition" and e.get("public")]),
        ("ライブ・コンサート", [e for e in all_up if e["venue_kind"] == "arena" and not SPORTS.search(e["name"])]),
        ("スポーツ・格闘技・相撲", [e for e in all_up if e["venue_kind"] == "arena" and SPORTS.search(e["name"])]),
    ]
    groups = [(g, [cards[s] for s in slugs if s in cards]) for g, slugs in AREA_GROUPS]
    groups = [(g, cs) for g, cs in groups if cs]
    all_series = [dict(sr, venue_slug=c["venue"]["slug"], venue_name=c["venue"]["name"]) for c in ctxs for sr in c["series"]]
    return {"series_public": [x for x in all_series if not x.get("trade")], "series_trade": [x for x in all_series if x.get("trade")],
            "groups": groups, "soon": [e for e in public if e["start"] <= soon_end][:15], "genres": genres,
            "total_events": len(all_up), "total_venues": len(cards), "saturday": ctxs[0]["saturday"]}


def multi_event_table(events, limit=None):
    """いくつかの会場のイベントをまとめた表。会場の列を付ける。"""
    rows = events[:limit] if limit else events
    if not rows:
        return Markup('<p class="note">これから開催されるイベントの情報を取得しています。</p>')
    body = "".join(
        f'<tr><td class="date">{period(e, br=True)}</td><td><a href="/{e["venue_slug"]}/{escape(e["slug"])}/">{escape(e["name"])}</a>'
        f'<span class="sub">{escape(e["venue_name"])}</span></td></tr>' for e in rows)
    return Markup('<div class="table-wrap"><table class="t-events"><thead><tr><th class="date">開催日</th><th>イベントと会場</th></tr>'
                  f"</thead><tbody>{body}</tbody></table></div>")


def top_search(cards, default_date):
    """トップページの検索。会場・日付・人数・並べ方を選ぶと、その場で空いている宿を出す。"""
    opts = "".join(f'<option value="{c["slug"]}">{escape(c["name"])}</option>' for _, cs in cards for c in cs)
    ppl = "".join(f'<label class="pp"><input type="radio" name="adults" value="{n}"{" checked" if n == "1" else ""}><span>{n}人</span></label>'
                  for n in ("1", "2", "3", "4"))
    sorts = "".join(f'<label class="pp"><input type="radio" name="sort" value="{k}"{" checked" if k == "walk" else ""}><span>{v}</span></label>'
                    for k, v in (("walk", "距離"), ("price", "値段"), ("rate", "レビュー")))
    return Markup(
        '<form class="search rec rec-top" data-limit="6">'
        f'<label class="search-date"><span>会場</span><select name="venue"><option value="">会場を選ぶ</option>{opts}</select></label>'
        f'<label class="search-date"><span>泊まる日</span><input type="date" name="date" value="{default_date}" min="{TODAY.isoformat()}"></label>'
        f'<p class="rec-label">人数</p><div class="search-people" role="group" aria-label="人数">{ppl}</div>'
        f'<p class="rec-label">並べ方</p><div class="search-people rec-sort" role="group" aria-label="並べ方">{sorts}</div>'
        '<script type="application/json" class="rec-data">{"date":"","people":{}}</script>'
        '<button type="submit" class="btn btn-primary btn-block">空いている宿を探す</button></form>'
        '<div class="rec-result" aria-live="polite"></div>'
        '<p class="search-note">楽天トラベルの空室から、会場の近くで泊まれる宿を出します。料金は1部屋に泊まるときの1人あたりの最安値です。</p>'
    )


def venue_context(venue):
    hotels = load_hotels(venue)
    events = read_json(DATA / "events" / f"{venue['slug']}.json", {"events": []})["events"]
    restaurants = read_json(DATA / "restaurants" / f"{vslug(venue)}.json", {"by_hotel": {}})["by_hotel"]
    lunch = (read_json(DATA / "restaurants" / f"{venue['slug']}.json", {}) or {}).get("lunch", [])
    # ランチは居酒屋より食堂やカフェなどを先に出す（居酒屋のランチは数が足りないときだけ）
    pub = [s for s in lunch if "居酒屋" in (s.get("genre") or "")]
    lunch = sorted([s for s in lunch if s not in pub], key=lambda s: s["distance_m"])[:8]
    lunch += sorted(pub, key=lambda s: s["distance_m"])[:max(0, 8 - len(lunch))]
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
        # 一般の人が来られるイベント（泊まりで来る人が多い）
        trade_series = any(sr.get("trade") for sr in series if sr["slug"] == e["series"])
        e["public"] = (bool(e["series"]) and not trade_series) or "一般" in (e.get("audience") or "")
    return {
        "series": series,
        "venue": venue,
        "hotels": hotels,
        "near_hotels": [h for h in hotels if h["distance_m"] <= 1000],
        "all_events": events,
        "events": upcoming,
        "public_events": [e for e in upcoming if e.get("public")],
        "trade_events": [e for e in upcoming if not e.get("public")],
        "restaurants": restaurants,
        "lunch": lunch,
        "shots": read_json(DATA / "shots" / f"{venue['slug']}.json", {}) or {},
        "saturday": sat.isoformat(),
        "sat_vacancy": read_json(DATA / "vacancy" / vslug(venue) / f"{sat.isoformat()}.json"),
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
         "breadcrumbs": [home, hub], "float_cta": {"href": "#search", "label": "日付と人数で空室を探す"},
         "hero": {"file": hero_name(f"{venue['name']}に近いホテル"), "title": venue["name"], "lead": "に近いホテル",
                  "photo": venue.get("hero_photos", {}).get("venue"),
                  "sub": venue["address"], "tiles": hero_tiles(None, ctx["hotels"], ctx["near_hotels"]),
                  "alt": f"{venue['name']}に近いホテルの数と会場までの徒歩時間"}},
        {"path": v + "hotels/", "template": "hotels.html",
         "title": f"{venue['name']}周辺のホテルを地図と比較表で選ぶ",
         "description": f"{venue['name']}から{km(venue)}以内のホテルを、地図と比較表で並べました。距離、料金、口コミの評価、大浴場の有無で並べ替えや絞り込みができます。",
         "breadcrumbs": [home, hub, {"name": "ホテルの比較", "path": v + "hotels/"}],
         "float_cta": {"href": v, "label": "おすすめのホテルを見る"}, "has_map": True},
        *[{"path": f"{v}{slug}/", "template": "people.html", "people": n, "people_label": label,
           "title": f"{venue['name']}近くのホテルに{label}で泊まる 1人あたりの料金と空室",
           "description": f"{venue['name']}の近くで{label}で1部屋に泊まれるホテルを、会場からの距離と1人あたりの料金で比べました。近い宿、安い宿、評価の高い宿のおすすめもまとめています。",
           "breadcrumbs": [home, hub, {"name": f"{label}で泊まる", "path": f"{v}{slug}/"}],
           "float_cta": {"href": "#best", "label": f"{label}で泊まれるおすすめを見る"}, "has_map": True}
          for slug, n, label in PEOPLE_PAGES],
        *[{"path": f"{v}{sr['slug']}/", "template": "series.html", "series": sr,
           "vacancy": read_json(DATA / "vacancy" / vslug(venue) / f"{sr['next']['start']}.json") if sr["next"] else None,
           "title": f"{sr['name']}（{sr['short']}）の会場に近いホテル {venue['name']}周辺で空いている宿",
           "description": (f"次の{sr['name']}（{sr['next']['name']}）は{period(sr['next'])}に{venue['name']}で開かれます。" if sr["next"]
                           else f"{sr['name']}は{venue['name']}で開かれるイベントです。")
                          + "会場に近いホテルの空室と1人あたりの料金を、人数を選ぶだけで確かめられます。",
           "hero": {"file": hero_name(f"{sr['short']}の会場に近いホテル"), "title": sr["name"], "photo": sr.get("hero_photo") or venue.get("hero_photos", {}).get("venue"),
                    "sub": (f"次回 {period(sr['next'])}　{venue['name']}" if sr["next"] else venue["name"]),
                    "tiles": hero_tiles(event_stats(ctx["hotels"], read_json(DATA / "vacancy" / vslug(venue) / f"{sr['next']['start']}.json"), None, None)
                                        if sr["next"] else None, ctx["hotels"], ctx["near_hotels"]),
                    "alt": f"{sr['name']}の会場に近いホテルの空き具合"},
           "breadcrumbs": [home, hub, {"name": f"{sr['short']}の宿", "path": f"{v}{sr['slug']}/"}],
           "float_cta": {"href": "#hotels", "label": "空いている近い宿を見る"}}
          for sr in ctx["series"]],
        {"path": v + "events/", "template": "events.html",
         "title": f"{venue['name']}の開催予定イベント一覧",
         "description": f"{venue['name']}でこれから開催される展示会や一般向けイベントを日付順にまとめています。イベントごとに会場に近いホテルと開催日の空室も確認できます。",
         "breadcrumbs": [home, hub, {"name": "開催予定イベント", "path": v + "events/"}], "float_cta": cta},
    ]
    if venue.get("guides"):
        pages += [
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
        ]
    for e in ctx["all_events"]:
        path = f"{v}{e['slug']}/"
        concurrent = [o for o in ctx["all_events"] if o is not e and o["start"] <= e["end"] and o["end"] >= e["start"]]
        days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days + 1
        vac = read_json(DATA / "vacancy" / vslug(venue) / f"{e['start']}.json") if e["end"] >= TODAY.isoformat() else None
        text = read_json(DATA / "texts" / venue["slug"] / f"{e['slug']}.json")
        hist = read_json(DATA / "vacancy_history" / vslug(venue) / f"{e['start']}.json")
        # 比べる相手は、同じ曜日の種類（金土の夜は週末、それ以外は平日）でイベントのない日
        kind = "weekend" if date.fromisoformat(e["start"]).weekday() in (4, 5) else "weekday"
        base_date = (read_json(DATA / "baseline" / f"{vslug(venue)}.json", {}) or {}).get(kind)
        base_vac = read_json(DATA / "vacancy" / vslug(venue) / f"{base_date}.json") if base_date else None
        st = event_stats(ctx["hotels"], vac, base_vac, hist) if vac else None
        common = {"event": e, "vacancy": vac, "text": text, "concurrent": concurrent[:12], "days": days, "credit_events": True,
                  "history": hist, "base_vacancy": base_vac, "base_kind": kind,
                  "hero": {"file": hero_name(f"{e['name']}の会場に近いホテル"), "title": e["name"], "photo": next((s.get("hero_photo") for s in ctx["series"] if s["slug"] == e.get("series") and s.get("hero_photo")), None) or venue.get("hero_photos", {}).get("event"),
                           "sub": f"{period(e)}　{venue['name']}", "tiles": hero_tiles(st, ctx["hotels"], ctx["near_hotels"]),
                           "alt": f"{e['name']}の会場に近いホテルの空き具合"}}
        pages.append(dict(common, **{
            "path": path, "template": "event.html", "noindex": bool(e.get("noindex")), "has_map": True,
            "title": (f"{e['name']}の会場に近いホテル {venue['name']}周辺で前泊にも使える宿" if is_trade(e) and e["start"] != e["end"]
                      else f"{e['name']}の会場に近いホテル {venue['name']}周辺の宿"),
            "description": (f"{e['name']}（{period(e)} {venue['name']}）の会場に近いホテルを、設営や前泊のある前日の夜から会期中の夜まで、"
                            "空室と1人あたりの料金で選べます。出張で何泊かするときの宿の取り方もまとめています。"
                            if is_trade(e) and e["start"] != e["end"] else
                            f"{e['name']}（{period(e)} {venue['name']}）の会場に近いホテルを、開催日の空室と1人あたりの料金で選べます。"
                            "人数を選ぶだけで泊まれる宿がわかり、日付を変えて空室を探すこともできます。"),
            "breadcrumbs": [home, hub, {"name": "開催予定イベント", "path": v + "events/"}, {"name": e["name"], "path": path}],
            "float_cta": {"href": "#hotels", "label": "空いている近い宿を見る"},
        }))
    return pages


def common_pages():
    home = {"name": "トップ", "path": "/"}
    return [
        {"path": "/", "template": "home.html", "is_home": True,
         "title": "ちか宿 イベント会場に近いホテルが見つかる", "h1": "イベント会場に近いホテルが見つかる",
         "description": "東京ビッグサイト、東京ドーム、日本武道館、幕張メッセなど首都圏の大型イベント会場に近いホテルを、会場からの距離と開催日の空室で探せます。展示会、ライブ、同人誌即売会、スポーツのイベントごとに宿をまとめています。",
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
    helpers = {"stay_nights": stay_nights, "is_trade": is_trade, "genre_photo": genre_photo, "photo": photo, "hotel_table": hotel_table, "hotel_cards": hotel_cards, "best_cards": best_cards,
               "compare_table": compare_table, "hotel_map": hotel_map, "people_tabs": people_tabs,
               "with_offers": with_offers, "price_of": price_of, "event_stats": event_stats, "best_picks": best_picks, "depart_table": depart_table,
               "open_time": open_time, "audience_label": audience_label,
               "event_table": event_table, "restaurant_table": restaurant_table, "dist_label": dist_label,
               "walk_min": walk_min, "yen": yen, "quick_cards": quick_cards, "people_switch": people_switch,
               "search_box": search_box, "chika": chika, "multi_event_table": multi_event_table, "top_search": top_search, "PEOPLE_PAGES": PEOPLE_PAGES, "banner": banner, "rec_box": rec_box, "food_map": food_map, "rank_tabs": rank_tabs, "station_table": station_table, "km": km, "more_buttons": more_buttons, "route_map": route_map, "book_url": book_url, "stars": stars, "chips": chips, "jdate": jdate, "period": period, "buildings": buildings,
               "site": SITE, "today": TODAY.isoformat(), "css_v": css_version()}
    all_venues = [v for v in venues() if v.get("publish", True)]
    main_venue = all_venues[0]
    main_ctx = venue_context(main_venue)
    venue_list = [venue_summary(v) for v in all_venues]
    helpers["venue_list"] = venue_list

    jobs = [(p, main_ctx) for p in common_pages()]
    for venue in all_venues:
        ctx = venue_context(venue)
        jobs += [(p, ctx) for p in pages_for(venue, ctx)]

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    helpers["home"] = home_data([venue_context(v) for v in all_venues])
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
        if page.get("hero"):
            hr = page["hero"]
            make_hero(DIST / HERO_DIR / hr["file"], hr["title"], hr["sub"], hr["tiles"], lead=hr.get("lead", "の会場に近いホテル"),
                      photo=next((d / hr["photo"] for d in (ROOT / "assets" / "photos", IMAGES) if hr.get("photo") and (d / hr["photo"]).exists()), None))
            hr["src"] = f"/{HERO_DIR}/{hr['file']}"
        side = {"venue": ctx["venue"], "events": (ctx["public_events"] + ctx["trade_events"])[:6], "people": PEOPLE_PAGES,
                "series": ctx["series"], "venues": venue_list}
        if page.get("is_home"):
            side = dict(side, events=helpers["home"]["soon"][:6], people=[], home=True)
        html = env.get_template("base.html").render(page=page, has_hotels=bool(ctx["hotels"]), side=side, **helpers)
        out = DIST / page["path"].lstrip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(nofollow_external(html), encoding="utf-8")

    side = {"venue": main_ctx["venue"], "events": (main_ctx["public_events"] + main_ctx["trade_events"])[:6], "people": PEOPLE_PAGES,
            "series": main_ctx["series"], "venues": venue_list}
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
        shutil.copytree(IMAGES, DIST / "images", dirs_exist_ok=True)
    # 公式サイトの画面の画像
    for d in (DATA / "shots").glob("*/"):
        shutil.copytree(d, DIST / "images" / "shots", dirs_exist_ok=True)
    # 空室検索（PHP）が使う宿の一覧
    shutil.copytree(ROOT / "static" / "api", DIST / "api")
    for venue in all_venues:
        ctx = venue_context(venue)
        (DIST / "api" / f"hotels-{venue['slug']}.json").write_text(json.dumps({
            "lat": venue["lat"], "lng": venue["lng"], "radius": venue.get("search_radius_km", 3.0), "moshimo": SITE.get("moshimo"),
            "hotels": [{"hotelNo": h["hotelNo"], "name": h["name"], "walk": walk_min(h["distance_m"]),
                        "distance": dist_label(h["distance_m"]), "image": h.get("image", ""),
                        "rate": h.get("review_avg"), "bath": bool(h.get("daiyoku") or h.get("onsen"))} for h in ctx["hotels"]],
        }, ensure_ascii=False), encoding="utf-8")

    urls = "".join(f"<url><loc>{SITE['base_url']}{quote(p['path'])}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>" for p, _ in jobs if not p.get("noindex"))
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE['base_url']}/sitemap.xml\n", encoding="utf-8")
    print(f"{len(jobs)}ページを書き出しました")


if __name__ == "__main__":
    main()
