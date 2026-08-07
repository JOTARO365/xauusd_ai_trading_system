"""agents/algo_dir.py — per-algo direction mode (long / short / both).

Lets each algo be restricted to one side, dashboard-editable, without touching entry code
per-algo. Every entry path asks allowed(algo_id, direction) before opening; a signal on the
disallowed side is skipped (stood down). Default "both" = no filtering = unchanged behaviour,
so nothing changes until a mode is set.

Store: data/algo_dir_mode.json  { "<algo_id>": "long"|"short"|"both" }, hot-reloaded (60 s TTL),
fail-soft. tsmom_d1 seeds from config.TSMOM_DIR_MODE when no explicit entry exists (back-compat).
"""
import json
import os
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILE = os.path.join(_BASE, "data", "algo_dir_mode.json")
_TTL = 60
_cache = {"t": 0.0, "map": {}}

LONG, SHORT, BOTH = "long", "short", "both"
_VALID = {LONG, SHORT, BOTH}


def _load():
    now = time.time()
    if now - _cache["t"] < _TTL:
        return _cache["map"]
    try:
        with open(_FILE, encoding="utf-8") as f:
            m = json.load(f)
            _cache["map"] = m if isinstance(m, dict) else {}
    except Exception:
        _cache["map"] = {}
    _cache["t"] = now
    return _cache["map"]


def mode_of(algo_id, default=BOTH):
    """direction mode ของ algo. missing → default (both). tsmom_d1 seed จาก config.TSMOM_DIR_MODE."""
    m = _load().get(algo_id)
    if m in _VALID:
        return m
    if algo_id == "tsmom_d1":                       # back-compat: seed จาก flag เดิม
        try:
            import config as _cfg
            v = str(getattr(_cfg, "TSMOM_DIR_MODE", "long")).lower()
            return v if v in _VALID else default
        except Exception:
            return default
    return default


def allowed(algo_id, direction):
    """True ถ้าทิศ (BUY/SELL) นี้เข้าได้ตาม mode ของ algo. both→ทุกทิศ · long→BUY · short→SELL."""
    m = mode_of(algo_id)
    if m == BOTH:
        return True
    d = str(direction or "").upper()
    return (m == LONG and d == "BUY") or (m == SHORT and d == "SELL")


def set_mode(algo_id, mode):
    """เขียน mode (long/short/both). คืน True ถ้าสำเร็จ. invalidate cache ทันที."""
    mode = str(mode or "").lower()
    if mode not in _VALID or not algo_id:
        return False
    m = dict(_load())
    m[algo_id] = mode
    try:
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        tmp = _FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _FILE)
    except OSError:
        return False
    _cache["t"] = 0.0                                # force reload
    return True


def all_modes():
    """snapshot { algo_id: mode } (explicit เท่านั้น) — สำหรับ dashboard."""
    return dict(_load())
