"""
calibrator.py — Phase 1 probability calibrator (INERT — ยังไม่ wire เข้า decision/gate/order)

โหลด isotonic map ที่ fit ไว้ (data/calibrator_fit.json, จาก scripts/fit_calibrator.py) →
calibrate(raw_conf 0-100) → P(win) 0-1 ที่ "หมายความตามค่า" (แก้ LLM overconfident).

build ล่วงหน้ารอ data + validate. ⚠️ ยังไม่มีใครเรียกใน pipeline — enable = wire ที่ call site
(decision_maker) หลังผ่าน docs/VALIDATION_CHECKLIST.md, คุมด้วย config CALIBRATOR_ENABLED.
inference ใช้ numpy interp ล้วน (ไม่ต้อง sklearn ตอนบอทรัน).
"""
import json
from pathlib import Path

import numpy as np
from loguru import logger

_FIT   = Path(__file__).resolve().parent.parent / "data" / "calibrator_fit.json"
_cache = "unloaded"   # sentinel: ยังไม่โหลด


def _load():
    """คืน (x_knots, y_knots) ของ isotonic map หรือ None. โหลดครั้งเดียว fail-soft."""
    global _cache
    if _cache == "unloaded":
        try:
            d = json.load(open(_FIT, encoding="utf-8"))
            m = d["isotonic_map"]
            _cache = (np.array(m["x"], dtype=float), np.array(m["y"], dtype=float))
        except Exception as e:
            logger.debug(f"[CALIBRATOR] ยังไม่มี fit ({e}) — calibrate จะคืน None")
            _cache = None
    return _cache


def calibrate(raw_conf) -> float | None:
    """raw LLM confidence (0-100) → calibrated P(win) (0-1). None ถ้ายังไม่มี fit.
    np.interp บน isotonic knots = ตรงกับ sklearn IsotonicRegression.predict สำหรับค่าในช่วง."""
    if raw_conf is None:
        return None
    m = _load()
    if m is None:
        return None
    x, y = m
    return round(float(np.interp(float(raw_conf), x, y)), 4)


def reload():
    """ล้าง cache (เรียกหลัง re-fit)."""
    global _cache
    _cache = "unloaded"
