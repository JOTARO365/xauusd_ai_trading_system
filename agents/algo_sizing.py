"""agents/algo_sizing.py — P-E: lot ไม้ ALGO risk-based ตามทุน (DESIGN_algo_v2). flag REGIME_SR_SIZING.

risk คงที่ต่อทุน: lot = equity × RISK_PCT / (sl_pips × pip_value), cap MAX_RISK_PCT + clamp MIN/MAX_LOT.
→ พอร์ตโต lot โต (risk % คงที่), พอร์ตเล็ก floor ที่ MIN_LOT. reuse _calc_pip_value + MONEY_MANAGEMENT เดิม
(สูตรเดียวกับ calculate_lot_size auto branch) แต่ **เฉพาะไม้ ALGO** ไม่แตะ LOT_MODE global.

flag OFF → คืน None → open_order/place_pending_order คำนวณเอง (fixed 0.01 เดิม). deterministic, 0 token.
"""
import config as _cfg

try:
    from loguru import logger
except Exception:                                           # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)


def _equity_pipval(equity=None):
    """ดึง (equity, pip_value) จาก MT5 (reuse โดย algo_lot + standdown). คืน (None, None) ถ้าไม่ได้."""
    try:
        from connectors.mt5_connector import _calc_pip_value
        if equity is None:
            import MetaTrader5 as mt5
            acc = mt5.account_info()
            equity = float(acc.equity) if acc else None
        if not equity or equity <= 0:
            return None, None
        pip_value = _calc_pip_value(_cfg.SYMBOL)
        return (equity, pip_value) if pip_value and pip_value > 0 else (None, None)
    except Exception:
        return None, None


def standdown_for_size(sl_pips, equity=None):
    """Small-account safety guard. คืน (skip: bool, info: dict).
    skip=True เมื่อ: เปิดที่ MIN_LOT แล้วเสี่ยง > ALGO_MAX_TRADE_RISK_PCT (min-lot ใหญ่เกินทุน+SL นี้)
    → ข้ามไม้แทน over-risk. flag OFF / คำนวณไม่ได้ → skip=False (fail-open, ไม่บล็อก; มี MAX_RISK_PCT cap รอง)."""
    if not getattr(_cfg, "ALGO_SIZE_STANDDOWN", False):
        return False, {"reason": "flag-off"}
    try:
        sl_pips = float(sl_pips)
        if sl_pips <= 0:
            return False, {"reason": "bad-sl"}
        eq, pip_value = _equity_pipval(equity)
        if eq is None:
            return False, {"reason": "no-metrics"}          # fail-open (ไม่บล็อกตอน MT5 มีปัญหา)
        ceiling = float(getattr(_cfg, "ALGO_MAX_TRADE_RISK_PCT", 0.02))
        min_lot = float(getattr(_cfg, "MIN_LOT", 0.01))
        risk_at_min = (min_lot * sl_pips * pip_value) / eq   # % ทุนที่เสี่ยงถ้าเปิด MIN_LOT
        skip = risk_at_min > ceiling
        return skip, {"reason": "over-risk" if skip else "ok", "risk_pct": risk_at_min,
                      "ceiling": ceiling, "equity": eq, "sl_pips": sl_pips}
    except Exception as e:
        logger.debug(f"[ALGO-STANDDOWN] fail-open: {e}")
        return False, {"reason": "error"}


def capital_warning(sl_pips, equity=None):
    """แจ้งเตือนทุนไม่พอ (risk/ไม้ ที่ MIN_LOT เกินเพดาน) — ไม่บล็อก แค่เตือน (คล้าย margin call).
    คืน (warn: bool, info). warn=True เมื่อ risk_at_min_lot > ALGO_MAX_TRADE_RISK_PCT. needed = ทุนที่ทำให้ถึงเพดาน."""
    try:
        sl_pips = float(sl_pips)
        eq, pip_value = _equity_pipval(equity)
        if eq is None or sl_pips <= 0:
            return False, {}
        thr = float(getattr(_cfg, "ALGO_MAX_TRADE_RISK_PCT", 0.02))
        min_lot = float(getattr(_cfg, "MIN_LOT", 0.01))
        risk = (min_lot * sl_pips * pip_value) / eq
        needed = (min_lot * sl_pips * pip_value) / thr if thr > 0 else 0.0
        return (risk > thr), {"risk_pct": risk, "threshold": thr, "equity": eq,
                              "needed_equity": needed, "sl_pips": sl_pips}
    except Exception as e:
        logger.debug(f"[CAPITAL-WARN] {e}")
        return False, {}


def algo_lot(sl_pips, equity=None, confidence_scale=1.0):
    """คืน lot risk-based (clamped) หรือ None ถ้า flag OFF / คำนวณไม่ได้ (→ fallback fixed).
    equity: override (เทสต์); ปกติดึงจาก account.equity."""
    if not getattr(_cfg, "REGIME_SR_SIZING", False):
        return None
    try:
        sl_pips = float(sl_pips)
        if sl_pips <= 0:
            return None
        from connectors.mt5_connector import _calc_pip_value
        if equity is None:
            import MetaTrader5 as mt5
            acc = mt5.account_info()
            equity = float(acc.equity) if acc else None
        if not equity or equity <= 0:
            return None
        pip_value = _calc_pip_value(_cfg.SYMBOL)             # value/pip/lot ในสกุลบัญชี (gold USD ≈ 1.0)
        if pip_value <= 0:
            return None
        risk_pct = float(getattr(_cfg, "REGIME_SR_RISK_PCT", 0.005))
        risk_amount = equity * risk_pct * max(0.0, min(1.0, float(confidence_scale)))
        max_risk = equity * float(getattr(_cfg, "MAX_RISK_PCT", 0.05))   # hard cap เดิม
        if max_risk > 0:
            risk_amount = min(risk_amount, max_risk)
        lot = round(risk_amount / (sl_pips * pip_value), 2)
        clamped = max(_cfg.MIN_LOT, min(lot, _cfg.MAX_LOT))
        logger.debug(f"[ALGO-SIZE] equity={equity:.2f} risk={risk_pct:.1%} SL={sl_pips}p pv={pip_value} "
                     f"→ lot {lot} (clamp {clamped})")
        return clamped
    except Exception as e:
        logger.debug(f"[ALGO-SIZE] fallback (fixed): {e}")
        return None
