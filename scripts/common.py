"""取得スクリプトと生成スクリプトで共通に使う処理。"""
import json
import math
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"

SITE = json.loads((CONFIG / "site.json").read_text(encoding="utf-8"))
REFERER = SITE["base_url"] + "/"


def venues():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((CONFIG / "venues").glob("*.json"))]


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def distance_m(lat1, lng1, lat2, lng2):
    """2点間の直線距離（メートル）。"""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


_last_call = {"t": 0.0}


def polite_get(url, params, headers=None, min_interval=1.2, retries=3):
    """間隔をあけてGETする。429や5xxは少し待って取り直す。404はNoneを返す。"""
    for attempt in range(retries):
        wait = min_interval - (time.time() - _last_call["t"])
        if wait > 0:
            time.sleep(wait)
        _last_call["t"] = time.time()
        res = requests.get(url, params=params, headers=headers or {}, timeout=30)
        if res.status_code == 404:
            return None
        if res.status_code in (429, 500, 502, 503) and attempt < retries - 1:
            time.sleep(5 * (attempt + 1))
            continue
        if res.status_code >= 400:
            # キーなどの秘密情報はログに出さない
            raise RuntimeError(f"HTTP {res.status_code}: {res.text[:300]}")
        return res
    return None


def env(name):
    value = os.environ.get(name, "").strip()
    return value or None
