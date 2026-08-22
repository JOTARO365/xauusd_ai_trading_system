"""agents/roster_guard.py — LIVE allowlist assertion (roster-drift guard, user 08-22).

ปัญหา: combo ขึ้น LIVE เองได้หลายประตู (LLM router, human toggle, engine seed) → −EV combo แอบเทรดจริง
(เคส regime_momentum_fvg:XAUUSD LIVE สวน docstring "SHADOW-ONLY"). fix = allowlist ฝั่ง code
(LLM/dashboard แก้ไม่ได้) + assert ทุก cycle: LIVE combo ที่ไม่อยู่ allowlist → **force-demote SHADOW**
(demote-only เท่านั้น — ไม่เคย promote, ปลอดภัย). fail-soft, 0 token.

LIVE_ALLOWLIST = owner-approved (08-22): เฉพาะ combo ที่ยอมให้เทรดเงินจริง. เปลี่ยน = แก้ที่นี่ + owner เท่านั้น.
"""
from loguru import logger

from agents import shadow_switches as _sw

# owner-approved 08-22 — "algo_id:symbol". allowlist = อนุญาต live (ไม่ force-promote; combo อื่นถูก demote)
LIVE_ALLOWLIST = frozenset({
    "regime_momentum:XAUUSD",   # ~breakeven live (+423); on gold main engine (regime_tick)
    "macro_momentum:XAUUSD",    # t1.91 ตัวใกล้ significant สุด + ผ่าน S/R-gate
    "tsmom_d1:BTCUSD",          # BTC ผ่าน drift-null (timing skill จริง)
    "tsmom_d1:WTIUSD",          # WTI momentum validated edge (t15, multi-symbol-live-engine)
})


def _all_combos():
    """คืน {(algo_id,symbol): state} จาก switches file (อ่านตรง กัน API drift)."""
    import json
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "algo_switches.json")
    try:
        d = json.loads(open(p, encoding="utf-8").read())
    except Exception:
        return {}
    out = {}
    for k, v in d.items():
        if ":" in k and isinstance(v, str):
            a, s = k.split(":", 1)
            out[(a, s)] = v
    return out


def assert_roster():
    """เรียกทุก cycle + startup. LIVE combo ที่ไม่อยู่ allowlist → demote SHADOW + alert. คืน list ที่ demote. fail-soft."""
    demoted = []
    try:
        for (algo, sym), state in _all_combos().items():
            if state == "LIVE" and f"{algo}:{sym}" not in LIVE_ALLOWLIST:
                try:
                    _sw.set_state(algo, sym, "SHADOW")
                    demoted.append(f"{algo}:{sym}")
                    logger.warning("[ROSTER-GUARD] force-demote %s:%s LIVE→SHADOW (ไม่อยู่ LIVE_ALLOWLIST = roster-drift)" % (algo, sym))
                except Exception as e:
                    logger.debug("[ROSTER-GUARD] demote fail %s:%s — %s" % (algo, sym, e))
    except Exception as e:
        logger.debug("[ROSTER-GUARD] fail-soft: %s" % e)
    return demoted
