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

from common import DATA, SITE, env, read_json, write_json

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
    xml = requests.get(SITE_URL + "sitemap.xml", timeout=30).content.decode("utf-8")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def inspect_one(s, u):
    api = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
    for attempt in range(3):
        try:
            r = s.post(api, json={"inspectionUrl": u, "siteUrl": SITE_URL, "languageCode": "ja"}, timeout=40)
        except Exception as exc:
            err = type(exc).__name__
            continue
        if r.status_code == 429:
            time.sleep(10)
            err = "HTTP 429"
            continue
        if r.status_code >= 400:
            return {"url": unquote(u), "error": f"HTTP {r.status_code} {r.text[:200]}"}
        res = r.json().get("inspectionResult", {}).get("indexStatusResult", {})
        return {"url": unquote(u), "verdict": res.get("verdict"), "coverage": res.get("coverageState"),
                "last_crawl": res.get("lastCrawlTime"), "google_canonical": res.get("googleCanonical")}
    return {"url": unquote(u), "error": err}


def inspect_all(s, urls, today, workers=5):
    """URL検査APIでインデックス状況を調べる（1日2000件、1分600件まで）。5件ずつ同時に問い合わせる。"""
    from concurrent.futures import ThreadPoolExecutor
    started = time.time()
    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(lambda u: inspect_one(s, u), urls)):
            out.append(res)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(urls)}件を調べました（{round(time.time() - started)}秒）")
            if time.time() - started > 20 * 60:
                print(f"時間がかかりすぎたので {i + 1}件で止めます（残りは次回）")
                break
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

    for name, dims in (("search_pages", ["page"]), ("search_queries", ["query"]), ("search_daily", ["date"])):
        try:
            rows = search_analytics(s, dims)
            write_json(OUT / f"{name}.json", {"checked": today, "rows": rows})
            print(f"{name}: {len(rows)}行")
        except Exception as exc:
            failed = True
            print(f"{name} の取得に失敗 {exc}", file=sys.stderr)

    urls = sitemap_urls()
    # 前回の結果を引き継ぎ、まだ調べていないURLと、インデックスされていないURLを先に調べる
    old = {x["url"]: x for x in (read_json(OUT / "index_status.json", {}) or {}).get("urls", [])}
    def priority(u):
        o = old.get(unquote(u))
        if not o:
            return 0
        if o.get("verdict") != "PASS":
            return 1
        return 2
    order = sorted(urls, key=priority)
    print(f"サイトマップのURL {len(urls)}件のうち、未調査{sum(priority(u) == 0 for u in urls)}件と未登録を優先して調べます")
    fresh = inspect_all(s, order, today)
    for x in fresh:
        x["checked"] = today
        old[x["url"]] = x
    live = {unquote(u) for u in urls}
    status = [x for k, x in old.items() if k in live]
    write_json(OUT / "index_status.json", {"checked": today, "urls": status})
    count = Counter(x.get("coverage") or x.get("error", "不明")[:40] for x in status)
    print("インデックス状況の内訳")
    for k, n in count.most_common():
        print(f"  {k}: {n}件")

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
