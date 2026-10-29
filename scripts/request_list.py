"""Search Consoleで「インデックス登録をリクエスト」するURLの順番を決めて、data/seo/申請リスト.csv に書く。

URL検査で「登録されています」と出ていても、検索結果に一度も表示されていないページは、
実際には検索に出ていない可能性が高い。そうしたページと未登録のページを、
宿が埋まる前に見てもらいたい順（開催日が近い、まとめページ、会場ページ）に並べる。
"""
import csv
import json
from datetime import date, timedelta
from urllib.parse import unquote

from common import DATA, ROOT, read_json, venues

OUT = DATA / "seo" / "申請リスト.csv"


def main():
    today = date.today()
    status = (read_json(DATA / "seo" / "index_status.json", {}) or {}).get("urls", [])
    shown = {unquote(r["page"]).rstrip("/") + "/" for r in (read_json(DATA / "seo" / "search_pages.json", {}) or {}).get("rows", [])
             if r.get("impressions")}
    # ページの種類と開催日を、URLの形から引けるようにする
    kind = {}
    for v in venues():
        base = f"/{v['slug']}/"
        kind[base] = ("会場", None)
        for sr in read_json(ROOT / "config" / "series" / f"{v['slug']}.json", []) or []:
            kind[f"{base}{sr['slug']}/"] = ("まとめ", None)
        for e in read_json(DATA / "events" / f"{v['slug']}.json", {"events": []})["events"]:
            kind[f"{base}{e['slug']}/"] = ("イベント", e)
    # 転送しているURL（終わった回、まとめた構成展）は申請しない
    ht = ROOT / "dist" / ".htaccess"
    redirected = {l.split('"')[1] for l in ht.read_text(encoding="utf-8").splitlines() if l.startswith("Redirect 301")} if ht.exists() else set()
    rows = []
    for x in status:
        url = unquote(x["url"])
        if "/" + url.split("/", 3)[3] in redirected:
            continue
        path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
        indexed = x.get("verdict") == "PASS"
        if indexed and url in shown:
            continue  # 検索結果に出ているので申請はいらない
        k, e = kind.get(path, ("トップ" if path == "/" else "そのほか", None))
        if e and e["end"] < today.isoformat():
            continue  # 終わったイベントは後回しでよい
        # 点数が小さいほど先に申請する
        if k in ("トップ", "まとめ"):
            score, why = 0, f"{k}のページ"
        elif k == "会場":
            score, why = 1, "会場のページ"
        elif e:
            days = (date.fromisoformat(e["start"]) - today).days
            trade = any(w in (e.get("audience") or "") for w in ("商談", "関係者"))
            if days <= 7:
                score, why = 2, "開催まで1週間以内"
            elif days <= 45:
                score, why = 3 if trade or (e.get("end") != e.get("start")) else 4, f"開催まで{days}日"
            else:
                score, why = 5, f"開催まで{days}日"
            if trade:
                why += "（業界向け・連泊が多い）"
        else:
            score, why = 6, "そのほかのページ"
        state = "登録済みだが検索に一度も出ていない" if indexed else (x.get("coverage") or "未確認")
        rows.append((score, e["start"] if e else "", url, state, why))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["順番", "URL", "状態", "先に申請する理由", "開催日"])
        for i, (score, start, url, state, why) in enumerate(rows, 1):
            w.writerow([i, url, state, why, start])
    print(f"申請リスト {len(rows)}件（登録済みだが検索に出ていない {sum(r[3].startswith('登録済み') for r in rows)}件）")


if __name__ == "__main__":
    main()
