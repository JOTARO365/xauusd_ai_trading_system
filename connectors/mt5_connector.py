import re
import time as _time
import numpy as np
import MetaTrader5 as mt5
from config import SYMBOL, MONEY_MANAGEMENT, LOT_MODE, FIXED_LOT, MIN_LOT, MAX_LOT, DYNAMIC_TP, NO_TP_WAIT_MINUTES
from loguru import logger


def _safe_comment(text: str) -> str:
    """กรองเฉพาะ ASCII printable และตัดให้ไม่เกิน 31 ตัวอักษร (ขีดจำกัด MT5)"""
    cleaned = re.sub(r"[^\x20-\x7E]", "", text)
    return cleaned[:31]

PENDING_TYPE_MAP = {
    "BUY_LIMIT":  mt5.ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP":   mt5.ORDER_TYPE_BUY_STOP,
    "SELL_STOP":  mt5.ORDER_TYPE_SELL_STOP,
}


def calculate_lot_size(account_balance: float, sl_pips: float) -> float:
    if LOT_MODE == "fixed":
        lot = FIXED_LOT
        logger.info(f"Lot mode: fixed → {lot}")
    else:
        risk_amount = account_balance * MONEY_MANAGEMENT["risk_per_trade"]
        pip_value = 0.1  # XAU/USD: $0.1 per pip per 0.01 lot
        lot = round(risk_amount / (sl_pips * pip_value * 100), 2)
        logger.info(f"Lot mode: auto → risk ${risk_amount:.2f} / SL {sl_pips} pips = {lot} lots")

    lot = max(MIN_LOT, min(lot, MAX_LOT))
    return lot


def _close_position(pos) -> bool:
    """ปิด market position ด้วยราคาตลาดขณะนั้น"""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    is_buy   = pos.type == 0
    close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask
    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       pos.volume,
        "type":         close_type,
        "position":     pos.ticket,
        "price":        close_price,
        "deviation":    20,
        "magic":        SYSTEM_MAGIC,
        "comment":      _safe_comment("CONFLICT_CLOSE"),
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = result.retcode if result else mt5.last_error()
        logger.error(f"Close conflict failed ticket={pos.ticket}: {err}")
        return False
    logger.info(f"Closed conflicting position: ticket={pos.ticket} {'BUY' if is_buy else 'SELL'} @ {close_price:.2f}")
    return True


def is_hedge_active() -> bool:
    """True ถ้ามี BUY และ SELL เปิดอยู่พร้อมกัน (hedge position)"""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return False
    types = {pos.type for pos in positions}
    return 0 in types and 1 in types  # 0=BUY, 1=SELL


def check_open_slot(direction: str) -> tuple[bool, str]:
    """
    ตรวจสอบว่าสามารถเปิด order ทิศทางนี้ได้หรือไม่

    กฎ:
    1. นับ slot แยก BUY/SELL — ต้องไม่เกิน max_open_trades ต่อฝั่ง
    2. ถ้ามี position ฝั่งตรงข้ามที่ขาดทุนอยู่ → ตรวจ 2 เงื่อนไข:
       a) ถ้า losing positions ทุกตัว SL อยู่หน้าทุนแล้ว (protected) → เปิดได้เลย
       b) ถ้า opposing position สวนทางยังไม่เกิน hedge_buffer_pips → เปิดได้
          hedge_buffer = จำนวนจุดที่ราคาวิ่งสวนทาง opposing position (default 1000 จุด)

    Returns: (can_open: bool, reason: str)
    """
    positions = mt5.positions_get(symbol=SYMBOL) or []
    max_per_dir = MONEY_MANAGEMENT["max_open_trades"]

    dir_type = 0 if direction.upper() == "BUY" else 1   # MT5: 0=BUY, 1=SELL
    opp_type = 1 - dir_type
    opp_name = "SELL" if direction.upper() == "BUY" else "BUY"

    same_pos = [p for p in positions if p.type == dir_type]
    opp_pos  = [p for p in positions if p.type == opp_type]

    # ── 1. Slot limit ต่อทิศทาง ────────────────────────────────
    protected = count_protected_slots()
    effective_max = max_per_dir + protected
    if len(same_pos) >= effective_max:
        return False, (
            f"{direction} slot เต็ม ({len(same_pos)}/{effective_max}"
            + (f" รวม {protected} protected" if protected else "") + ")"
        )

    # ── 2. Hedge buffer — ช่องไฟเปิดฝั่งตรงข้าม ────────────────
    if opp_pos:
        losing = [p for p in opp_pos if p.profit < 0]
        if losing:
            # a) ตรวจว่า losing position แต่ละตัว SL อยู่หน้าทุนหรือยัง (protected)
            def _is_sl_protected(p) -> bool:
                if p.sl == 0:
                    return False
                return (p.type == 0 and p.sl >= p.price_open) or \
                       (p.type == 1 and p.sl <= p.price_open)

            unprotected = [p for p in losing if not _is_sl_protected(p)]

            if not unprotected:
                # ทุก losing position SL หน้าทุนแล้ว — ไม่มีความเสี่ยงเพิ่ม
                logger.debug(
                    f"{opp_name} losing แต่ SL protected ทั้งหมด → เปิด {direction} ได้"
                )
            else:
                # b) ตรวจ pip distance ของ unprotected positions vs hedge_buffer_pips
                sym_info  = mt5.symbol_info(SYMBOL)
                tick      = mt5.symbol_info_tick(SYMBOL)
                point     = sym_info.point if sym_info else 0.01
                cur_price = tick.bid if tick else 0

                max_adverse = 0.0
                for p in unprotected:
                    if p.type == 0:  # BUY — สวนทาง = ราคาลง
                        adverse = (p.price_open - cur_price) / point
                    else:            # SELL — สวนทาง = ราคาขึ้น
                        adverse = (cur_price - p.price_open) / point
                    max_adverse = max(max_adverse, adverse)

                buffer_pips = MONEY_MANAGEMENT["hedge_buffer_pips"]
                if max_adverse > buffer_pips:
                    return False, (
                        f"ไม่สามารถเปิด {direction} — "
                        f"{opp_name} สวนทางสูงสุด {max_adverse:.0f} จุด "
                        f"เกิน buffer ({buffer_pips} จุด) | "
                        f"{len(unprotected)} position ยังเสี่ยงอยู่"
                    )
                logger.debug(
                    f"{opp_name} สวนทาง {max_adverse:.0f} จุด ≤ {buffer_pips} → เปิด {direction} ได้"
                )

    return True, ""


def open_order(direction: str, sl_pips: float, tp_pips: float,
               comment: str = "", min_rr: float | None = None) -> dict:
    account = mt5.account_info()
    if account is None:
        logger.error("Cannot get account info")
        return {"success": False, "error": "No account info"}

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logger.error(f"Cannot get tick for {SYMBOL}")
        return {"success": False, "error": "No tick data"}

    sym_info = mt5.symbol_info(SYMBOL)
    point      = sym_info.point
    stops_min  = sym_info.trade_stops_level * point   # ระยะ SL/TP ขั้นต่ำจากราคาปัจจุบัน
    lot = calculate_lot_size(account.balance, sl_pips)

    no_tp = (tp_pips == 0)   # mode พิเศษ: ไม่ตั้ง TP รอ momentum

    if direction.upper() == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        sl = price - sl_pips * point
        tp = 0.0 if no_tp else price + tp_pips * point
        if stops_min > 0:
            if price - sl < stops_min:
                sl = price - stops_min
                logger.warning(f"SL ปรับจาก {sl_pips} pips → {round((price-sl)/point)} pips (stops_level)")
            if not no_tp and tp - price < stops_min:
                tp = price + stops_min
                logger.warning(f"TP ปรับ → {round((tp-price)/point)} pips (stops_level)")
    elif direction.upper() == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        sl = price + sl_pips * point
        tp = 0.0 if no_tp else price - tp_pips * point
        if stops_min > 0:
            if sl - price < stops_min:
                sl = price + stops_min
                logger.warning(f"SL ปรับจาก {sl_pips} pips → {round((sl-price)/point)} pips (stops_level)")
            if not no_tp and price - tp < stops_min:
                tp = price - stops_min
                logger.warning(f"TP ปรับ → {round((price-tp)/point)} pips (stops_level)")
    else:
        return {"success": False, "error": f"Invalid direction: {direction}"}

    if no_tp:
        logger.info("No-TP mode: เปิด order โดยไม่ตั้ง TP — รอตั้งหลัง momentum สงบ")

    # ตรวจ Risk/Reward ratio — ข้ามถ้า no_tp (ไม่มี TP ให้คำนวณ)
    effective_min_rr = min_rr if min_rr is not None else MONEY_MANAGEMENT["min_rr_ratio"]
    if not no_tp:
        actual_sl_pips = abs(price - sl) / point
        actual_tp_pips = abs(tp - price) / point
        rr = actual_tp_pips / actual_sl_pips if actual_sl_pips > 0 else 0
        if rr < effective_min_rr:
            logger.warning(f"RR ratio {rr:.2f} ต่ำกว่าขั้นต่ำ {effective_min_rr:.1f} (dynamic)")
            return {"success": False, "error": f"RR ratio too low: {rr:.2f} (min={effective_min_rr:.1f})"}

    # ตรวจจำนวน order ที่เปิดอยู่
    # hedge active → reset limit กลับเป็น base (ไม่นับ protected slots)
    # ป้องกัน protected bonus ถูก exploit ขณะ hedge
    open_positions = mt5.positions_get(symbol=SYMBOL)
    if is_hedge_active():
        effective_limit = MONEY_MANAGEMENT["max_open_trades"]
        logger.info("Hedge active — base limit only (protected bonus reset)")
    else:
        effective_limit = MONEY_MANAGEMENT["max_open_trades"] + count_protected_slots()
    if open_positions and len(open_positions) >= effective_limit:
        return {"success": False, "error": "Max open trades reached"}

    # ตรวจ margin ก่อนส่ง — คำนวณ margin ที่ต้องการสำหรับ lot นี้
    margin_needed = mt5.order_calc_margin(order_type, SYMBOL, lot, price)
    if margin_needed is not None and account.equity < margin_needed:
        logger.warning(f"Margin ไม่พอ: ต้องการ {margin_needed:.2f}, equity {account.equity:.2f}")
        safe_lot = round((account.equity * 0.9) / (margin_needed / lot), 2) if lot > 0 else 0
        safe_lot = max(MIN_LOT, min(safe_lot, lot))
        if safe_lot < MIN_LOT:
            return {"success": False, "error": f"Margin ไม่พอแม้จะใช้ lot ขั้นต่ำ (equity={account.equity:.2f})"}
        logger.info(f"ลด lot จาก {lot} → {safe_lot} เพราะ margin จำกัด")
        lot = safe_lot

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "deviation": 20,
        "magic": 20260429,
        "comment": _safe_comment(comment),
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        err = mt5.last_error()
        logger.error(f"Order failed: order_send returned None — {err}")
        return {"success": False, "error": f"order_send None: {err}"}
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed: {result.retcode} — {result.comment}")
        return {"success": False, "error": result.comment, "retcode": result.retcode}

    logger.info(f"Order opened: {direction} {lot} lots @ {price} SL={sl:.2f} TP={tp:.2f}")
    return {
        "success": True,
        "ticket": result.order,
        "direction": direction,
        "lot": lot,
        "price": price,
        "sl": round(sl, 2),
        "tp": round(tp, 2),
    }


SYSTEM_MAGIC = 20260429   # magic number ที่ระบบ AI ใช้


def get_open_positions() -> list:
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [
        {
            "ticket":     p.ticket,
            "direction":  "BUY" if p.type == 0 else "SELL",
            "lot":        p.volume,
            "open_price": p.price_open,
            "sl":         p.sl,
            "tp":         p.tp,
            "profit":     p.profit,
            "magic":      p.magic,
            "comment":    p.comment,
            "time_open":  p.time,
            "source":     "SYSTEM" if p.magic == SYSTEM_MAGIC else "MANUAL",
        }
        for p in positions
    ]


def get_mt5_history(days: int = 60) -> list:
    """ดึงประวัติ deal ทั้งหมดจาก MT5 (ทั้ง SYSTEM และ MANUAL)
    รวม SL/TP จาก history_orders_get เพื่อให้ log สมบูรณ์
    """
    from datetime import datetime, timedelta
    date_from = datetime.now() - timedelta(days=days)
    date_to   = datetime.now()

    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        return []

    # สร้าง map order_ticket → order เพื่อดึง SL/TP
    raw_orders = mt5.history_orders_get(date_from, date_to)
    order_map: dict[int, object] = {}
    if raw_orders:
        for o in raw_orders:
            if o.symbol == SYMBOL:
                order_map[o.ticket] = o

    results = []
    for d in deals:
        if d.symbol != SYMBOL:
            continue
        # entry deal เท่านั้น (DEAL_ENTRY_IN = 0)
        if d.entry != 0:
            continue

        o  = order_map.get(d.order)
        sl = (o.sl if o and o.sl != 0.0 else None)
        tp = (o.tp if o and o.tp != 0.0 else None)

        results.append({
            "ticket":    d.order,       # order ticket
            "deal_id":   d.ticket,
            "direction": "BUY" if d.type == 0 else "SELL",
            "lot":       d.volume,
            "price":     d.price,
            "time":      d.time,
            "magic":     d.magic,
            "comment":   d.comment,
            "source":    "SYSTEM" if d.magic == SYSTEM_MAGIC else "MANUAL",
            "sl":        sl,
            "tp":        tp,
        })
    return results


def place_pending_order(pending_type: str, price: float, sl_pips: float, tp_pips: float,
                        comment: str = "", expiry_hours: int = 48) -> dict:
    """วาง pending order ที่ level ที่กำหนด ใช้ TRADE_ACTION_PENDING"""
    if pending_type not in PENDING_TYPE_MAP:
        return {"success": False, "error": f"Invalid pending_type: {pending_type}"}

    account = mt5.account_info()
    if account is None:
        return {"success": False, "error": "No account info"}

    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return {"success": False, "error": f"No symbol info for {SYMBOL}"}

    point     = info.point
    stops_min = info.trade_stops_level * point
    lot       = calculate_lot_size(account.balance, sl_pips)
    is_buy    = pending_type.startswith("BUY")
    sl = (price - sl_pips * point) if is_buy else (price + sl_pips * point)
    tp = (price + tp_pips * point) if is_buy else (price - tp_pips * point)

    # ขยับ SL/TP ถ้าชนขีดจำกัด stops_level ของ pending price
    if stops_min > 0:
        if is_buy:
            if price - sl < stops_min:
                sl = price - stops_min
            if tp - price < stops_min:
                tp = price + stops_min
        else:
            if sl - price < stops_min:
                sl = price + stops_min
            if price - tp < stops_min:
                tp = price - stops_min

    actual_sl_pips = abs(price - sl) / point
    actual_tp_pips = abs(tp - price) / point
    rr = actual_tp_pips / actual_sl_pips if actual_sl_pips > 0 else 0
    if rr < MONEY_MANAGEMENT["min_rr_ratio"]:
        return {"success": False, "error": f"RR ratio too low: {rr:.2f}"}

    # ตรวจทิศทาง price vs ราคาปัจจุบัน (MT5 จะ reject ถ้าผิดข้าง)
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is not None:
        ask, bid = tick.ask, tick.bid
        if pending_type == "BUY_LIMIT"  and price >= ask:
            return {"success": False, "error": f"BUY_LIMIT price {price} ต้องต่ำกว่า ask {ask:.2f}"}
        if pending_type == "SELL_LIMIT" and price <= bid:
            return {"success": False, "error": f"SELL_LIMIT price {price} ต้องสูงกว่า bid {bid:.2f}"}
        if pending_type == "BUY_STOP"   and price <= ask:
            return {"success": False, "error": f"BUY_STOP price {price} ต้องสูงกว่า ask {ask:.2f}"}
        if pending_type == "SELL_STOP"  and price >= bid:
            return {"success": False, "error": f"SELL_STOP price {price} ต้องต่ำกว่า bid {bid:.2f}"}

    # expiry ใช้ server time จาก tick (ป้องกัน timezone mismatch กับ broker)
    server_time = tick.time if tick is not None else int(__import__("time").time())
    expiry_ts   = server_time + expiry_hours * 3600

    request = {
        "action":       mt5.TRADE_ACTION_PENDING,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         PENDING_TYPE_MAP[pending_type],
        "price":        round(price, 2),
        "sl":           round(sl, 2),
        "tp":           round(tp, 2),
        "deviation":    20,
        "magic":        SYSTEM_MAGIC,
        "comment":      _safe_comment(comment),
        "type_time":    mt5.ORDER_TIME_SPECIFIED,
        "expiration":   expiry_ts,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    result = mt5.order_send(request)
    if result is None:
        err = mt5.last_error()
        logger.error(f"Pending order failed: order_send returned None — {err}")
        return {"success": False, "error": f"order_send None: {err}"}
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Pending order failed: {result.retcode} — {result.comment}")
        return {"success": False, "error": result.comment, "retcode": result.retcode}

    logger.info(f"Pending placed: {pending_type} @ {price:.2f} SL={sl:.2f} TP={tp:.2f} lot={lot}")
    return {
        "success":      True,
        "ticket":       result.order,
        "pending_type": pending_type,
        "price":        round(price, 2),
        "sl":           round(sl, 2),
        "tp":           round(tp, 2),
        "lot":          lot,
        "expiry":       expiry_ts,
    }


def get_pending_orders() -> list:
    """ดึง pending orders ทั้งหมดของ SYMBOL (ทั้ง SYSTEM และ MANUAL)"""
    _PENDING_TYPES = {
        mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
        mt5.ORDER_TYPE_BUY_STOP,  mt5.ORDER_TYPE_SELL_STOP,
    }
    orders = mt5.orders_get(symbol=SYMBOL)
    if orders is None:
        return []
    return [
        {
            "ticket":       o.ticket,
            "pending_type": next((k for k, v in PENDING_TYPE_MAP.items() if v == o.type), "UNKNOWN"),
            "price":        o.price_open,
            "sl":           o.sl if o.sl != 0.0 else None,
            "tp":           o.tp if o.tp != 0.0 else None,
            "lot":          o.volume_current,
            "magic":        o.magic,
            "comment":      o.comment,
            "expiration":   o.time_expiration,
            "source":       "SYSTEM" if o.magic == SYSTEM_MAGIC else "MANUAL",
        }
        for o in orders if o.type in _PENDING_TYPES
    ]


BREAKEVEN_TRIGGER_PIPS = 1000   # ขยับ SL มาหน้าทุนเมื่อกำไรถึงระดับนี้
BREAKEVEN_BUFFER_PIPS  = 100    # เผื่อ spread — SL = entry + 100 pips (ไม่ขาดทุน)


def count_protected_slots() -> int:
    """คืนจำนวน open positions ที่ SL อยู่หน้าทุนแล้ว (ไม่มีความเสี่ยงขาดทุน)
    ใช้เพิ่ม slot สำหรับ order ใหม่ — 1 protected position = 1 extra slot"""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0
    info = mt5.symbol_info(SYMBOL)
    point = info.point if info else 0.01
    count = 0
    for pos in positions:
        if pos.sl == 0:
            continue
        is_buy = pos.type == 0
        # BUY: SL หน้าทุน = sl >= entry + buffer, SELL: sl <= entry - buffer
        if is_buy  and pos.sl >= pos.price_open + BREAKEVEN_BUFFER_PIPS * point:
            count += 1
        elif not is_buy and pos.sl <= pos.price_open - BREAKEVEN_BUFFER_PIPS * point:
            count += 1
    return count


def manage_breakeven() -> int:
    """ตรวจ open positions ทุกตัว — ถ้ากำไรเกิน BREAKEVEN_TRIGGER_PIPS แล้ว SL ยังอยู่ฝั่งขาดทุน
    ให้ขยับ SL มาที่ entry + buffer (หน้าทุนเล็กน้อย)
    คืนจำนวน positions ที่แก้ SL"""
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return 0
    point = info.point

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 0

    modified = 0
    for pos in positions:
        entry  = pos.price_open
        is_buy = pos.type == 0   # ORDER_TYPE_BUY = 0

        # คำนวณ pip ที่กำไรอยู่ตอนนี้
        current = tick.bid if is_buy else tick.ask
        profit_pips = ((current - entry) if is_buy else (entry - current)) / point

        if profit_pips < BREAKEVEN_TRIGGER_PIPS:
            continue   # ยังไม่ถึง trigger

        # คำนวณ SL ใหม่ที่หน้าทุน
        new_sl = round(entry + BREAKEVEN_BUFFER_PIPS * point, 2) if is_buy \
            else round(entry - BREAKEVEN_BUFFER_PIPS * point, 2)

        # ข้ามถ้า SL ปัจจุบันอยู่หน้าทุนแล้ว
        if is_buy  and pos.sl >= new_sl:
            continue
        if not is_buy and pos.sl != 0 and pos.sl <= new_sl:
            continue

        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   SYMBOL,
            "position": pos.ticket,
            "sl":       new_sl,
            "tp":       pos.tp,
        }
        result = mt5.order_send(req)
        if result is None:
            logger.error(f"Breakeven failed ticket={pos.ticket}: {mt5.last_error()}")
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Breakeven failed ticket={pos.ticket}: retcode={result.retcode}")
        else:
            direction = "BUY" if is_buy else "SELL"
            logger.info(
                f"Breakeven set: ticket={pos.ticket} {direction} "
                f"entry={entry:.2f} profit={profit_pips:.0f}pips "
                f"SL {pos.sl:.2f}→{new_sl:.2f}"
            )
            modified += 1

    return modified


# ─────────────────────────────────────────────────────────────
# DYNAMIC TP EXTENSION
# ─────────────────────────────────────────────────────────────

TP_EXT_NEAR_PIPS       = 150   # ขยับ TP เมื่อราคาห่างจาก TP น้อยกว่านี้ (เดิม 300)
TP_EXT_PIPS            = 400   # ขยับ TP ออกไปอีกเท่านี้ต่อรอบ
TP_EXT_MAX             = 2     # จำนวนครั้งสูงสุดต่อ position (เดิม 3)
TP_EXT_MIN_PROFIT_PIPS = 500   # กำไรขั้นต่ำก่อนพิจารณาขยาย (เดิม 300)
TP_EXT_COOLDOWN_SECS   = 900   # cooldown 15 นาทีระหว่าง extension แต่ละครั้ง
TP_EXT_SL_LOCK_PIPS    = 200   # trail SL ห่างจากราคาปัจจุบัน X pips เมื่อ extend TP

_tp_ext_count:     dict[int, int]   = {}   # ticket → จำนวนครั้งที่ขยายแล้ว
_tp_ext_last_time: dict[int, float] = {}   # ticket → timestamp ครั้งล่าสุดที่ขยาย


def _ema_np(prices: np.ndarray, period: int) -> np.ndarray:
    k   = 2.0 / (period + 1)
    out = prices.copy().astype(float)
    for i in range(1, len(out)):
        out[i] = prices[i] * k + out[i - 1] * (1 - k)
    return out


def _is_momentum_strong(direction: str) -> bool:
    """
    ตรวจ momentum แบบ lightweight จากข้อมูล M15 โดยตรง — ไม่เรียก AI
    คืน True ถ้า momentum แรง (score ≥ 4) สอดคล้องกับ direction
    สัญญาณ: RSI(14) slope, MACD hist + expansion, Price ROC(5), EMA stack
    """
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 55)
    if bars is None or len(bars) < 35:
        return False

    close  = np.array([b["close"] for b in bars], dtype=float)
    is_buy = direction.upper() == "BUY"

    # RSI(14)
    delta  = np.diff(close)
    gain   = np.where(delta > 0, delta, 0.0)
    loss   = np.where(delta < 0, -delta, 0.0)
    avg_g  = np.convolve(gain, np.ones(14) / 14, "valid")
    avg_l  = np.convolve(loss, np.ones(14) / 14, "valid")
    rs     = np.where(avg_l > 0, avg_g / avg_l, 100.0)
    rsi    = 100.0 - (100.0 / (1.0 + rs))
    rsi_slope = float(rsi[-1] - rsi[-4]) if len(rsi) >= 5 else 0.0

    # MACD histogram
    ema12        = _ema_np(close, 12)
    ema26        = _ema_np(close, 26)
    hist         = (ema12 - ema26) - _ema_np(ema12 - ema26, 9)
    hist_now     = float(hist[-1])
    hist_prev    = float(hist[-3]) if len(hist) >= 3 else hist_now
    hist_expand  = abs(hist_now) > abs(hist_prev)

    # Price ROC 5 bars
    roc5 = float((close[-1] - close[-6]) / close[-6] * 100) if len(close) >= 6 else 0.0

    # EMA stack alignment
    ema20   = _ema_np(close, 20)
    ema50   = _ema_np(close, 50)
    ema_bull = close[-1] > ema20[-1] > ema50[-1]
    ema_bear = close[-1] < ema20[-1] < ema50[-1]

    up = dn = 0
    if rsi_slope >  1.5: up += 1
    elif rsi_slope < -1.5: dn += 1

    if hist_now > 0: up += 2 if hist_expand else 1
    elif hist_now < 0: dn += 2 if hist_expand else 1

    if roc5 >  0.02: up += 1
    elif roc5 < -0.02: dn += 1

    if ema_bull: up += 1
    elif ema_bear: dn += 1

    return (up >= 4 and up > dn) if is_buy else (dn >= 4 and dn > up)


def manage_dynamic_tp() -> int:
    """
    ตรวจ open positions ที่กำไร — เมื่อราคาเข้าใกล้ TP และ momentum แรง
    ขยับ TP ออกไปอีก TP_EXT_PIPS (สูงสุด TP_EXT_MAX ครั้ง)
    คืนจำนวน positions ที่ขยาย TP
    """
    if not DYNAMIC_TP:
        return 0

    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return 0
    point = info.point

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 0

    extended = 0
    for pos in positions:
        if pos.tp == 0:
            continue

        is_buy   = pos.type == 0
        current  = tick.bid if is_buy else tick.ask
        ticket   = pos.ticket

        profit_pips = ((current - pos.price_open) if is_buy else (pos.price_open - current)) / point
        if profit_pips < TP_EXT_MIN_PROFIT_PIPS:
            continue

        dist_to_tp = ((pos.tp - current) if is_buy else (current - pos.tp)) / point
        if dist_to_tp > TP_EXT_NEAR_PIPS or dist_to_tp < 0:
            continue  # ยังไกล TP อยู่ หรือ TP โดนแล้ว

        ext_done = _tp_ext_count.get(ticket, 0)
        if ext_done >= TP_EXT_MAX:
            continue

        # cooldown — ไม่ extend อีกถ้าเพิ่ง extend ไปภายใน TP_EXT_COOLDOWN_SECS
        last_ext = _tp_ext_last_time.get(ticket, 0.0)
        secs_since = _time.time() - last_ext
        if secs_since < TP_EXT_COOLDOWN_SECS:
            wait_min = int((TP_EXT_COOLDOWN_SECS - secs_since) / 60)
            logger.debug(f"Dynamic TP: ticket={ticket} cooldown — อีก {wait_min}min")
            continue

        direction = "BUY" if is_buy else "SELL"
        if not _is_momentum_strong(direction):
            logger.debug(f"Dynamic TP: ticket={ticket} momentum ไม่แรงพอ — ไม่ขยาย")
            continue

        new_tp = round(pos.tp + TP_EXT_PIPS * point, 2) if is_buy \
            else round(pos.tp - TP_EXT_PIPS * point, 2)

        # trail SL มาล็อคกำไรเมื่อ extend TP — SL ไม่ถอยหลัง
        lock_sl = round(current - TP_EXT_SL_LOCK_PIPS * point, 2) if is_buy \
            else round(current + TP_EXT_SL_LOCK_PIPS * point, 2)
        if is_buy:
            new_sl = max(pos.sl, lock_sl)   # SL เลื่อนขึ้นเท่านั้น
        else:
            cur_sl = pos.sl if pos.sl > 0 else float("inf")
            new_sl = min(cur_sl, lock_sl)   # SL เลื่อนลงเท่านั้น (SELL)

        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   SYMBOL,
            "position": ticket,
            "sl":       new_sl,
            "tp":       new_tp,
        }
        result = mt5.order_send(req)
        if result is None:
            logger.error(f"Dynamic TP extend failed ticket={ticket}: {mt5.last_error()}")
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Dynamic TP extend failed ticket={ticket}: retcode={result.retcode}")
        else:
            _tp_ext_count[ticket]     = ext_done + 1
            _tp_ext_last_time[ticket] = _time.time()
            locked_pips = abs(current - new_sl) / point
            logger.info(
                f"Dynamic TP extended: ticket={ticket} {direction} "
                f"profit={profit_pips:.0f}pips dist_to_tp={dist_to_tp:.0f}pips "
                f"TP {pos.tp:.2f}→{new_tp:.2f} | SL {pos.sl:.2f}→{new_sl:.2f} "
                f"(locked {locked_pips:.0f}pips profit) ext #{ext_done + 1}/{TP_EXT_MAX}"
            )
            extended += 1

    return extended


def manage_post_event_tp() -> int:
    """
    ตรวจ open positions ที่เปิดแบบ No-TP (tp=0) — เมื่อเวลาผ่านไปครบ NO_TP_WAIT_MINUTES
    และ momentum สงบแล้ว ให้ตั้ง TP = entry ± default_tp_pips
    คืนจำนวน positions ที่ตั้ง TP แล้ว
    """
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return 0
    point     = info.point
    stops_min = info.trade_stops_level * point

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    now  = int(_time.time())
    default_tp_pips = MONEY_MANAGEMENT["default_tp_pips"]
    set_count = 0

    for pos in positions:
        if pos.tp != 0:
            continue   # มี TP แล้ว — ข้าม

        is_buy       = pos.type == 0
        direction    = "BUY" if is_buy else "SELL"
        elapsed_mins = (now - pos.time) / 60

        if elapsed_mins < NO_TP_WAIT_MINUTES:
            logger.debug(
                f"No-TP ticket={pos.ticket} — รออีก {NO_TP_WAIT_MINUTES - elapsed_mins:.0f}min"
            )
            continue

        # ยังรอ momentum สงบ
        if _is_momentum_strong(direction):
            logger.info(
                f"No-TP ticket={pos.ticket} — elapsed {elapsed_mins:.0f}min "
                "แต่ momentum ยังแรง — รอต่อ"
            )
            continue

        # คำนวณ TP จาก entry price
        new_tp = round(pos.price_open + default_tp_pips * point, 2) if is_buy \
            else round(pos.price_open - default_tp_pips * point, 2)

        # ตรวจ stops_level จากราคาปัจจุบัน
        if tick is not None and stops_min > 0:
            current = tick.ask if is_buy else tick.bid
            if is_buy  and new_tp - current < stops_min:
                new_tp = round(current + stops_min, 2)
            elif not is_buy and current - new_tp < stops_min:
                new_tp = round(current - stops_min, 2)

        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   SYMBOL,
            "position": pos.ticket,
            "sl":       pos.sl,
            "tp":       new_tp,
        }
        result = mt5.order_send(req)
        if result is None:
            logger.error(f"Post-event TP failed ticket={pos.ticket}: {mt5.last_error()}")
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Post-event TP failed ticket={pos.ticket}: retcode={result.retcode}")
        else:
            logger.info(
                f"Post-event TP set: ticket={pos.ticket} {direction} "
                f"entry={pos.price_open:.2f} elapsed={elapsed_mins:.0f}min TP→{new_tp:.2f}"
            )
            set_count += 1

    return set_count


def cancel_pending_order(ticket: int) -> bool:
    """ยกเลิก pending order ด้วย TRADE_ACTION_REMOVE"""
    result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    if result is None:
        logger.error(f"Cancel pending failed: order_send returned None — {mt5.last_error()}")
        return False
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Cancel pending failed: ticket={ticket} retcode={result.retcode}")
        return False
    logger.info(f"Pending order cancelled: ticket={ticket}")
    return True


def get_closed_deal_pnl(order_ticket: int) -> float | None:
    """หา PnL รวมของ position ที่ปิดแล้ว
    คืน float (รวม 0.0 กรณี break-even) หรือ None ถ้ายังไม่ปิด / หาข้อมูลไม่ได้
    """
    from datetime import datetime, timedelta
    deals = mt5.history_deals_get(
        datetime.now() - timedelta(days=60),
        datetime.now()
    )
    if deals is None:
        return None

    matched = [d for d in deals if d.position_id == order_ticket]
    if not matched:
        return None

    # ต้องมี closing deal (DEAL_ENTRY_OUT = 1) ถึงจะถือว่าปิดแล้ว
    if not any(d.entry == 1 for d in matched):
        return None

    return round(sum(d.profit + d.swap + d.commission for d in matched), 2)
