"""イベント別ページの短い解説文をGemini APIで書く。

必要な環境変数: GEMINI_API_KEY（未設定なら何もしない）
1イベントにつき1回だけ生成して data/texts/ に保存し、毎日書き直すことはしない。
チャットでリライトしたいときは、保存されたJSONを直接直せばそのまま使われる。
"""
import json
import sys
import time
from datetime import date

import requests

from common import DATA, env, read_json, venues, write_json

MODEL = "gemini-2.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
MAX_PER_RUN = 80

PROMPT = """あなたはイベント会場の近くの宿を案内するサイトの編集者です。
次のイベントに泊まりがけで参加する人に向けて、短い解説を日本語で書いてください。

イベント名: {name}
会場: {venue}（{hall}）
開催日: {start} から {end}
開催時間: {hours}
対象: {audience}
入場料: {fee}
内容: {content}

書くもの（JSONで返す）
intro: このイベントがどんな催しで、どんな人が来るのかを2〜3文で。
stay: このイベントに合わせて宿を取る人へのアドバイスを2〜3文で。会期の長さ、対象（業界関係者か一般か）、開催時間から考えられることを書く。

守ること
・上に書いた情報だけを使い、来場者数や過去の実績など書かれていない事実を作らない
・情報が空欄の項目には触れない
・「〇〇：説明」のような書き方や箇条書きはしない。普通の文章で書く
・「このページでは」「いかがでしたか」のような前置きや締めは書かない
・です・ます調で、誇張した表現を使わない
"""


def generate(event, venue):
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(venue=venue["name"], **{
            k: event.get(k) or "" for k in ("name", "hall", "start", "end", "hours", "audience", "fee", "content")})}]}],
        "generationConfig": {
            "temperature": 0.6,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT", "properties": {"intro": {"type": "STRING"}, "stay": {"type": "STRING"}},
                               "required": ["intro", "stay"]},
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    res = requests.post(URL, params={"key": env("GEMINI_API_KEY")}, json=body, timeout=60)
    if res.status_code >= 400:
        raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")
    text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
    out = json.loads(text)
    return {"intro": out["intro"].strip(), "stay": out["stay"].strip(), "model": MODEL}


def main():
    if not env("GEMINI_API_KEY"):
        print("GeminiのAPIキーが未設定のため、解説文の生成を飛ばします")
        return 0
    made, failed = 0, False
    today = date.today().isoformat()
    pairs = [(venue, e) for venue in venues()
             for e in read_json(DATA / "events" / f"{venue['slug']}.json", {"events": []})["events"]]
    # どの会場でも、これから開催されるイベントを日付の近い順に書く
    pairs.sort(key=lambda p: (p[1]["end"] < today, p[1]["start"]))
    for venue, event in pairs:
        path = DATA / "texts" / venue["slug"] / f"{event['slug']}.json"
        if path.exists() or made >= MAX_PER_RUN:
            continue
        try:
            write_json(path, generate(event, venue))
            made += 1
            time.sleep(1)
        except Exception as exc:
            failed = True
            print(f"  {event['name']}: 解説文の生成に失敗 {exc}", file=sys.stderr)
    print(f"解説文を{made}件生成しました")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
