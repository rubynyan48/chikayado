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


def hotel_cards(hotels, limit=6, vacancy=None, checkin=None):
    """宿を1軒ずつ、大きな写真と予約ボタンで見せる。"""
    out = []
    for h in hotels[:limit]:
        vac = (vacancy or {}).get(h["hotelNo"])
        rows = [f'<tr><th>会場まで</th><td>直線{dist_label(h["distance_m"])}（{badge(h["distance_m"])}）</td></tr>']
        if h.get("station"):
            rows.append(f'<tr><th>最寄り駅</th><td>{escape(h["station"])}駅</td></tr>')
        if vac:
            rows.append(f'<tr><th>{jdate(checkin, False)}の料金</th><td>1泊{yen(vac["total"])}から<span class="sub">大人1名の最安プラン</span></td></tr>')
        elif h.get("min_charge"):
            rows.append(f'<tr><th>料金の目安</th><td>{yen(h["min_charge"])}から</td></tr>')
        if h.get("review_avg") and h.get("review_count"):
            rows.append(f'<tr><th>評価</th><td>{float(h["review_avg"]):.2f}（{int(h["review_count"]):,}件）</td></tr>')
        img = f'<img src="{escape(h["image"])}" alt="{escape(h["name"])}" loading="lazy">' if h.get("image") else ""
        access = f'<p class="hotel-access">{escape(h["access"])}</p>' if h.get("access") else ""
        out.append(
            f'<section class="hotel"><h3>{escape(h["name"])}</h3>{img}'
            f'<table class="hotel-facts"><tbody>{"".join(rows)}</tbody></table>{access}'
            f'<div class="book"><p>予約はこちら</p><a class="btn btn-primary btn-block" href="{escape(book_url(h, vac))}" '
            f'rel="nofollow sponsored noopener" target="_blank">楽天トラベルで空室と料金を見る</a></div></section>'
        )
    return Markup("".join(out))


def ruler(hotels):
    """会場からの直線距離を1本のものさしに並べた図。"""
    if not hotels:
        return Markup("")
    w, h = 680, 270
    left, right, axis_y, max_m = 40, 650, 190, 3000

    def x(m):
        return left + (right - left) * min(m, max_m) / max_m

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="会場から各ホテルまでの直線距離">',
        f'<rect x="{left}" y="{axis_y - 120}" width="{x(1000) - left:.1f}" height="120" fill="#FFF6CC"/>',
        f'<text x="{left + 8}" y="{axis_y - 92}" font-size="22" font-weight="700" fill="#7A5E00">歩いて行ける目安</text>',
        f'<line x1="{left}" y1="{axis_y}" x2="{right}" y2="{axis_y}" stroke="#1B2633" stroke-width="2"/>',
    ]
    for m in range(0, max_m + 1, 500):
        tall = m % 1000 == 0
        parts.append(f'<line x1="{x(m):.1f}" y1="{axis_y}" x2="{x(m):.1f}" y2="{axis_y + (10 if tall else 6)}" stroke="#1B2633" stroke-width="{2 if tall else 1}"/>')
        if tall:
            label = "会場" if m == 0 else f"{m // 1000}km"
            parts.append(f'<text x="{x(m):.1f}" y="{axis_y + 38}" font-size="22" font-weight="700" text-anchor="middle" fill="#1B2633">{label}</text>')
    placed = []
    for hotel in hotels:
        cx = x(hotel["distance_m"])
        level = 0
        while any(abs(cx - px) < 20 and lv == level for px, lv in placed):
            level += 1
        if level > 7:
            continue
        placed.append((cx, level))
        color = "#12507A" if hotel["distance_m"] <= 1000 else "#7E8C99"
        parts.append(f'<circle cx="{cx:.1f}" cy="{axis_y - 18 - level * 22}" r="10" fill="{color}" stroke="#fff" stroke-width="2"><title>{escape(hotel["name"])}（{dist_label(hotel["distance_m"])}）</title></circle>')
    parts.append(f'<path d="M{left} {axis_y - 4} l-10 -20 h20 z" fill="#F5C518" stroke="#1B2633" stroke-width="1.5"/>')
    parts.append(f'<text x="{right}" y="{h - 10}" font-size="18" text-anchor="end" fill="#5B6875">点ひとつが1軒のホテル</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


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

H2_RE = re.compile(r"<h2>(.*?)</h2>", re.S)


def add_toc(body):
    toc = []

    def repl(m):
        n = len(toc) + 1
        toc.append({"id": f"s{n}", "text": re.sub(r"<[^>]+>", "", m.group(1)).strip()})
        return f'<h2 id="s{n}">{m.group(1)}</h2>'

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
    return {
        "venue": venue,
        "hotels": hotels,
        "near_hotels": [h for h in hotels if h["distance_m"] <= 1000],
        "all_events": events,
        "events": upcoming,
        "restaurants": restaurants,
    }


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
         "breadcrumbs": [home, hub], "float_cta": {"href": "#hotels", "label": "近い順のホテルを見る"}},
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
        {"path": v + "events/", "template": "events.html",
         "title": f"{venue['name']}の開催予定イベント一覧",
         "description": f"{venue['name']}でこれから開催される展示会や一般向けイベントを日付順にまとめています。イベントごとに会場に近いホテルと開催日の空室も確認できます。",
         "breadcrumbs": [home, hub, {"name": "開催予定イベント", "path": v + "events/"}], "float_cta": cta},
    ]
    for e in ctx["all_events"]:
        path = f"{v}{e['slug']}/"
        vac = read_json(DATA / "vacancy" / venue["slug"] / f"{e['slug']}.json")
        text = read_json(DATA / "texts" / venue["slug"] / f"{e['slug']}.json")
        pages.append({
            "path": path, "template": "event.html", "event": e, "vacancy": vac, "text": text,
            "title": f"{e['name']}に近いホテル {venue['name']}周辺の宿",
            "description": f"{e['name']}（{period(e)} {venue['name']}）に泊まりで行く人向けに、会場に近いホテルを距離順にまとめました。"
                           + ("開催初日に空室のある宿と料金も毎日更新しています。" if vac else ""),
            "breadcrumbs": [home, hub, {"name": "開催予定イベント", "path": v + "events/"}, {"name": e["name"], "path": path}],
            "float_cta": {"href": "#hotels", "label": "空室のあるホテルを見る" if vac else "会場に近いホテルを見る"},
            "credit_events": True,
        })
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


def main():
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    helpers = {"photo": photo, "ruler": ruler, "hotel_table": hotel_table, "hotel_cards": hotel_cards,
               "event_table": event_table, "restaurant_table": restaurant_table, "dist_label": dist_label,
               "walk_min": walk_min, "yen": yen, "jdate": jdate, "period": period, "buildings": buildings,
               "site": SITE, "today": TODAY.isoformat()}
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
        html = env.get_template("base.html").render(site=SITE, page=page, has_hotels=bool(ctx["hotels"]))
        out = DIST / page["path"].lstrip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")

    shutil.copy(ROOT / "static" / "style.css", DIST / "style.css")
    for extra in (ROOT / "static").iterdir():
        if extra.is_file() and extra.name != "style.css":
            shutil.copy(extra, DIST / extra.name)  # Search Consoleの確認ファイルなど
    if IMAGES.exists():
        shutil.copytree(IMAGES, DIST / "images")

    urls = "".join(f"<url><loc>{SITE['base_url']}{p['path']}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>" for p, _ in jobs)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE['base_url']}/sitemap.xml\n", encoding="utf-8")
    print(f"{len(jobs)}ページを書き出しました")


if __name__ == "__main__":
    main()
