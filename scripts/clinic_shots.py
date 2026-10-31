"""クリニックの公式サイトの最初の画面を撮影する。data/shots/clinics/ に保存し、30日たったら撮り直す。"""
from datetime import date, timedelta

from common import DATA, clinics, read_json, write_json
from fetch_shots import Unusable, has_faces, shoot

RETAKE_DAYS = 30


def main():
    from playwright.sync_api import sync_playwright
    folder = DATA / "shots" / "clinics"
    folder.mkdir(parents=True, exist_ok=True)
    index_path = DATA / "shots" / "clinics.json"
    index = read_json(index_path, {}) or {}
    today = date.today()
    urls = {}
    for c in clinics():
        if c.get("shot_url"):
            urls.setdefault(c["shot_url"], c["group"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="ja-JP",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        for url, group in urls.items():
            old = index.get(url)
            if old and old.get("taken", "") > (today - timedelta(days=RETAKE_DAYS)).isoformat():
                continue
            out = folder / f"{group.replace(' ', '')}の公式サイト.jpg"
            page = ctx.new_page()
            try:
                shoot(page, url, out)
                faces = has_faces(out)
                index[url] = {"file": "clinics/" + out.name, "taken": today.isoformat(), "faces": faces}
                print("撮影", group, "顔あり" if faces else "")
            except (Unusable, Exception) as exc:
                print("撮影できません", group, type(exc).__name__, exc)
            finally:
                page.close()
        browser.close()
    write_json(index_path, index)


if __name__ == "__main__":
    main()
