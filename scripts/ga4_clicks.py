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
    if r.status_code != 200:
        print("GA4のエラー", r.status_code, r.text[:500])
        return None
    return r.json().get("rows", [])


def main():
    if not env("GOOGLE_SA_KEY"):
        print("GOOGLE_SA_KEY が未設定です")
        return
    s = session()
    prop = str(SITE["ga4_property_id"])
    dims_sets = [
        ["dateHourMinute", "pagePath", "linkDomain", "linkUrl", "sessionSource", "deviceCategory"],
        ["dateHourMinute", "pagePath", "linkDomain", "linkUrl"],
        ["dateHour", "pagePath", "linkUrl"],
    ]
    for dims in dims_sets:
        rows = run(s, prop, {
        "dateRanges": [{"startDate": "14daysAgo", "endDate": "today"}],
            "dimensions": [{"name": n} for n in dims],
            "metrics": [{"name": "eventCount"}],
            "dimensionFilter": {"filter": {"fieldName": "eventName", "stringFilter": {"value": "click"}}},
            "orderBys": [{"dimension": {"dimensionName": dims[0]}, "desc": True}], "limit": 500})
        if rows is not None:
            break
    out = []
    for r in rows or []:
        d = dict(zip(dims, (x["value"] for x in r["dimensionValues"])))
        t = d.get("dateHourMinute") or d.get("dateHour", "") + "00"
        out.append({"time": f"{t[4:6]}/{t[6:8]} {t[8:10]}:{t[10:12]}", "page": unquote(d.get("pagePath", "")), "domain": d.get("linkDomain", ""),
                    "url": d.get("linkUrl", "")[:160], "source": d.get("sessionSource", ""), "device": d.get("deviceCategory", ""),
                    "count": int(r["metricValues"][0]["value"])})
    for o in out:
        print(o["time"], o["device"], o["source"], o["domain"], o["page"])
    write_json(DATA / "seo" / "ga4_clicks.json", out)
    # どこから来た人が、どのページに着いたか（AIの回答から来た人を見分けるため）
    rows = run(s, prop, {
        "dateRanges": [{"startDate": "14daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "sessionSource"}, {"name": "landingPage"}],
        "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}, {"name": "averageSessionDuration"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}], "limit": 300}) or []
    print("--- 来た場所と着いたページ（直近14日） ---")
    for r in rows:
        d = [x["value"] for x in r["dimensionValues"]]
        m = [x["value"] for x in r["metricValues"]]
        print(d[0], unquote(d[1])[:70], "訪問", m[0], "しっかり見た", m[1], "平均", round(float(m[2])), "秒")
    print(f"外部リンクのクリック {len(out)}行")


if __name__ == "__main__":
    main()
