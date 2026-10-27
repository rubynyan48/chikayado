"""東京ビッグサイト以外の会場の、公式サイトのスケジュールを読み取る。

会場ごとにページの作りが違うので、読み取り方を1つずつ書いている。
どれも「name, start, end, hall, hours, audience, fee, content, organizer, url」を持つ辞書のリストを返す。
"""
import re
import time
import unicodedata
from datetime import date, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def clean(text):
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", s).strip()


def get_html(url):
    time.sleep(1.5)  # 相手のサイトに負担をかけないよう間をあける
    res = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ja"}, timeout=40)
    res.raise_for_status()
    if res.encoding in (None, "ISO-8859-1"):
        res.encoding = res.apparent_encoding
    return BeautifulSoup(res.text, "html.parser")


def months_ahead(n, today=None):
    """今月からn か月分の (年, 月)。"""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def guess_year(month, today=None):
    """年が書かれていない日付の年を決める。今より3か月以上前の月なら来年とみなす。"""
    today = today or date.today()
    return today.year + 1 if month < today.month - 3 else today.year


def event(name, start, end=None, **kw):
    e = {"name": clean(name), "start": start, "end": end or start, "hall": "", "hours": "", "audience": "一般",
         "fee": "", "content": "", "organizer": "", "url": ""}
    e.update({k: clean(v) if isinstance(v, str) else v for k, v in kw.items() if v})
    return e


def join_days(items):
    """1日ずつ並んだ同じ名前の公演を、続いている日ごとに1つのイベントにまとめる。"""
    items = sorted(items, key=lambda x: (x["name"], x["start"]))
    out = []
    for it in items:
        last = out[-1] if out else None
        if last and last["name"] == it["name"] and \
                date.fromisoformat(it["start"]) - date.fromisoformat(last["end"]) <= timedelta(days=1):
            last["end"] = max(last["end"], it["end"])
            for k in ("hours",):
                if it.get(k) and it[k] not in last.get(k, ""):
                    last[k] = (last[k] + " " + it[k]).strip()
            continue
        out.append(dict(it))
    return sorted(out, key=lambda x: x["start"])


def title_with_artist(artist, title):
    artist, title = clean(artist), clean(title)
    if "備考" in title:
        title = ""
    if not title:
        return artist
    if not artist or artist.lower() in title.lower() or len(artist) > 40 or "備考" in artist:
        return title
    return f"{artist} {title}"


# ---- 東京ドーム -------------------------------------------------------------
SKIP_DOME = re.compile(r"TOKYO DOME TOUR|ドームツアー")


def tokyo_dome(venue):
    items = []
    for y, m in months_ahead(5):
        soup = get_html(f"https://www.tokyo-dome.co.jp/dome/event?date={y}-{m:02d}")
        for li in soup.select("li.m-link-event__item"):
            dt = li.select_one(".m-link-event__dateText")
            md = re.search(r"(\d{1,2})月(\d{1,2})日", dt.get_text() if dt else "")
            if not md:
                continue
            d = date(guess_year(int(md.group(1))), int(md.group(1)), int(md.group(2))).isoformat()
            for c in li.select(".m-link-event__contentItem"):
                cat = clean(c.select_one(".m-badge").get_text()) if c.select_one(".m-badge") else ""
                t = c.select_one(".m-link-event__titleText")
                if not t:
                    continue
                name = clean(t.get_text())
                # 野球の公式戦は地元のファンが中心なので載せない
                if cat == "野球" or SKIP_DOME.search(name):
                    continue
                a = c.select_one("a.m-link-event__title")
                tm = c.select_one(".m-link-event__time")
                contact = c.select_one(".m-widget-accordionBox__content")
                items.append(event(name, d, hours=tm.get_text() if tm else "", content=cat,
                                   url=a["href"] if a and a.get("href", "").startswith("http") else "",
                                   organizer=contact.get_text(" ") if contact else ""))
    return join_days(items)


# ---- 有明アリーナ ------------------------------------------------------------
def ariake_arena(venue):
    items = []
    for tab in ("", "next/", "two/", "three/", "last/"):
        soup = get_html(f"https://ariake-arena.tokyo/event/{tab}")
        for li in soup.select("ul.event_detail_list > li"):
            days = [clean(s.get_text()) for s in li.select(".event_day span") if clean(s.get_text())]
            dates = []
            for s in days:
                md = re.match(r"(\d{1,2})\.(\d{1,2})", s)
                if md:
                    mo, d = int(md.group(1)), int(md.group(2))
                    dates.append(date(guess_year(mo), mo, d).isoformat())
            if not dates:
                continue
            artist = li.select_one(".event_name").get_text() if li.select_one(".event_name") else ""
            sub = li.select_one(".sub_title").get_text() if li.select_one(".sub_title") else ""
            info = {}
            for tr in li.select("table.detail_table tr"):
                th, td = tr.find("th"), tr.find("td")
                if th and td:
                    info[clean(th.get_text())] = td
            url = ""
            if "公式サイト" in info and info["公式サイト"].find("a"):
                url = info["公式サイト"].find("a").get("href", "")
            items.append(event(title_with_artist(artist, sub), min(dates), max(dates), hall="メインアリーナ",
                               hours=info["公演時間"].get_text(" ") if "公演時間" in info else "",
                               fee=info["料金"].get_text(" ") if "料金" in info else "",
                               organizer=info["お問合せ先"].get_text(" ") if "お問合せ先" in info else "",
                               url=url if url.startswith("http") else ""))
    # 同じ公演が2つのタブに出ることがあるので重ねない
    seen, out = set(), []
    for e in sorted(items, key=lambda x: x["start"]):
        k = (e["name"], e["start"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


# ---- 東京ガーデンシアター ----------------------------------------------------
def garden_theater(venue):
    base = "https://www.shopping-sumitomo-rd.com/tokyo_garden_theater/schedule/"
    items = []
    for y, m in months_ahead(6):
        soup = get_html(f"{base}?date={y}-{m:02d}")
        for li in soup.select("ul.list_schedule > li"):
            dates = []
            for ymd in li.select(".ymd"):
                mo, d = ymd.select_one(".m"), ymd.select_one(".d")
                if mo and d and mo.get_text().strip().isdigit() and d.get_text().strip().isdigit():
                    mo_i = int(mo.get_text())
                    # 年をまたぐ公演（12月の一覧に1月の日付など）に合わせて年を直す
                    yy = y + 1 if mo_i < m - 6 else y - 1 if mo_i > m + 6 else y
                    dates.append(date(yy, mo_i, int(d.get_text())).isoformat())
            if not dates:
                continue
            if re.fullmatch(r"(?i)private|非公開", clean(li.select_one(".title").get_text() if li.select_one(".title") else "")):
                continue  # 貸切の非公開イベント
            player = li.select_one(".player").get_text() if li.select_one(".player") else ""
            title = li.select_one(".title").get_text() if li.select_one(".title") else ""
            tag = li.select_one(".tag").get_text() if li.select_one(".tag") else ""
            a = li.find("a")
            name = title_with_artist(player, title)
            if re.fullmatch(r"(?i)private|非公開|貸切", name):
                continue
            items.append(event(name, min(dates), max(dates), content=tag,
                               url=a["href"] if a and a.get("href") else ""))
    seen, out = set(), []
    for e in sorted(items, key=lambda x: x["start"]):
        k = (e["name"], e["start"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


# ---- 国立代々木競技場 --------------------------------------------------------
def yoyogi(venue):
    items = []
    for tab, hall in ((59, "第一体育館"), (60, "第二体育館")):
        soup = get_html(f"https://www.jpnsport.go.jp/yoyogi/event/tabid/{tab}/Default.aspx")
        for tr in soup.select("table.event-calendar tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            md = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", tds[0].get_text())
            a = tds[1].find("a")
            if not md or not a:
                continue
            d = date(*map(int, md.groups())).isoformat()
            name = clean(a.get_text(" "))
            # 会員限定公演の注記は名前から外す
            name = re.sub(r"\s*\[[^\]]*\]\s*ファンクラブ会員限定公演$", "", name)
            items.append(event(name, d, hall=hall))
    return join_days(items)


# ---- NHKホール ---------------------------------------------------------------
def nhk_hall(venue):
    soup = get_html("https://www.nhk-fdn.or.jp/nhk_hall/event.html")
    items = []
    for box in soup.select("div.eventBox"):
        img = box.find("img", alt=re.compile(r"\d{4}年\d{1,2}月"))
        if not img:
            continue
        y, m = map(int, re.match(r"(\d{4})年(\d{1,2})月", img["alt"]).groups())
        for t in box.find_all("table"):
            rows = t.find_all("tr")
            if not rows or "日・曜日" in rows[0].get_text():
                continue
            cells = rows[0].find_all(["td", "th"])
            if len(cells) < 3:
                continue
            text = t.get_text(" ", strip=True)
            if "関係者" in text:
                continue  # 招待客だけの式典や大会
            days = []
            for r in rows:
                c = r.find(["td", "th"])
                md = re.match(r"\s*(\d{1,2})日", c.get_text() if c else "")
                if md:
                    days.append(date(y, m, int(md.group(1))).isoformat())
            if not days:
                continue
            name = clean(cells[1].get_text(" "))
            # 今月と来月の表は「開場・開演・終演」、それより先は「開演」だけ
            if len(cells) >= 6:
                hours = f"開場 {clean(cells[2].get_text(' '))} 開演 {clean(cells[3].get_text(' '))}"
            else:
                hours = f"開演 {clean(cells[2].get_text(' '))}"
            if max(days) < date.today().isoformat():
                continue
            items.append(event(name, min(days), max(days), hours=hours, content="整理券が必要な公開番組" if "整理券" in text else ""))
    return items


# ---- 国立競技場（MUFGスタジアム） -------------------------------------------
def national_stadium(venue):
    base = "https://jns-e.com/calendar/"
    pages = [base] + [f"{base}page/{y}{m:02d}/" for y, m in months_ahead(8)[1:]]
    items, seen = [], set()
    for url in pages:
        soup = get_html(url)
        for a in soup.find_all("a", href=re.compile(r"^/calendar/\d{8}-\d+/")):
            if a["href"] in seen:
                continue
            seen.add(a["href"])
            t = a.select_one(".p-schedule-calendar-list__title")
            if not t:
                continue
            cat = a.select_one(".p-schedule-calendar-list__category-label")
            meta = {}
            for row in a.select(".p-schedule-calendar-list__meta-row"):
                k, v = row.find("dt"), row.find("dd")
                if k and v:
                    meta[clean(k.get_text())] = v.get_text(" ", strip=True)
            dates = [date(int(y), int(mo), int(d)).isoformat()
                     for y, mo, d in re.findall(r"(\d{4})\s*(\d{1,2})/(\d{1,2})", meta.get("日程", ""))]
            if not dates or max(dates) < date.today().isoformat():
                continue
            items.append(event(t.get_text(" "), min(dates), max(dates), hours=meta.get("開始時間", ""),
                               organizer=meta.get("主催者", ""), content=cat.get_text() if cat else "",
                               url="https://jns-e.com" + a["href"]))
    return sorted(items, key=lambda e: e["start"])


# ---- トヨタアリーナ東京 ------------------------------------------------------
# Bリーグ・Dリーグの公式戦は地元のファンが中心なので載せない（チャンピオンシップなどは載せる）
SKIP_TOYOTA = re.compile(r"^(設営日|撤去日|PRIVATE|非公開)$|公演中止|開催中止|B\.LEAGUE 20\d\d-\d\d .+ vs |D\.LEAGUE .*REGULAR SEASON", re.I)


def toyota_arena(venue):
    base = "https://www.toyota-arena-tokyo.jp"
    items = []
    for y, m in months_ahead(6):
        soup = get_html(f"{base}/events/?year={y}&month={m}")
        for li in soup.select("li.bg-gray-f5"):
            spans = [clean(s.get_text()) for s in li.select("div.font-bold span")]
            md = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", spans[0] if spans else "")
            p = li.select_one("p.font-bold")
            if not md or not p:
                continue
            sub = p.find("span")
            artist = clean(sub.get_text()).replace("アーティスト:", "").strip() if sub else ""
            artist = re.sub(r"[、,]\s*(ゲストあり|ほか|他)$", "", artist)
            if sub:
                sub.extract()
            title = clean(p.get_text(" "))
            if SKIP_TOYOTA.search(title):
                continue
            info = li.select("p")[1:] if len(li.select("p")) > 1 else []
            hours, organizer = "", ""
            if info:
                parts = info[0].find_all("span", recursive=False)
                hours = clean(parts[0].get_text(" ")) if parts else ""
                organizer = clean(parts[1].get_text(" ")) if len(parts) > 1 else ""
            a = li.find("a", href=True)
            d = date(*map(int, md.groups())).isoformat()
            # 出演者が多いフェスは名前に入れない
            name = title if len(artist) > 40 else title_with_artist(artist, title)
            items.append(event(name, d, hall={"MAIN ARENA": "メインアリーナ", "SUB ARENA": "サブアリーナ"}.get(spans[1], spans[1]) if len(spans) > 1 else "", hours=hours,
                               organizer=organizer, content="バスケットボール" if re.search(r"B\.LEAGUE|バスケ", title) else "",
                               url=base + a["href"] if a else ""))
    return join_days(items)


# ---- 幕張メッセ --------------------------------------------------------------
def makuhari_messe(venue):
    base = "https://www.m-messe.co.jp"
    found = {}
    for y, m in months_ahead(7):
        for page in range(1, 8):
            soup = get_html(f"{base}/event/?month={y}{m:02d}&page={page}")
            lis = soup.select("li.eventInr")
            new = 0
            for li in lis:
                a = li.find("a", href=True)
                if not a or a["href"] in found:
                    continue
                dates = re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", li.select_one(".date").get_text() if li.select_one(".date") else "")
                if not dates:
                    continue
                dates = [date(*map(int, x)).isoformat() for x in dates]
                if max(dates) < date.today().isoformat():
                    continue
                t = li.select_one(".eventTit")
                tg = li.select_one(".target")
                cat = li.select_one(".category")
                found[a["href"]] = event(t.get_text(" ") if t else "", min(dates), max(dates),
                                         audience=clean(tg.get_text()).replace("対象", "").strip() if tg else "",
                                         content=cat.get_text() if cat else "", url=base + a["href"])
                new += 1
            if not new or not soup.find("a", href=f"javascript:pager({page + 1})"):
                break
    items = []
    for href, e in found.items():
        # 詳しいページから時間、会場のホール、料金、主催者、公式サイトを読む
        try:
            soup = get_html(e["url"])
        except Exception:
            items.append(e)
            continue
        def pick(sel):
            el = soup.select_one(sel)
            return el.get_text(" ") if el else ""
        hall = " ".join(clean(h.get_text(" ")) for h in soup.select("dl.facility .hall"))
        site = soup.select_one("dl.url a[href^=http]")
        e.update(event(e["name"], e["start"], e["end"], hall=hall, hours=pick("dl.time .main"),
                       audience=e["audience"], fee=pick("dl.person .price"), content=e["content"],
                       organizer=pick("dl.organizer dd"), url=site["href"] if site else e["url"]))
        items.append(e)
    return sorted(items, key=lambda x: (x["start"], x["name"]))


# ---- Kアリーナ横浜 -----------------------------------------------------------
def k_arena(venue):
    items = []
    for y, m in months_ahead(7):
        soup = get_html(f"https://k-arena.com/schedule/?y={y}&m={m}")
        for li in soup.select("li.schedule-list-item"):
            md = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", clean(li.select_one(".schedule-list-item__date").get_text()) if li.select_one(".schedule-list-item__date") else "")
            t = li.select_one(".schedule-list-item__title")
            if not md or not t:
                continue
            title = clean(t.get_text())
            if re.search(r"(?i)^private$|公演中止|開催中止|公演延期", title):
                continue
            artist = li.select_one(".schedule-list-item__artist")
            artist = clean(artist.get_text()) if artist else ""
            hours = li.select_one(".schedule-list-item__open-start")
            a = li.find("a", href=re.compile(r"/schedule/\d{8}"))
            name = title if len(artist) > 40 else title_with_artist(artist, title)
            items.append(event(name, date(*map(int, md.groups())).isoformat(), hours=hours.get_text(" ") if hours else "",
                               url=a["href"] if a else ""))
    seen, out = set(), []
    for e in items:
        if (e["name"], e["start"]) not in seen:
            seen.add((e["name"], e["start"]))
            out.append(e)
    return join_days(out)


# ---- 横浜アリーナ -------------------------------------------------------------
def yokohama_arena(venue):
    items = []
    for y, m in months_ahead(7):
        time.sleep(1.5)
        res = requests.get(f"https://www.yokohama-arena.co.jp/event/{y}{m:02d}?_format=json",
                           headers={"User-Agent": UA}, timeout=40)
        res.raise_for_status()
        data = res.json()
        for x in data if isinstance(data, list) else []:
            title = x.get("title") or ""
            if not x.get("date1") or re.search(r"(?i)^private$|公演中止|開催中止", title):
                continue
            hours = " ".join(f"開場 {o} 開演 {s}" for o, s in zip(x.get("ev_open") or [], x.get("ev_start") or []))
            if not hours and x.get("ev_start"):
                hours = "開演 " + " ".join(x["ev_start"])
            url = x.get("url") or ""
            items.append(event(title_with_artist(x.get("artist") or "", title), x["date1"], x.get("date2") or x["date1"],
                               hours=hours, organizer=x.get("company") or "",
                               url=url if url.startswith("http") else "https://www.yokohama-arena.co.jp" + (x.get("path") or "")))
    return join_days(items)


# ---- ぴあアリーナMM ----------------------------------------------------------
def pia_arena(venue):
    items = []
    for y, m in months_ahead(7):
        soup = get_html(f"https://pia-arena-mm.jp/event@p1={y}&p2={m:02d}.html")
        for a in soup.select("a"):
            dt = a.select_one(".event-list__date p")
            if not dt:
                continue
            md = re.match(r"(\d{1,2})\.(\d{1,2})", clean(dt.get_text()))
            parts = [clean(x.get_text()) for x in a.select(".title > *")]
            if not md or not parts or re.fullmatch(r"(?i)private|", parts[0]):
                continue
            mo, d = int(md.group(1)), int(md.group(2))
            yy = y + 1 if mo < m - 6 else y
            artist, title = (parts + [""])[:2]
            if re.search(r"公演中止|開催中止", artist + title):
                continue
            items.append(event(title_with_artist(artist, title) if title else artist, date(yy, mo, d).isoformat(),
                               url="https://pia-arena-mm.jp/" + a["href"].lstrip("./") if a.get("href") else ""))
    seen, out = set(), []
    for e in items:
        if (e["name"], e["start"]) not in seen:
            seen.add((e["name"], e["start"]))
            out.append(e)
    return join_days(out)


# ---- パシフィコ横浜（公式のGoogleカレンダー） ----------------------------------
PACIFICO_CALENDARS = [
    ("230f1639b8d54499f15caa874711a36b626933721072c1f9182d1282e4ddc586", "学会・会議", "関係者"),
    ("9e043fe7408716fce55f5f54f484074002eb939a192acdb50237cfb3ffac54fb", "大会・式典", "関係者"),
    ("78a66c66587ef8c39d987a3eb014082df0eff54f2445e9f837f94404fa0304e6", "イベント・コンサート", "一般"),
    ("6804e72a022c5b213349f94093988a11b91248a693afc0a30328b839ea2ed120", "展示会・見本市", "関係者"),
    ("737b19946fd8b839a17aaaa8ddc15f64af59045e36622b78fb50dcc31959992e", "物販・展示即売会", "一般"),
    ("1d7858363ffb40c9c82e272fc18b92528e0db30df3d6e159dfc503eeee6464a5", "公開講座", "一般"),
]


def pacifico(venue):
    today = date.today()
    limit = today + timedelta(days=240)
    items = []
    for cal, cat, aud in PACIFICO_CALENDARS:
        time.sleep(1.5)
        res = requests.get(f"https://calendar.google.com/calendar/ical/{cal}%40group.calendar.google.com/public/basic.ics",
                           headers={"User-Agent": UA}, timeout=40)
        res.raise_for_status()
        text = res.content.decode("utf-8").replace("\r\n ", "").replace("\n ", "")
        for block in text.split("BEGIN:VEVENT")[1:]:
            def field(k):
                mm = re.search(rf"^{k}[^:\n]*:(.*)$", block, re.M)
                return mm.group(1).strip() if mm else ""
            ds, de = field("DTSTART")[:8], field("DTEND")[:8]
            if not ds.isdigit():
                continue
            start = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
            end = date(int(de[:4]), int(de[4:6]), int(de[6:8])) if de.isdigit() else start
            if "VALUE=DATE" in block.split("DTEND")[-1][:20] or len(field("DTEND")) == 8:
                end = end - timedelta(days=1)  # 終日の予定は終わりの日が翌日になっている
            end = max(start, end)
            if end < today or start > limit or field("STATUS") == "CANCELLED":
                continue
            name = field("SUMMARY").replace("\\,", ",").replace("\\;", ";")
            if not name or re.search(r"(?i)^private$|中止", name):
                continue
            url = re.search(r'href="([^"]+)"', field("DESCRIPTION").replace("\\", ""))
            items.append(event(name, start.isoformat(), end.isoformat(), content=cat, audience=aud,
                               url=url.group(1) if url else ""))
    seen, out = set(), []
    for e in sorted(items, key=lambda x: (x["start"], x["name"])):
        if (e["name"], e["start"]) not in seen:
            seen.add((e["name"], e["start"]))
            out.append(e)
    return out


SOURCES = {
    "k_arena": k_arena,
    "yokohama_arena": yokohama_arena,
    "pia_arena": pia_arena,
    "pacifico": pacifico,
    "toyota_arena": toyota_arena,
    "makuhari_messe": makuhari_messe,
    "national_stadium": national_stadium,
    "nhk_hall": nhk_hall,
    "tokyo_dome": tokyo_dome,
    "ariake_arena": ariake_arena,
    "garden_theater": garden_theater,
    "yoyogi": yoyogi,
}
