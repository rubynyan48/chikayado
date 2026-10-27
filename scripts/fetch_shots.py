"""イベントの公式サイトの最初の画面を撮影して、開催概要に載せる画像にする。

いまは一般の人が行けるイベントだけを撮る。ライブ会場ではアーティストの写真が出ることが多いので、
人の顔が写っている画面は使わない。チケットサイトや会場のページは公式サイトではないので撮らない。
撮った画像は data/shots/<会場>/ に保存し、
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


# 公式サイトではないページ（会場、チケット販売）
NOT_OFFICIAL = re.compile(r"m-messe\.co\.jp|toyota-arena-tokyo\.jp|tokyo-dome\.co\.jp|jns-e\.com|ariake-arena\.tokyo|"
                          r"shopping-sumitomo-rd\.com|jpnsport\.go\.jp|nhk-fdn\.or\.jp|nipponbudokan\.or\.jp|t-i-forum\.co\.jp|"
                          r"eplus\.jp|t\.pia\.jp|l-tike\.com|diskgarage|ticket")
OVERRIDES = read_json(ROOT / "config" / "shot_overrides.json", {}) or {}
FACE_MODEL = ROOT / "assets" / "models" / "face_detection_yunet.onnx"


def has_faces(path):
    """写真の人の顔が写っていれば True（アニメの絵はほぼ反応しない）。"""
    try:
        import cv2
    except ImportError:
        return False
    im = cv2.imread(str(path))
    h, w = im.shape[:2]
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (w, h), 0.8)
    _, faces = det.detect(im)
    return faces is not None and any(f[2] * f[3] >= 30 * 30 for f in faces)


def official_url(e):
    for pattern, url in OVERRIDES.get("urls", {}).items():
        if re.search(pattern, e["name"]):
            return url
    url = e.get("url") or ""
    if not url or NOT_OFFICIAL.search(url):
        return ""
    return url if url.startswith("http") else "https://" + url


def file_name(text):
    return re.sub(r'[\\/:*?"<>|#%&\s]+', "", text)[:50] + "の公式サイト.jpg"


def is_public(e, patterns):
    return any(p.search(e["name"]) for p in patterns) or "一般" in (e.get("audience") or "")


def looks_blank(path):
    with Image.open(path) as im:
        st = ImageStat.Stat(im.convert("L"))
    return st.stddev[0] < 10


# エラーやロボット確認の画面に出る言葉。これが見えたら使わない
BAD_TEXT = ["Bad Gateway", "403 ERROR", "403 Forbidden", "404 Not Found", "Access Denied", "Just a moment",
            "セキュリティ検証", "接続を確認しています", "ロボットではありません", "request could not be satisfied"]


class Unusable(Exception):
    pass


def shoot(page, url, out):
    res = page.goto(url, wait_until="domcontentloaded", timeout=25000)
    if res is None or res.status >= 400:
        raise Unusable(f"HTTP {res.status if res else 'なし'}")
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
    text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''")
    if len(text.strip()) < 40 or any(w.lower() in text.lower() for w in BAD_TEXT):
        raise Unusable("エラーかロボット確認の画面")
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
    import time
    started = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="ja-JP",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        for venue in venues():
            live_venue = venue.get("kind") != "exhibition"
            slug = venue["slug"]
            events = read_json(DATA / "events" / f"{slug}.json", {"events": []})["events"]
            series = read_json(ROOT / "config" / "series" / f"{slug}.json", []) or []
            patterns = [re.compile(s["match"]) for s in series]
            index_path = DATA / "shots" / f"{slug}.json"
            index = read_json(index_path, {}) or {}
            folder = DATA / "shots" / slug
            folder.mkdir(parents=True, exist_ok=True)
            skip = [re.compile(x) for x in OVERRIDES.get("skip", [])]
            targets = [e for e in events if e["end"] >= today.isoformat() and official_url(e) and is_public(e, patterns)
                       and not any(p.search(e["name"]) for p in skip)]
            done = 0
            for e in targets:
                old = index.get(e["slug"])
                # 手で入れた画像はそのまま使う
                if old and old.get("manual"):
                    continue
                if old and old.get("taken", "") >= (today - timedelta(days=RETAKE_DAYS)).isoformat():
                    continue
                if done >= MAX_PER_RUN or time.time() - started > 20 * 60:
                    break
                url = official_url(e)
                out = folder / file_name(e["name"])
                page = ctx.new_page()
                try:
                    shoot(page, url, out)
                    if looks_blank(out):
                        out.unlink()
                        print(f"白い画面だったので使いません {e['name']}")
                    elif (live_venue or "音楽" in (e.get("content") or "")) and has_faces(out):
                        out.unlink()
                        print(f"人の顔が写っているので使いません {e['name']}")
                    else:
                        index[e["slug"]] = {"file": out.name, "url": url, "taken": today.isoformat()}
                        print(f"撮影 {e['name']}")
                except Unusable as ex:
                    print(f"使えない画面でした {e['name']} {ex}")
                    if old:
                        (folder / old["file"]).unlink(missing_ok=True)
                        del index[e["slug"]]
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
