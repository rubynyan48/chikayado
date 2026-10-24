"""会場のイベント情報（東京都オープンデータのCSV）を取得し、data/events/ に貯めていく。

CSVは約3か月先までの予定しか載らないため、取得のたびに新しいイベントを足し、
過去に取ったイベントは消さずに残す。内容が変わったイベントは上書きする。
"""
import csv
import io
import re
import sys
import unicodedata
from datetime import date

import requests

from common import DATA, read_json, venues, write_json

# CSVの列名は変わることがあるので、含まれる言葉で探す
COLUMNS = {
    "name": ["展示会名", "催事名", "イベント名", "名称"],
    "start": ["(開始)", "開始日", "開催開始"],
    "end": ["(終了)", "終了日", "開催終了"],
    "hall": ["利用施設", "会場", "ホール"],
    "hours": ["開催時間"],
    "audience": ["対象"],
    "fee": ["入場料", "料金"],
    "content": ["内容", "概要"],
    "organizer": ["主催", "連絡先"],
    "url": ["URL", "ＵＲＬ", "ホームページ"],
}


def decode(raw):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def find_columns(header):
    found = {}
    for key, words in COLUMNS.items():
        for i, col in enumerate(header):
            col_n = unicodedata.normalize("NFKC", col or "")
            if i in found.values():
                continue
            if any(unicodedata.normalize("NFKC", w) in col_n for w in words):
                # 「最終日の終了時間」を終了日と取り違えないようにする
                if key == "end" and ("時間" in col_n or "時刻" in col_n):
                    continue
                found[key] = i
                break
    return found


def parse_date(text, fallback_year=None):
    s = unicodedata.normalize("NFKC", text or "").strip()
    m = re.search(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return date(y, mo, d).isoformat()
    m = re.search(r"(\d{1,2})\D{1,2}(\d{1,2})", s)
    if m and fallback_year:
        mo, d = map(int, m.groups())
        return date(fallback_year, mo, d).isoformat()
    return None


def make_slug(name):
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"[\s　/\\?#%&<>\"'|:;,.。、・!！()（）\[\]［］「」『』【】~〜～*+=]+", "", s)
    return s[:60] or "event"


def format_hall(text):
    """「東1-3」のような書き方に「ホール」を補う。"""
    if re.match(r"^[東西南][0-9]", text) and "ホール" not in text:
        return text + "ホール"
    return text


def clean(text):
    s = unicodedata.normalize("NFKC", text or "").strip()
    return re.sub(r"\s+", " ", s)


def fetch_venue_events(venue):
    res = requests.get(venue["events_csv"], timeout=60)
    res.raise_for_status()
    rows = list(csv.reader(io.StringIO(decode(res.content))))
    # 列名の行を探す（先頭に説明行が入ることがあるため）
    header_i = next((i for i, r in enumerate(rows[:10]) if find_columns(r).keys() >= {"name", "start"}), None)
    if header_i is None:
        raise RuntimeError(f"CSVの列名が見つかりません: {rows[:3]}")
    cols = find_columns(rows[header_i])
    print("列の対応:", {k: rows[header_i][v] for k, v in cols.items()})

    def get(row, key):
        i = cols.get(key)
        return clean(row[i]) if i is not None and i < len(row) else ""

    events = []
    for row in rows[header_i + 1:]:
        name = get(row, "name")
        start = parse_date(get(row, "start"))
        if not name or not start:
            continue
        end = parse_date(get(row, "end"), int(start[:4])) or start
        if end < start:
            end = start
        events.append({
            "name": name,
            "start": start,
            "end": end,
            "hall": format_hall(get(row, "hall")),
            "hours": get(row, "hours"),
            "audience": get(row, "audience"),
            "fee": get(row, "fee"),
            "content": get(row, "content"),
            "organizer": get(row, "organizer"),
            "url": get(row, "url"),
        })
    return events


def merge(venue, fresh):
    path = DATA / "events" / f"{venue['slug']}.json"
    store = read_json(path, {"events": []})
    by_key = {(e["name"], e["start"][:4]): e for e in store["events"]}
    used_slugs = {e["slug"] for e in store["events"]}
    today = date.today().isoformat()
    added = 0
    for e in fresh:
        key = (e["name"], e["start"][:4])
        if key in by_key:
            old = by_key[key]
            old.update({k: v for k, v in e.items() if v})
            old["last_seen"] = today
            continue
        slug = make_slug(e["name"])
        if slug in used_slugs:
            slug = f"{slug}-{e['start'].replace('-', '')}"
        used_slugs.add(slug)
        e.update(slug=slug, first_seen=today, last_seen=today)
        by_key[key] = e
        added += 1
    events = sorted(by_key.values(), key=lambda e: (e["start"], e["name"]))
    write_json(path, {"venue": venue["slug"], "updated": today, "events": events})
    print(f"{venue['name']}: CSV {len(fresh)}件 新規 {added}件 合計 {len(events)}件")


def main():
    failed = False
    for venue in venues():
        if not venue.get("events_csv"):
            continue
        try:
            merge(venue, fetch_venue_events(venue))
        except Exception as exc:  # 1会場の失敗で全体を止めない
            failed = True
            print(f"{venue['name']}: イベント取得に失敗 {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
