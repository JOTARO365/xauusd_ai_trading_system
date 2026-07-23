"""connectors/speech_log.py — บันทึก timestamp ของ speech events จาก ForexFactory calendar (Phase 2).

สะสม timestamp ของ speech ที่เห็นในปฏิทิน → data/speech_log.json (key = ชื่อ normalize → list ของ unix ts).
speech modal ใช้หา "ครั้งก่อน" (ts ที่ผ่านมาแล้ว) เพื่อโชว์ปฏิกิริยาราคา XAU จริง. 0 token, fail-soft.
เรียกเป็นระยะจาก dashboard collector daemon (throttle ~30 นาที).
"""
import datetime as dt
import json
import os
import re

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG = os.path.join(_BASE, "data", "speech_log.json")
_SPEECH_RE = re.compile(r"speaks?|speech|testif|remarks|press conf", re.I)


def norm_key(title):
    """ชื่อ event → key เทียบ speech ซ้ำ (lowercase, ยุบ space)."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def log_speeches():
    """fetch calendar → บันทึก timestamp ของ speech ทุกตัว (dedupe, เก็บ 20 ครั้งล่าสุด/ชื่อ). คืนจำนวนที่เพิ่ม."""
    try:
        from connectors.web_news import fetch_forexfactory_calendar
        evs = fetch_forexfactory_calendar(hours_ahead=168, include_all_us=True) or []
    except Exception:
        return 0
    try:
        rec = json.load(open(_LOG, encoding="utf-8"))
    except Exception:
        rec = {}
    added = 0
    for e in evs:
        title = e.get("title") or ""
        if not _SPEECH_RE.search(title):
            continue
        ts_iso = e.get("timestamp_iso")
        if not ts_iso:
            continue
        try:
            ts = int(dt.datetime.fromisoformat(ts_iso).timestamp())
        except Exception:
            continue
        k = norm_key(title)
        ent = rec.setdefault(k, {"title": title, "ts": []})
        if ts not in ent["ts"]:
            ent["ts"].append(ts)
            ent["ts"].sort()
            ent["ts"] = ent["ts"][-20:]                 # เก็บ 20 ครั้งล่าสุด
            added += 1
    if added:
        try:
            with open(_LOG, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
        except Exception:
            pass
    return added


if __name__ == "__main__":
    import sys
    sys.path.insert(0, _BASE)   # repo root — ให้ `from connectors.web_news` import ได้เมื่อรันไฟล์ตรงๆ
    sys.stdout.reconfigure(encoding="utf-8")
    n = log_speeches()
    print(f"logged {n} new speech timestamps → {_LOG}")
    try:
        rec = json.load(open(_LOG, encoding="utf-8"))
        print(f"total keys: {len(rec)}")
        for k, v in list(rec.items())[:8]:
            print(f"  {v['title'][:40]:40} × {len(v['ts'])}")
    except Exception:
        pass
