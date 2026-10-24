"""イベントの公式サイトの最初の画面を撮影して、開催概要に載せる画像にする。

いまは一般の人が行けるイベントだけを撮る。撮った画像は data/shots/<会場>/ に保存し、
一覧を data/shots/<会場>.json に書く。14日たったら撮り直す。
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageStat

from common import DATA, ROOT, read_json, venues, write_json

MAX_PER_RUN = 30
RETAKE_DAYS = 14
# クッキーの同意やお知らせの窓を閉じるときに押すボタンの文字
CLOSE_WORDS = ["同意", "同意する", "すべて同意", "許可", "OK", "Accept", "Accept All", "Agree", "閉じる", "Close", "×"]
# 画面に貼りついた同意の帯を消す
REMOVE_BANNERS = """
() => {
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if ((s.position === 'fixed' || s.position === 'sticky') && /cookie|クッキー|同意|プライバシー/i.test(el.innerText || '')) el.remove();
  }
}
"""


def file_name(text):
    return re.sub(r'[\\/:*?"<>|#%&\s]+', "", text)[:50] + "の公式サイト.jpg"


def is_public(e, patterns):
    return any(p.search(e["name"]) for p in patterns) or "一般" in (e.get("audience") or "")


def looks_blank(path):
    with Image.open(path) as im:
        st = ImageStat.Stat(im.convert("L"))
    return st.stddev[0] < 10


def shoot(page, url, out):
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    for w in CLOSE_WORDS:
        try:
            btn = page.get_by_role("button", name=w, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
        except Exception:
            pass
    try:
        page.evaluate(REMOVE_BANNERS)
    except Exception:
        pass
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    tmp = out.with_suffix(".png")
    page.screenshot(path=str(tmp))
    with Image.open(tmp) as im:
        im.convert("RGB").resize((1200, 750), Image.LANCZOS).save(out, "JPEG", quality=80, optimize=True, progressive=True)
    tmp.unlink()


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright がないので撮影を飛ばします")
        return
    today = date.today()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="ja-JP",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        for venue in venues():
            slug = venue["slug"]
            events = read_json(DATA / "events" / f"{slug}.json", {"events": []})["events"]
            series = read_json(ROOT / "config" / "series" / f"{slug}.json", []) or []
            patterns = [re.compile(s["match"]) for s in series]
            index_path = DATA / "shots" / f"{slug}.json"
            index = read_json(index_path, {}) or {}
            folder = DATA / "shots" / slug
            folder.mkdir(parents=True, exist_ok=True)
            targets = [e for e in events if e["end"] >= today.isoformat() and e.get("url") and is_public(e, patterns)]
            done = 0
            for e in targets:
                old = index.get(e["slug"])
                if old and old.get("taken", "") >= (today - timedelta(days=RETAKE_DAYS)).isoformat():
                    continue
                if done >= MAX_PER_RUN:
                    break
                url = e["url"] if e["url"].startswith("http") else "https://" + e["url"]
                out = folder / file_name(e["name"])
                page = ctx.new_page()
                try:
                    shoot(page, url, out)
                    if looks_blank(out):
                        out.unlink()
                        print(f"白い画面だったので使いません {e['name']}")
                    else:
                        index[e["slug"]] = {"file": out.name, "url": url, "taken": today.isoformat()}
                        print(f"撮影 {e['name']}")
                except Exception as ex:
                    print(f"撮影できません {e['name']} {type(ex).__name__}")
                finally:
                    page.close()
                done += 1
            # 終わったイベントの画像は消す
            live = {e["slug"] for e in targets}
            for k in list(index):
                if k not in live:
                    (folder / index[k]["file"]).unlink(missing_ok=True)
                    del index[k]
            write_json(index_path, index)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
