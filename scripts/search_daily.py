"""検索の表示回数とクリック数を日ごとに取り出す（落ちた日を見るため）。"""
from common import DATA, write_json
from seo_report import search_analytics, session
from datetime import date

s = session()
rows = search_analytics(s, ["date"])
write_json(DATA / "seo" / "search_daily.json", {"checked": date.today().isoformat(), "rows": rows})
for r in rows:
    print(r["date"], "表示", r["impressions"], "クリック", r["clicks"], "順位", r["position"])
