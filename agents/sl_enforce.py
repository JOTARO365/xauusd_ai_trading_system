"""agents/sl_enforce.py — SL safety floor + backstop sweep (user 08-22, แก้คลาส −6,248 un-stopped SELL).

สองส่วน:
  1. valid(sl_pips, symbol) — refuse-to-open ถ้า SL หาย/0/แคบกว่า SL_MIN_PIPS. hard safety floor (ไม่ใช่แก้ SL default).
  2. reconcile() — sweep ทุก cycle: position ที่เปิดอยู่ **ไม่มี broker SL** (ทุก magic รวม manual/MSE) → แนบ
     backstop SL (disaster stop SL_BACKSTOP_PIPS). ไม่เคยขยับ/บีบ SL ที่มีอยู่. idempotent, fail-soft.

= กันไม้ระเบิด (short ค้างตลอด rally SL ไม่ทำงาน −6,248). fail-CLOSED เฉพาะ valid() (refuse-to-open = ปลอดภัย);
reconcile fail-soft. 0 token.
"""
from loguru import logger


def _cfg(n, d):
    import config as _c
    return getattr(_c, n, d)


def valid(sl_pips, symbol=None):
    """False → refuse to open. เรียกใน open_order/place_pending_order ก่อนวาง."""
    floor = float(_cfg("SL_MIN_PIPS", 100))
    if sl_pips is None:
        return False, "SL-ENFORCE: missing SL (sl_pips=None)"
    try:
        sp = float(sl_pips)
    except (TypeError, ValueError):
        return False, "SL-ENFORCE: invalid SL (non-numeric)"
    if sp <= 0:
        return False, "SL-ENFORCE: SL ≤ 0"
    if sp < floor:
        return False, "SL-ENFORCE: SL %.0f < floor %.0f pips" % (sp, floor)
    return True, ""


def reconcile(positions=None):
    """sweep: position ที่ไม่มี SL → แนบ backstop. คืน list ของ ticket ที่แก้. idempotent, fail-soft."""
    fixed = []
    try:
        import MetaTrader5 as mt5
        pos = positions if positions is not None else (mt5.positions_get() or [])
        backstop_pips = float(_cfg("SL_BACKSTOP_PIPS", 500))
        for p in pos:
            if getattr(p, "sl", 0) and p.sl > 0:
                continue                                      # มี SL แล้ว — ไม่แตะ
            si = mt5.symbol_info(p.symbol)
            if si is None or si.point <= 0:
                continue
            dist = backstop_pips * si.point
            is_buy = (p.type == mt5.ORDER_TYPE_BUY)
            sl = round(p.price_open - dist, si.digits) if is_buy else round(p.price_open + dist, si.digits)
            req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
                   "sl": sl, "tp": getattr(p, "tp", 0.0)}
            r = mt5.order_send(req)
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                fixed.append(p.ticket)
                logger.warning("[SL-ENFORCE] backstop SL %.2f แนบให้ ticket %s %s (เปิดไร้ SL = un-stopped risk)"
                               % (sl, p.ticket, p.symbol))
            else:
                logger.debug("[SL-ENFORCE] แนบ backstop fail ticket %s: %s" % (p.ticket, getattr(r, "retcode", "?")))
    except Exception as e:
        logger.debug("[SL-ENFORCE] reconcile fail-soft: %s" % e)
    return fixed
