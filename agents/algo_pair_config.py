"""agents/algo_pair_config.py — per-(algo × คู่) param override รวมศูนย์ (user 08-09).

ให้ tune แต่ละ algo ต่อคู่ได้ง่ายจากไฟล์เดียว data/algo_pair_config.json:
  { "confluence_15m": { "XAUUSD": {"SL_ATR": 1.2, "session": "13-17"} },
    "macro_momentum": { "BTCUSD": {"RR": 1.5} } }
ว่าง/ไม่มี key → คืน default (global) = ไม่เปลี่ยนพฤติกรรม. hot-reload (mtime cache). pure, 0 token.

⚠️ DISCIPLINE (quant-sat ch3): tune param ต่อคู่ไล่ backtest = curve-fitting. ใช้ได้เฉพาะ
  (ก) structural (session/TF/driver ตาม market microstructure) หรือ (ข) ผ่าน OOS validation.
  ห้ามไล่ +EV in-sample ต่อคู่โดยไม่ validate — จะได้ edge ปลอม live −EV.
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "algo_pair_config.json")
_cache = {"mtime": 0.0, "data": {}}


def _load():
    """re-read เมื่อไฟล์เปลี่ยน (hot-reload). fail-soft → {}."""
    try:
        m = os.path.getmtime(_PATH)
        if m != _cache["mtime"]:
            with open(_PATH, encoding="utf-8") as f:
                _cache["data"] = json.load(f) or {}
            _cache["mtime"] = m
    except Exception:
        _cache["data"] = _cache.get("data") or {}
    return _cache["data"]


def get(algo_id, symbol, param, default=None):
    """ค่า param ของ (algo, คู่) — override ถ้ามี ไม่งั้น default (global). symbol/algo case-sensitive ตาม json."""
    d = _load()
    try:
        return d.get(algo_id, {}).get(symbol, {}).get(param, default)
    except Exception:
        return default


def pair_overrides(algo_id, symbol):
    """dict override ทั้งหมดของ (algo, คู่) — สำหรับ dashboard/debug. {} ถ้าไม่มี."""
    return dict(_load().get(algo_id, {}).get(symbol, {}))


def all_config():
    """ทั้งไฟล์ — dashboard."""
    return dict(_load())
