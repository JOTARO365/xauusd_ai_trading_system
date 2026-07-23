"""agents/tsmom_manager.py — TSMOM-D1 directional engine (DESIGN_tsmom_integration.md).

edge เดียวที่ validated (~31 กลยุทธ์): time-series momentum รายวัน. position-based daily overlay —
ทำงาน 1 ครั้ง/แท่ง D1 ใหม่: signal ensemble (majority vote L=63/126/252, แท่งปิดแล้ว) → vol-target lot
(reuse algo_lot) → reconcile position ALGO-TSMOM (เปิด/ถือ/flip/ปิด). exit = signal flip (ไม่มี fixed TP);
SL = chandelier 3×ATR(D1) disaster stop. flag-gated (TSMOM_LIVE/SHADOW), fail-soft, 0 token.

⚠️ bypass DecisionMaker เหมือน ALGO path เดิม (deterministic). risk guards เดิม (daily-loss/MAX_RISK_PCT) binding.
"""
import config as _cfg

try:
    from loguru import logger
except Exception:                                           # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

COMMENT = "ALGO-TSMOM"
_last_d1_ts = None


def _enabled():
    return getattr(_cfg, "TSMOM_LIVE", False) or getattr(_cfg, "TSMOM_SHADOW", False)


def _d1_rates(count=300):
    import MetaTrader5 as mt5
    from connectors.price_feed import get_ohlcv
    rates = get_ohlcv(_cfg.SYMBOL, mt5.TIMEFRAME_D1, count)
    if rates is None or len(rates) < 260:
        return None
    return rates


def _signal(close):
    """ensemble majority vote. ใช้แท่ง D1 ปิดแล้ว (index -2; -1 = แท่งกำลังก่อตัว)."""
    import numpy as np
    Ls = [int(x) for x in str(getattr(_cfg, "TSMOM_LOOKBACKS", "63,126,252")).split(",")]
    ci = -2; votes = 0
    for L in Ls:
        if len(close) <= L - ci + 1:
            continue
        votes += int(np.sign(close[ci] - close[ci - L]))
    return "BUY" if votes > 0 else ("SELL" if votes < 0 else "FLAT")


def _state(action, detail, regime="TREND"):
    try:
        from agents.algo_state import write_state
        write_state(f"TSMOM-{action}", regime=regime, via="tsmom", detail=detail)
    except Exception:
        pass


def _open(direction, atr, shadow):
    from connectors.mt5_connector import open_order
    from agents.algo_sizing import algo_lot, capital_warning
    import regime_lib as R
    fixed = float(getattr(_cfg, "TSMOM_SL_PIPS", 0) or 0)   # >0 = SL คงที่ (บัญชีเล็ก); 0 = chandelier ATR
    tsmom_sl = int(fixed) if fixed > 0 else max(1, round(float(getattr(_cfg, "TSMOM_SL_ATR", 3.0)) * atr / R.POINT))
    tp_pips = 0                                              # no-TP mode (open_order รองรับ): trend-following exit ที่ flip
    # capital-aware SL: ทุนไม่พอสำหรับ SL TSMOM (chandelier กว้าง) → ใช้ manual auto-SL (แคบกว่า พอดีทุน) + เตือน
    sl_pips, sl_src = tsmom_sl, "chandelier 3×ATR D1"
    _warn, _wi = capital_warning(tsmom_sl)
    if _warn and getattr(_cfg, "TSMOM_SL_CAP_FALLBACK", True):
        # manual auto-SL = เดียวกับ ensure_sl_protection: AUTO_SL_PIPS หรือ default_sl_pips
        fb = int(getattr(_cfg, "AUTO_SL_PIPS", 0) or 0) \
            or int((getattr(_cfg, "MONEY_MANAGEMENT", {}) or {}).get("default_sl_pips", 2000))
        if 0 < fb < tsmom_sl:                              # ใช้เฉพาะถ้าแคบกว่าจริง (พอดีทุน)
            sl_pips, sl_src = fb, "manual auto-SL (capital fallback)"
            logger.warning(f"[TSMOM] ⚠️ ทุนไม่พอ SL TSMOM {tsmom_sl}p (risk {_wi['risk_pct']*100:.0f}% > เพดาน "
                           f"{_wi['threshold']*100:.0f}% · ทุน {_wi['equity']:,.0f}) → ใช้ manual auto-SL {fb}p แทน · "
                           f"เติมทุน ~{_wi['needed_equity']:,.0f} เพื่อใช้ SL TSMOM เต็ม (SL แคบ = edge หาย WR ต่ำ โดน noise รูด)")
        else:
            logger.warning(f"[TSMOM] ⚠️ ทุนไม่พอ SL TSMOM {tsmom_sl}p แต่ manual auto-SL ({fb}p) ไม่แคบกว่า "
                           f"→ เปิดด้วย SL TSMOM · ควรมีทุน ~{_wi['needed_equity']:,.0f}")
    elif _warn:                                             # fallback ปิด → พฤติกรรมเดิม (warn-only, เปิดด้วย SL กว้าง)
        logger.warning(f"[TSMOM] ⚠️ CAPITAL WARNING: risk {_wi['risk_pct']*100:.0f}%/ไม้ > เพดาน "
                       f"{_wi['threshold']*100:.0f}% · ทุน {_wi['equity']:,.0f} · ควรมี ~{_wi['needed_equity']:,.0f} "
                       f"— เปิด order ต่อ (fallback ปิด)")
    lot = algo_lot(sl_pips)
    res = open_order(direction, sl_pips, tp_pips, comment=COMMENT, lot=lot, shadow=shadow)
    ok = True if shadow else bool(isinstance(res, dict) and res.get("success"))
    logger.warning(f"[TSMOM] {'SHADOW ' if shadow else ''}OPEN {direction} SL={sl_pips}p ({sl_src}) lot={lot} → {res}")
    _fb_note = " · CAPITAL-FALLBACK เติมทุนเพื่อ SL TSMOM เต็ม" if sl_src.startswith("manual") else ""
    _state("OPEN" if ok else "OPEN-FAIL",
           f"{direction} · SL={sl_pips}p ({sl_src}) · lot={lot}{_fb_note}" + ("" if ok else " · เปิดไม่สำเร็จ (retry)"))
    return ok


def _close(pos, reason, shadow):
    if shadow:
        logger.warning(f"[TSMOM] SHADOW would-close #{pos['ticket']} ({reason})")
        return
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import _close_position
        objs = mt5.positions_get(ticket=pos["ticket"])
        if objs:
            _close_position(objs[0])
        logger.warning(f"[TSMOM] CLOSE #{pos['ticket']} ({reason})")
    except Exception as e:
        logger.error(f"[TSMOM] close #{pos.get('ticket')} failed: {e}")


def _reconcile(target, atr, shadow):
    from connectors.mt5_connector import get_open_positions
    tsmom = [p for p in (get_open_positions() or [])
             if str(p.get("comment") or "").startswith(COMMENT)]
    cur = tsmom[0] if tsmom else None
    if target == "FLAT":
        if cur:
            _close(cur, "signal FLAT", shadow); _state("FLAT", "signal เป็นกลาง → ปิด position")
        else:
            _state("STAND-DOWN", "signal FLAT · ไม่มี position")
        return True
    if cur is None:
        return _open(target, atr, shadow)                   # fail → ไม่ mark bar (retry รอบหน้า)
    if cur["direction"] == target:
        _state("HOLD", f"ถือ {target} ตามเทรนด์ D1 · #{cur['ticket']}"); return True
    _close(cur, f"flip → {target}", shadow)                  # ทิศกลับ → ปิด+เปิดตรงข้าม
    return _open(target, atr, shadow)


def manage_tsmom():
    """เรียกทุก cycle จาก node_position_mgmt. act เฉพาะแท่ง D1 ใหม่. fail-soft."""
    if not _enabled():
        return None
    global _last_d1_ts
    try:
        rates = _d1_rates()
        if rates is None:
            return None
        closed_ts = int(rates[-2]["time"])                  # แท่ง D1 ปิดล่าสุด
        if _last_d1_ts == closed_ts:
            return None                                      # ยังไม่มีแท่ง D1 ใหม่ → ไม่ทำซ้ำ
        import regime_lib as R
        target = _signal(rates["close"])
        atr = float(R.atr(rates["high"], rates["low"], rates["close"], 22)[-2])
        if atr <= 0:
            return None
        shadow = getattr(_cfg, "TSMOM_SHADOW", False) and not getattr(_cfg, "TSMOM_LIVE", False)
        if _reconcile(target, atr, shadow):                 # set bar เฉพาะเมื่อสำเร็จ (open fail → retry รอบหน้า)
            _last_d1_ts = closed_ts
        return {"target": target, "atr": atr, "shadow": shadow}
    except Exception as e:
        logger.debug(f"[TSMOM] manage error: {e}")
        return None
