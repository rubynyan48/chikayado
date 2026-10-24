"""会場の公式サイトのページをそのまま保存して、読み取り方を調べるための一時的な道具。"""
import hashlib
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "data" / "probe"
out.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
for url in (ROOT / "scripts" / "probe_urls.txt").read_text().split():
    name = hashlib.md5(url.encode()).hexdigest()[:10]
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ja"}, timeout=30)
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        (out / f"{name}.html").write_text(r.text, encoding="utf-8")
        print(r.status_code, len(r.text), name, url, r.url)
    except Exception as e:
        print("ERR", name, url, type(e).__name__)
