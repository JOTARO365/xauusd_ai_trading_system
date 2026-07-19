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
