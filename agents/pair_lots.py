"""agents/pair_lots.py — lot ต่อคู่ กำหนดอิสระ (user 08-09), แก้จาก dashboard.

แก้ปัญหา contract ต่างกันต่อ symbol (ทอง 100 vs BTC 1) → global FIXED_LOT ใช้ไม่ได้ทุกคู่.
เก็บ data/pair_lots.json = {"XAUUSD": 0.3, "BTCUSD": 0.01, ...}. hot-reload. ว่าง = ใช้ FIXED_LOT global.
open_order อ่าน lot_for(symbol) เป็น fixed-lot ต่อคู่ (ก่อน global). FF (ถ้าเปิด+ทุน<floor) ยัง override เพื่อ safety.
pure, 0 token. logical symbol เป็น key (XAUUSD ไม่ใช่ GOLD#).
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pair_lots.json")
_cache = {"mtime": 0.0, "data": {}}


def _load():
    try:
        m = os.path.getmtime(_PATH)
        if m != _cache["mtime"]:
            _cache["data"] = json.loads(open(_PATH, encoding="utf-8").read()) or {}
            _cache["mtime"] = m
    except Exception:
        _cache["data"] = _cache.get("data") or {}
    return _cache["data"]


def lot_for(symbol, default=None):
    """lot ที่กำหนดของ symbol (logical). None = ไม่กำหนด (ใช้ default/global)."""
    try:
        v = _load().get(symbol)
        return float(v) if v is not None and float(v) > 0 else default
    except Exception:
        return default


def all_lots():
    return {k: v for k, v in _load().items() if not str(k).startswith("_")}


def set_lot(symbol, lot):
    """ตั้ง lot ของ symbol (lot<=0 หรือ None = ลบ). คืน True/False."""
    try:
        d = dict(_load())
        if lot is None or float(lot) <= 0:
            d.pop(symbol, None)
        else:
            d[symbol] = round(float(lot), 3)
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        open(_PATH, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2))
        _cache["mtime"] = 0.0                                  # force reload
        return True
    except Exception:
        return False
