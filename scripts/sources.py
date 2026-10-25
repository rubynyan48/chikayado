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


SOURCES = {
    "nhk_hall": nhk_hall,
    "tokyo_dome": tokyo_dome,
    "ariake_arena": ariake_arena,
    "garden_theater": garden_theater,
    "yoyogi": yoyogi,
}
