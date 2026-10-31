"""予約サイトへのクリックが、どのページのどのリンクから出たかをGA4から取り出す。

GA4の拡張計測が自動で記録する外部リンクのクリック（click イベント）を使う。
結果は data/seo/ga4_clicks.json と画面に出す。直近14日、今日の分も含む。
"""
import json
from urllib.parse import unquote

from common import DATA, SITE, env, write_json
from seo_report import session


def run(s, prop, body):
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport", json=body, timeout=60)
    r.raise_for_status()
    return r.json().get("rows", [])


def main():
    if not env("GOOGLE_SA_KEY"):
        print("GOOGLE_SA_KEY が未設定です")
        return
    s = session()
    prop = str(SITE["ga4_property_id"])
    rows = run(s, prop, {
        "dateRanges": [{"startDate": "14daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "dateHourMinute"}, {"name": "pagePath"}, {"name": "linkDomain"}, {"name": "linkUrl"},
                       {"name": "sessionSource"}, {"name": "deviceCategory"}],
        "metrics": [{"name": "eventCount"}],
        "dimensionFilter": {"filter": {"fieldName": "eventName", "stringFilter": {"value": "click"}}},
        "orderBys": [{"dimension": {"dimensionName": "dateHourMinute"}, "desc": True}], "limit": 500})
    out = []
    for r in rows:
        d = [x["value"] for x in r["dimensionValues"]]
        t = d[0]
        out.append({"time": f"{t[4:6]}/{t[6:8]} {t[8:10]}:{t[10:12]}", "page": unquote(d[1]), "domain": d[2],
                    "url": d[3][:160], "source": d[4], "device": d[5], "count": int(r["metricValues"][0]["value"])})
    for o in out:
        print(o["time"], o["device"], o["source"], o["domain"], o["page"])
    write_json(DATA / "seo" / "ga4_clicks.json", out)
    print(f"外部リンクのクリック {len(out)}行")


if __name__ == "__main__":
    main()
