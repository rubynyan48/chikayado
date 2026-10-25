"""IndexNow（Bing、Yandexなど）に、新しいページと更新されたページを知らせる。

Googleは対応していない。鍵は static/<鍵>.txt に置いてあり、サイトの一番上で公開される。
送ったURLと日付は data/seo/indexnow.json に残し、新しいURLは毎回、ほかは7日ごとに送り直す。
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

from common import DATA, ROOT, SITE, read_json, write_json

API = "https://api.indexnow.org/indexnow"
RESEND_DAYS = 7


def find_key():
    for p in (ROOT / "static").glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{32}", p.stem) and p.read_text().strip() == p.stem:
            return p.stem
    return None


def main():
    key = find_key()
    if not key:
        print("IndexNowの鍵ファイルがないため飛ばします")
        return 0
    sitemap = ROOT / "dist" / "sitemap.xml"
    if not sitemap.exists():
        print("サイトマップがないため飛ばします")
        return 0
    urls = re.findall(r"<loc>([^<]+)</loc>", sitemap.read_text(encoding="utf-8"))
    state_path = DATA / "seo" / "indexnow.json"
    state = read_json(state_path, {}) or {}
    today = date.today()
    limit = (today - timedelta(days=RESEND_DAYS)).isoformat()
    send = [u for u in urls if state.get(u, "") < limit]
    if not send:
        print("IndexNowに送るURLはありません")
        return 0
    host = SITE["base_url"].split("//", 1)[1].rstrip("/")
    body = {"host": host, "key": key, "keyLocation": f"{SITE['base_url'].rstrip('/')}/{key}.txt", "urlList": send}
    r = requests.post(API, json=body, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=60)
    print(f"IndexNowに{len(send)}件を送りました HTTP {r.status_code} {r.text[:200]}")
    if r.status_code in (200, 202):
        for u in send:
            state[u] = today.isoformat()
        # サイトマップから消えたURLは忘れる
        state = {u: d for u, d in state.items() if u in set(urls)}
        write_json(state_path, state)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
