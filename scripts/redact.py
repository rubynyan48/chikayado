"""実行ログからキーやサーバー情報を伏せ字にして、data/logs/latest.txt に追記する。

使い方: コマンド 2>&1 | python scripts/redact.py
"""
import os
import sys
from pathlib import Path

NAMES = ["RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY", "HOTPEPPER_API_KEY", "GEMINI_API_KEY",
         "HOST", "USER_ID", "DEST"]
secrets = sorted({os.environ[n] for n in NAMES if len(os.environ.get(n, "")) >= 4}, key=len, reverse=True)

log = Path(__file__).resolve().parent.parent / "data" / "logs" / "latest.txt"
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as f:
    for line in sys.stdin:
        for s in secrets:
            line = line.replace(s, "＊＊＊")
        sys.stdout.write(line)
        f.write(line)
