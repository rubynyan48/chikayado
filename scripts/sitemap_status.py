"""Search Consoleに登録したサイトマップ（sitemap.xmlとfeed.xml）を、Googleがどう読んだかを書き出す。"""
import json
from urllib.parse import quote

from common import DATA, write_json
from seo_report import SITE_URL, session


def main():
    s = session()
    r = s.get(f"https://searchconsole.googleapis.com/webmasters/v3/sites/{quote(SITE_URL, safe='')}/sitemaps", timeout=60)
    r.raise_for_status()
    items = r.json().get("sitemap", [])
    for x in items:
        print(json.dumps({k: x.get(k) for k in ("path", "type", "isPending", "lastSubmitted", "lastDownloaded", "errors", "warnings", "contents")},
                         ensure_ascii=False))
    write_json(DATA / "seo" / "sitemaps.json", items)


if __name__ == "__main__":
    main()
