"""会場の公式サイトのページをそのまま保存して、読み取り方を調べるための一時的な道具。"""
import hashlib
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "data" / "probe"
out.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def render(url, name):
    """JavaScriptで中身を作るページは、ブラウザで開いてから保存する。通信したURLも残す。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(user_agent=UA, locale="ja-JP")
        reqs = []
        page.on("request", lambda r: reqs.append(r.method + " " + r.url))
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        (out / f"{name}.html").write_text(page.content(), encoding="utf-8")
        (out / f"{name}.requests.txt").write_text("\n".join(reqs), encoding="utf-8")
        print("RENDER", len(page.content()), name, url)
        b.close()


for url in (ROOT / "scripts" / "probe_urls.txt").read_text().split():
    if url.startswith("render:"):
        url = url[7:]
        name = hashlib.md5(url.encode()).hexdigest()[:10]
        try:
            render(url, name)
        except Exception as e:
            print("ERR", name, url, type(e).__name__, e)
        continue
    name = hashlib.md5(url.encode()).hexdigest()[:10]
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ja"}, timeout=30)
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        (out / f"{name}.html").write_text(r.text, encoding="utf-8")
        print(r.status_code, len(r.text), name, url, r.url)
    except Exception as e:
        print("ERR", name, url, type(e).__name__)
