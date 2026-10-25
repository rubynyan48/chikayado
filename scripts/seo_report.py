"""Search ConsoleとGA4のデータを取り出して、data/seo/ に保存する。

必要な環境変数: GOOGLE_SA_KEY（サービスアカウントの鍵JSONの中身）
GA4のプロパティIDは config/site.json の ga4_property_id に入れる（数字だけ）。

取り出すもの
- index_status.json   サイトマップの全URLのインデックス状況（URL検査API）
- search_pages.json   ページごとの表示回数・クリック数・平均順位（直近28日）
- search_queries.json 検索キーワードごとの表示回数・クリック数・平均順位（直近28日）
- ga4_pages.json      ページごとの表示回数と利用者数（直近28日）
"""
import json
import re
import sys
import time
from collections import Counter
from datetime import date, timedelta
from urllib.parse import quote, unquote

import requests

from common import DATA, SITE, env, write_json

SITE_URL = SITE["base_url"].rstrip("/") + "/"
OUT = DATA / "seo"


def session():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    info = json.loads(env("GOOGLE_SA_KEY"))
    creds = service_account.Credentials.from_service_account_info(info, scopes=[
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    ])
    print(f"サービスアカウント {info.get('client_email')} で接続します")
    return AuthorizedSession(creds)


def sitemap_urls():
    xml = requests.get(SITE_URL + "sitemap.xml", timeout=30).text
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def inspect_all(s, urls):
    """URL検査APIで1件ずつインデックス状況を調べる（1日2000件まで）。"""
    api = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
    out = []
    for i, u in enumerate(urls):
        r = s.post(api, json={"inspectionUrl": u, "siteUrl": SITE_URL, "languageCode": "ja"}, timeout=60)
        if r.status_code == 429:
            print("URL検査の上限に達したので、ここで止めます")
            break
        if r.status_code >= 400:
            out.append({"url": unquote(u), "error": f"HTTP {r.status_code} {r.text[:200]}"})
            continue
        res = r.json().get("inspectionResult", {}).get("indexStatusResult", {})
        out.append({"url": unquote(u), "verdict": res.get("verdict"), "coverage": res.get("coverageState"),
                    "last_crawl": res.get("lastCrawlTime"), "google_canonical": res.get("googleCanonical")})
        time.sleep(0.2)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(urls)}件を調べました")
    return out


def search_analytics(s, dims):
    api = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{quote(SITE_URL, safe='')}/searchAnalytics/query"
    end = date.today() - timedelta(days=2)
    body = {"startDate": (end - timedelta(days=27)).isoformat(), "endDate": end.isoformat(),
            "dimensions": dims, "rowLimit": 5000}
    r = s.post(api, json=body, timeout=60)
    r.raise_for_status()
    rows = r.json().get("rows", [])
    return [{**{d: unquote(k) for d, k in zip(dims, row["keys"])}, "clicks": row["clicks"], "impressions": row["impressions"],
             "ctr": round(row["ctr"], 4), "position": round(row["position"], 1)} for row in rows]


def ga4_pages(s, prop):
    api = f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport"
    body = {"dateRanges": [{"startDate": "28daysAgo", "endDate": "yesterday"}],
            "dimensions": [{"name": "pagePath"}], "metrics": [{"name": "screenPageViews"}, {"name": "activeUsers"}],
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}], "limit": 1000}
    r = s.post(api, json=body, timeout=60)
    r.raise_for_status()
    return [{"page": unquote(row["dimensionValues"][0]["value"]), "views": int(row["metricValues"][0]["value"]),
             "users": int(row["metricValues"][1]["value"])} for row in r.json().get("rows", [])]


def main():
    if not env("GOOGLE_SA_KEY"):
        print("GOOGLE_SA_KEY が未設定のため、Search ConsoleとGA4の取得を飛ばします")
        return 0
    s = session()
    today = date.today().isoformat()
    failed = False

    urls = sitemap_urls()
    print(f"サイトマップのURL {len(urls)}件のインデックス状況を調べます")
    status = inspect_all(s, urls)
    write_json(OUT / "index_status.json", {"checked": today, "urls": status})
    count = Counter(x.get("coverage") or x.get("error", "不明")[:40] for x in status)
    print("インデックス状況の内訳")
    for k, n in count.most_common():
        print(f"  {k}: {n}件")

    for name, dims in (("search_pages", ["page"]), ("search_queries", ["query"])):
        try:
            rows = search_analytics(s, dims)
            write_json(OUT / f"{name}.json", {"checked": today, "rows": rows})
            print(f"{name}: {len(rows)}行")
        except Exception as exc:
            failed = True
            print(f"{name} の取得に失敗 {exc}", file=sys.stderr)

    prop = str(SITE.get("ga4_property_id") or "").strip()
    if prop:
        try:
            rows = ga4_pages(s, prop)
            write_json(OUT / "ga4_pages.json", {"checked": today, "rows": rows})
            print(f"GA4: {len(rows)}ページ")
        except Exception as exc:
            failed = True
            print(f"GA4の取得に失敗 {exc}", file=sys.stderr)
    else:
        print("GA4のプロパティIDが未設定のため、GA4は飛ばします")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
