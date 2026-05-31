import re
import time as _time
import numpy as np
import MetaTrader5 as mt5
import config as _cfg
from config import SYMBOL, MONEY_MANAGEMENT
from loguru import logger


def _safe_comment(text: str) -> str:
    """กรองเฉพาะตัวอักษรที่ broker ยอมรับ และตัดให้ไม่เกิน 31 ตัวอักษร
    ตัดออก: | : @ # $ % ^ & * ( ) + = [ ] { } ; ' " < > ? \\
    เหลือ: A-Z a-z 0-9 space _ - . / !
    """
    cleaned = re.sub(r"[^A-Za-z0-9 _.!\-/]", "", text)
    return cleaned[:31]

# ── Order retry config ───────────────────────────────────────────────────────
_RETRYABLE_RETCODES = frozenset({
    10004,   # REQUOTE
    10021,   # PRICE_CHANGED
    10024,   # TOO_MANY_REQUESTS
})
_MAX_ORDER_RETRIES = 2
_RETRY_DELAY_SEC   = 0.5


def is_algo_trading_enabled() -> bool:
    """ตรวจว่าปุ่ม Algo Trading ใน MT5 terminal เปิดอยู่หรือไม่"""
    try:
        info = mt5.terminal_info()
        return bool(info and info.trade_allowed)
    except Exception:
        return True   # ถ้าตรวจไม่ได้ สมมติว่าเปิดอยู่


PENDING_TYPE_MAP = {
    "BUY_LIMIT":  mt5.ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP":   mt5.ORDER_TYPE_BUY_STOP,
    "SELL_STOP":  mt5.ORDER_TYPE_SELL_STOP,
}


def calculate_lot_size(account_balance: float, sl_pips: float,
                       confidence_scale: float = 1.0) -> float:
    """คำนวณ lot size โดยปรับตาม confidence_scale (0.5–1.0)
    confidence_scale < 1.0 → risk น้อยลงตามสัดส่วน confidence
    """
    pip_value = 0.1  # XAU/USD: $0.1 per pip per 0.01 lot
    if _cfg.LOT_MODE == "fixed":
        lot = _cfg.FIXED_LOT
        logger.info(f"Lot mode: fixed → {lot}")
    else:
        scale = max(0.0, min(1.0, confidence_scale))
        risk_amount = account_balance * MONEY_MANAGEMENT["risk_per_trade"] * scale
        lot = round(risk_amount / (sl_pips * pip_value * 100), 2)

    clamped = max(_cfg.MIN_LOT, min(lot, _cfg.MAX_LOT))
    actual_risk = clamped * sl_pips * pip_value * 100 if _cfg.LOT_MODE != "fixed" else 0
    if _cfg.LOT_MODE != "fixed":
        scale_note  = f" scale={confidence_scale:.2f}" if confidence_scale < 1.0 else ""
        clamp_note  = f" → clamped={clamped}" if clamped != lot else ""
        logger.info(
            f"Lot mode: auto{scale_note} → risk ${risk_amount:.2f} / SL {sl_pips} pips = {lot} lots"
            f"{clamp_note} | actual risk ${actual_risk:.2f} ({actual_risk/account_balance*100:.1f}%)"
        )
    return clamped


def _calc_pip_value(symbol: str) -> float:
    """
    คืน value ต่อ 1 pip ต่อ 1 lot ใน account currency
    ใช้ mt5.order_calc_profit — MT5 จัดการ currency conversion ให้อัตโนมัติ
    รองรับ USD, THB, EUR, GBP ฯลฯ โดยไม่ต้อง hardcode อัตราแลกเปลี่ยน
    Fallback = 1.0 (GOLD USD standard: $1/pip/lot)
    """
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return 1.0
    price = (tick.bid + tick.ask) / 2
    profit = mt5.order_calc_profit(
        mt5.ORDER_TYPE_BUY, symbol, 1.0, price, price + info.point * 100
    )
    if profit is None or profit <= 0:
        return 1.0
    return round(profit / 100, 4)  # value per 1 pip per 1 lot ใน account currency


def _nnlb_lot_and_check(equity: float, sl_pips: float) -> tuple[float, str]:
    """
    NNLB lot calculation + equity gate
    คืน (lot, error_msg)  — error_msg ว่าง = ผ่าน

    *** Config เป็น USD-canonical ***
    NNLB_BASE_EQUITY / NNLB_EQUITY_PER_LOT ตั้งเป็น **USD** แล้วแปลงเป็นสกุลบัญชี
    อัตโนมัติด้วย rate = _calc_pip_value(SYMBOL). ทองราคา 1 pip = $1 USD พอดี →
    pip value ในสกุลบัญชี = อัตราแลกเปลี่ยน USD→account ccy (USD→1.0, THB→~36).
    ค่าชุดเดียวจึงใช้ได้ทุกสกุล (USD/THB/EUR ...) ใน multi-user setup

    Profit-tier logic (หน่วยสกุลบัญชี หลังแปลงจาก USD):
      profit = equity - base_acct
      steps  = floor(profit / per_step_acct)        ← เพิ่ม 0.01 lot ต่อ step
      lot    = MIN_LOT + steps × 0.01  (clamped MIN_LOT–MAX_LOT)

    ตัวอย่าง NNLB_BASE_EQUITY=25 (USD), NNLB_EQUITY_PER_LOT=25 (USD), MIN_LOT=0.01:
      บัญชี USD (rate=1)  : base=$25,  +0.01 lot ทุก $25 กำไร
      บัญชี THB (rate~36) : base~900฿, +0.01 lot ทุก ~900฿ กำไร
    """
    # ── USD → account currency (rate = pip value ของทอง = $1/pip) ──────
    # ใช้ค่าเดียวกันทั้งแปลง config และ max-loss calc → MT5 จัดการ conversion ให้
    rate         = _calc_pip_value(_cfg.SYMBOL)          # account-ccy ต่อ 1 USD (per pip per lot)
    base_acct    = _cfg.NNLB_BASE_EQUITY * rate
    per_step     = max(1e-9, _cfg.NNLB_EQUITY_PER_LOT * rate)   # guard against div/0
    acct         = mt5.account_info()
    ccy          = acct.currency if acct else "?"

    # ── Gate: equity ต่ำกว่า base → ไม่คุ้มกับ SL ────────────────
    if equity < base_acct:
        msg = (f"[NNLB] equity {equity:.2f} {ccy} < base {base_acct:.2f} {ccy} "
               f"(${_cfg.NNLB_BASE_EQUITY:.0f} × {rate:.2f}) — skip (ทุนไม่พอ)")
        logger.warning(msg)
        return 0.0, msg

    # ── Profit-based tier: เพิ่ม 0.01 lot ทุก per_step กำไร ──
    profit       = max(0.0, equity - base_acct)
    profit_steps = int(profit / per_step)
    lot          = round(min(_cfg.MIN_LOT + profit_steps * 0.01, _cfg.MAX_LOT), 2)
    lot          = max(_cfg.MIN_LOT, lot)

    # ── NNLB_MAX_LOSS_PCT: cap lot ให้ max_loss ไม่เกิน X% ของ equity ──
    # pv_1lot = rate (เป็นค่าเดียวกัน: per pip per 1 lot ใน account ccy)
    pv_1lot      = rate
    max_loss         = round(lot * sl_pips * pv_1lot, 2)
    max_loss_allowed = round(equity * (_cfg.NNLB_MAX_LOSS_PCT / 100), 2)

    if sl_pips > 0 and max_loss > max_loss_allowed:
        budget_lot = round(max_loss_allowed / (sl_pips * pv_1lot), 2) if pv_1lot > 0 else _cfg.MIN_LOT
        if budget_lot >= _cfg.MIN_LOT:
            lot      = budget_lot
            max_loss = round(lot * sl_pips * pv_1lot, 2)
            logger.warning(
                f"[NNLB] lot ลดจาก profit-tier → {budget_lot} "
                f"เพื่อให้ max_loss {max_loss:.0f} {ccy} ≤ {_cfg.NNLB_MAX_LOSS_PCT:.0f}% ของ equity"
            )
        else:
            lot      = _cfg.MIN_LOT
            max_loss = round(lot * sl_pips * pv_1lot, 2)
            logger.warning(
                f"[NNLB] ⚠ MIN_LOT={lot} ยังให้ max_loss {max_loss:.0f} {ccy} "
                f">{_cfg.NNLB_MAX_LOSS_PCT:.0f}% equity ({max_loss_allowed:.0f} {ccy}) "
                f"— ทุนน้อยเกิน SL แต่ NNLB ยังเข้า"
            )

    loss_pct = round(max_loss / equity * 100, 1) if equity > 0 else 0
    logger.warning(
        f"[NNLB] equity={equity:.0f} {ccy}  profit={profit:.0f}  steps={profit_steps} → lot={lot} | "
        f"max loss {max_loss:.0f} {ccy} ({loss_pct}%)"
    )
    return lot, ""


def _get_htf_swing(tf_name: str = "D1", lookback: int = 3) -> tuple:
    """
    ดึง swing low / swing high จาก Higher Timeframe
    lookback: จำนวนแท่งที่ปิดแล้ว (ไม่นับแท่งที่กำลังก่อตัว)
    Returns: (swing_low, swing_high)  — (0.0, 0.0) ถ้า error
    """
    from connectors.price_feed import get_ohlcv
    tf_map = {
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
    }
    tf = tf_map.get(tf_name.upper(), mt5.TIMEFRAME_D1)
    # ดึงเผื่อ +1 เพราะแท่งสุดท้ายอาจยังไม่ปิด
    rates = get_ohlcv(SYMBOL, tf, lookback + 2)
    if rates is None or len(rates) < lookback + 1:
        return 0.0, 0.0
    # ตัดแท่งสุดท้าย (กำลังก่อตัว) ออก แล้วเอา lookback แท่งที่เหลือ
    closed = rates[:-1][-lookback:]
    swing_low  = float(min(r["low"]  for r in closed))
    swing_high = float(max(r["high"] for r in closed))
    logger.debug(
        f"[TRAILING] swing_{tf_name}(n={lookback}): "
        f"low={swing_low:.2f}  high={swing_high:.2f}"
    )
    return swing_low, swing_high


def manage_trailing_stop() -> int:
    """
    Swing Low/High trailing stop ใช้ Higher TF (H4 / D1 / W1)

    Logic:
      BUY : trail_sl = swing_low (lowest low ของ 3 แท่งที่ปิดแล้ว) − buffer
      SELL: trail_sl = swing_high (highest high ของ 3 แท่ง)         + buffer
      ขยับ SL เฉพาะเมื่อ trail_sl ดีกว่า SL ปัจจุบัน

    Config (.env):
      TRAILING_STOP=true
      TRAILING_ATR_TF=D1          # H4 | D1 | W1
      TRAILING_ATR_MULT=1.5       # buffer เป็น $ ใต้/เหนือ swing point
    """
    if not getattr(_cfg, "TRAILING_STOP", False):
        return 0

    tf_name        = getattr(_cfg, "TRAILING_ATR_TF",       "D1")
    buffer         = getattr(_cfg, "TRAILING_ATR_MULT",      1.5)   # $ buffer above/below swing
    min_profit_r   = getattr(_cfg, "TRAILING_MIN_PROFIT_R",  1.5)   # start trailing only after 1.5R profit
    lookback       = int(getattr(_cfg, "TRAILING_LOOKBACK",  6))    # H4 candles to find swing

    swing_low, swing_high = _get_htf_swing(tf_name, lookback=lookback)
    if swing_low <= 0 or swing_high <= 0:
        logger.warning("[TRAILING] ดึง swing levels ไม่ได้ — ข้าม")
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 0

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0

    info  = mt5.symbol_info(SYMBOL)
    point = info.point if info else 0.01
    moved = 0

    for pos in positions:
        is_buy       = pos.type == 0
        cur_sl       = pos.sl
        current      = tick.bid if is_buy else tick.ask
        profit_pips  = ((current - pos.price_open) if is_buy else (pos.price_open - current)) / point
        if cur_sl == 0:
            continue   # no SL set — skip to avoid trail_sl above current price
        sl_dist_pips = abs(pos.price_open - cur_sl) / point

        # ไม่เริ่ม trail จนกว่าจะมีกำไร ≥ min_profit_r × SL distance
        if sl_dist_pips > 0 and profit_pips < sl_dist_pips * min_profit_r:
            logger.debug(
                f"[TRAILING] ticket={pos.ticket}: profit={profit_pips:.0f}p < "
                f"min={sl_dist_pips * min_profit_r:.0f}p ({min_profit_r}R) — รอก่อน"
            )
            continue

        if is_buy:
            trail_sl = round(swing_low - buffer, 2)
            if cur_sl > 0 and trail_sl <= cur_sl:
                continue   # swing low ไม่ขยับขึ้น
        else:
            trail_sl = round(swing_high + buffer, 2)
            if cur_sl > 0 and trail_sl >= cur_sl:
                continue

        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   SYMBOL,
            "position": pos.ticket,
            "sl":       trail_sl,
            "tp":       pos.tp,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            direction = "BUY" if is_buy else "SELL"
            ref = f"swing_low={swing_low:.2f}" if is_buy else f"swing_high={swing_high:.2f}"
            logger.warning(
                f"[TRAILING] ticket={pos.ticket} {direction} "
                f"SL {cur_sl:.2f} → {trail_sl:.2f}  ({ref} buf=${buffer})"
            )
            moved += 1
        else:
            err = result.retcode if result else mt5.last_error()
            logger.error(f"[TRAILING] ขยับ SL ticket={pos.ticket} fail: {err}")

    return moved


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


def check_open_slot(direction: str, last_dir_lost: bool = False) -> tuple[bool, str]:
    """
    ตรวจสอบว่าสามารถเปิด order ทิศทางนี้ได้หรือไม่

    กฎ:
    1. นับ slot แยก BUY/SELL — ต้องไม่เกิน max_open_trades ต่อฝั่ง
    2. ถ้ามี position ฝั่งตรงข้าม → ทุกตัวต้องกำไร (profit > 0) ก่อน
    3. ถ้ามี position ฝั่งตรงข้ามที่ขาดทุนอยู่ → ตรวจ 2 เงื่อนไข:
       a) ถ้า losing positions ทุกตัว SL อยู่หน้าทุนแล้ว (protected) → เปิดได้เลย
       b) ถ้า opposing position สวนทางยังไม่เกิน hedge_buffer_pips → เปิดได้
    4. last_dir_lost=True → ตัด bonus slot ออก (trade ล่าสุดทิศนี้แพ้ = trend เสี่ยงเปลี่ยน)

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
    if last_dir_lost and protected > 0:
        # trade ล่าสุดทิศนี้แพ้ → ตัด bonus slot ออก ป้องกัน pyramid ทิศเดียว
        effective_max = max_per_dir
        logger.info(f"Bonus slot disabled [{direction}]: last trade in this direction was a loss")
    else:
        effective_max = max_per_dir + protected
    if len(same_pos) >= effective_max:
        return False, (
            f"{direction} slot เต็ม ({len(same_pos)}/{effective_max}"
            + (f" รวม {protected} protected" if protected else "") + ")"
        )

    # ── 2+3. opposing positions — ตรวจ protected / hedge buffer ──────
    if opp_pos:
        not_in_profit = [p for p in opp_pos if p.profit <= 0]
        if not_in_profit:
            def _is_sl_protected(p) -> bool:
                if p.sl == 0:
                    return False
                return (p.type == 0 and p.sl >= p.price_open) or \
                       (p.type == 1 and p.sl <= p.price_open)

            unprotected = [p for p in not_in_profit if not _is_sl_protected(p)]

            if not unprotected:
                # ทุก position ที่ไม่กำไร SL อยู่หน้าทุนแล้ว — ไม่มีความเสี่ยงเพิ่ม
                logger.debug(
                    f"{opp_name} not-in-profit แต่ SL protected ทั้งหมด → เปิด {direction} ได้"
                )
            else:
                # ตรวจ pip distance ของ unprotected positions vs hedge_buffer_pips
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
               comment: str = "", min_rr: float | None = None,
               confidence_scale: float = 1.0) -> dict:
    if _cfg.DRY_RUN:
        tick = mt5.symbol_info_tick(SYMBOL)
        price = (tick.ask if direction.upper() == "BUY" else tick.bid) if tick else 0.0
        logger.warning(f"[DRY_RUN] would have opened {direction} @ {price:.2f} SL={sl_pips}p TP={tp_pips}p")
        return {"success": True, "ticket": 0, "direction": direction,
                "lot": 0.0, "price": price, "sl": 0.0, "tp": 0.0, "dry_run": True}

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

    if _cfg.NNLB_MODE:
        lot, err = _nnlb_lot_and_check(account.equity, sl_pips)
        if err:
            return {"success": False, "error": err}
    else:
        lot = calculate_lot_size(account.balance, sl_pips, confidence_scale)

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

    if not _cfg.NNLB_MODE:
        # ตรวจ Risk/Reward ratio — ข้ามถ้า no_tp (ไม่มี TP ให้คำนวณ)
        effective_min_rr = min_rr if min_rr is not None else MONEY_MANAGEMENT["min_rr_ratio"]
        if not no_tp:
            actual_sl_pips = abs(price - sl) / point
            actual_tp_pips = abs(tp - price) / point
            rr = actual_tp_pips / actual_sl_pips if actual_sl_pips > 0 else 0
            if rr < effective_min_rr:
                logger.warning(f"RR ratio {rr:.2f} ต่ำกว่าขั้นต่ำ {effective_min_rr:.1f} (dynamic)")
                return {"success": False, "error": f"RR ratio too low: {rr:.2f} (min={effective_min_rr:.1f})"}

        # ตรวจจำนวน order ต่อฝั่ง (สอดคล้องกับ check_open_slot)
        dir_type = 0 if direction.upper() == "BUY" else 1
        open_positions = mt5.positions_get(symbol=SYMBOL) or []
        same_dir_count = sum(1 for p in open_positions if p.type == dir_type)
        effective_limit = MONEY_MANAGEMENT["max_open_trades"] + count_protected_slots()
        if same_dir_count >= effective_limit:
            return {"success": False, "error": "Max open trades reached"}

        # ตรวจ margin ก่อนส่ง — คำนวณ margin ที่ต้องการสำหรับ lot นี้
        margin_needed = mt5.order_calc_margin(order_type, SYMBOL, lot, price)
        if margin_needed is not None and account.equity < margin_needed:
            logger.warning(f"Margin ไม่พอ: ต้องการ {margin_needed:.2f}, equity {account.equity:.2f}")
            safe_lot = round((account.equity * 0.9) / (margin_needed / lot), 2) if lot > 0 else 0
            safe_lot = max(_cfg.MIN_LOT, min(safe_lot, lot))
            if safe_lot < _cfg.MIN_LOT:
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

    # ── Send order — retry สำหรับ requote / price_changed ───────────────
    result    = None
    last_err  = ""
    is_buy    = direction.upper() == "BUY"

    for attempt in range(_MAX_ORDER_RETRIES + 1):
        if attempt > 0:
            _time.sleep(_RETRY_DELAY_SEC)
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                break
            price = tick.ask if is_buy else tick.bid
            sl    = (price - sl_pips * point) if is_buy else (price + sl_pips * point)
            tp    = (0.0 if no_tp else price + tp_pips * point) if is_buy \
                    else (0.0 if no_tp else price - tp_pips * point)
            request["price"] = price
            request["sl"]    = round(sl, 2)
            request["tp"]    = round(tp, 2)
            logger.info(f"Order retry {attempt}/{_MAX_ORDER_RETRIES} @ {price:.2f}")

        result = mt5.order_send(request)
        if result is None:
            last_err = f"order_send None: {mt5.last_error()}"
            logger.warning(f"order_send returned None (attempt {attempt+1}): {last_err}")
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            break
        last_err = f"{result.retcode} — {result.comment}"
        if result.retcode not in _RETRYABLE_RETCODES:
            break   # error ถาวร ไม่ต้อง retry
        logger.warning(f"Order retryable error (attempt {attempt+1}): {last_err}")

    if result is None:
        logger.error(f"Order failed (all attempts): {last_err}")
        return {"success": False, "error": last_err}
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed: {last_err}")
        return {"success": False, "error": result.comment, "retcode": result.retcode}

    logger.info(f"Order opened: {direction} {lot} lots @ {price} SL={sl:.2f} TP={tp:.2f}")

    # ขยับ SL ฝั่งตรงข้ามทุก order มาหน้าทุนทันที (ไม่รอ 1000 pips)
    n = _force_breakeven_opposing(direction)
    logger.info(f"Force-BE result: {n} opposing position(s) protected after opening {direction}")

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


def get_current_price() -> float:
    """คืน bid price ปัจจุบันของ SYMBOL — ใช้ใน skip gate ตรวจ price spike"""
    tick = mt5.symbol_info_tick(SYMBOL)
    return float(tick.bid) if tick else 0.0


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
    if _cfg.DRY_RUN:
        logger.warning(f"[DRY_RUN] would have placed {pending_type} @ {price:.2f} SL={sl_pips}p TP={tp_pips}p")
        return {"success": True, "ticket": 0, "pending_type": pending_type,
                "price": price, "sl": 0.0, "tp": 0.0, "dry_run": True}

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

    if _cfg.NNLB_MODE:
        lot, err = _nnlb_lot_and_check(account.equity, sl_pips)
        if err:
            return {"success": False, "error": err}
    else:
        lot = calculate_lot_size(account.balance, sl_pips)

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


BREAKEVEN_BUFFER_PIPS  = 200    # fallback เมื่อ _cfg ยังไม่โหลด


def count_protected_slots() -> int:
    """คืนจำนวน open positions ที่ SL อยู่หน้าทุนแล้ว (ไม่มีความเสี่ยงขาดทุน)
    ใช้เพิ่ม slot สำหรับ order ใหม่ — 1 protected position = 1 extra slot"""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0
    info = mt5.symbol_info(SYMBOL)
    point = info.point if info else 0.01
    buf = getattr(_cfg, "BE_BUFFER_PIPS", BREAKEVEN_BUFFER_PIPS)
    count = 0
    for pos in positions:
        if pos.sl == 0:
            continue
        is_buy = pos.type == 0
        if is_buy  and pos.sl >= pos.price_open + buf * point:
            count += 1
        elif not is_buy and pos.sl <= pos.price_open - buf * point:
            count += 1
    return count


def manage_breakeven() -> int:
    """
    R-based breakeven พร้อม confirmation cycles:
    - trigger เมื่อ profit ≥ BE_TRIGGER_R × SL distance จริงของ position
    - ราคาต้องค้างอยู่เหนือ trigger BE_CONFIRM_CYCLES รอบติดกันก่อน SL จะย้าย
      (ป้องกัน "แตะแล้วดีดกลับ" ที่ HTF consolidation zone)

    Config (.env):
      BE_TRIGGER_R      = 0.8   # trigger ที่ 80% ของ SL distance
      BE_BUFFER_PIPS    = 200   # SL วางที่ entry + 200 pips
      BE_CONFIRM_CYCLES = 2     # ต้องค้างเหนือ trigger กี่ cycle ก่อน BE ย้าย
    """
    global _be_pending

    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return 0
    point = info.point

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        _be_pending.clear()
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 0

    default_trigger_r  = getattr(_cfg, "BE_TRIGGER_R",      0.8)
    default_buf_pips   = getattr(_cfg, "BE_BUFFER_PIPS",    BREAKEVEN_BUFFER_PIPS)
    confirm_need       = max(1, int(getattr(_cfg, "BE_CONFIRM_CYCLES", 2)))
    # HTF (D1/W1/MN) zone trades: wait longer before moving BE, lock more profit
    htf_trigger_r  = getattr(_cfg, "HTF_BE_TRIGGER_R",   1.5)   # trigger only at 1.5R
    htf_buf_pips   = getattr(_cfg, "HTF_BE_BUFFER_PIPS", 1000)  # lock 1,000 pips

    # ลบ tickets ที่ปิดแล้วออกจาก pending
    active_tickets = {p.ticket for p in positions}
    _be_pending = {t: c for t, c in _be_pending.items() if t in active_tickets}

    modified = 0
    for pos in positions:
        entry  = pos.price_open
        is_buy = pos.type == 0

        if pos.sl == 0:
            continue
        sl_dist_pips = abs(entry - pos.sl) / point
        if sl_dist_pips < 10:
            continue   # SL แคบเกินไป (อาจถูกขยับมา BE แล้ว)

        # ใช้ HTF settings ถ้า position ถูก register ว่าเปิดที่ D1/W1/MN zone
        # Fallback heuristic: ถ้า SL_dist > 1000p = likely HTF trade (process restarted)
        zone_info = _zone_state.get(pos.ticket, {})
        zone_tf   = zone_info.get("tf", "") if zone_info else ""
        is_htf    = zone_tf in ("D1", "W1", "MN1") or sl_dist_pips > 1000
        trigger_r = htf_trigger_r if is_htf else default_trigger_r

        current      = tick.bid if is_buy else tick.ask
        profit_pips  = ((current - entry) if is_buy else (entry - current)) / point
        trigger_pips = sl_dist_pips * trigger_r

        # Proportional buffer: lock 30% of current profit, minimum = default_buf_pips
        # ป้องกัน lock กำไรน้อยเกินไปเมื่อ position วิ่งไกลแล้ว
        if is_htf:
            buf_pips = max(htf_buf_pips, int(profit_pips * 0.30))
        else:
            buf_pips = max(default_buf_pips, int(profit_pips * 0.30))

        if is_htf and zone_tf:
            logger.debug(
                f"BE [{zone_tf} zone] ticket={pos.ticket}: "
                f"trigger={trigger_r}R buf={buf_pips}p profit={profit_pips:.0f}p"
            )

        if profit_pips < trigger_pips:
            # ราคาลงมาต่ำกว่า trigger — reset counter
            if pos.ticket in _be_pending:
                logger.debug(
                    f"BE reset ticket={pos.ticket}: profit {profit_pips:.0f}p < trigger {trigger_pips:.0f}p"
                )
                _be_pending.pop(pos.ticket)
            continue

        # นับ consecutive cycles ที่อยู่เหนือ trigger
        _be_pending[pos.ticket] = _be_pending.get(pos.ticket, 0) + 1
        cycles_ok = _be_pending[pos.ticket]

        if cycles_ok < confirm_need:
            logger.info(
                f"BE pending ticket={pos.ticket}: "
                f"profit={profit_pips:.0f}p ≥ trigger={trigger_pips:.0f}p "
                f"— รอ confirm {cycles_ok}/{confirm_need} cycles"
            )
            continue   # ยังไม่ถึง confirm threshold

        new_sl = round(entry + buf_pips * point, 2) if is_buy \
            else round(entry - buf_pips * point, 2)

        if is_buy  and pos.sl >= new_sl:
            _be_pending.pop(pos.ticket, None)
            continue
        if not is_buy and pos.sl <= new_sl:
            _be_pending.pop(pos.ticket, None)
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
                f"entry={entry:.2f} SL_dist={sl_dist_pips:.0f}p "
                f"trigger={trigger_pips:.0f}p profit={profit_pips:.0f}p "
                f"confirmed={cycles_ok}cycles  SL {pos.sl:.2f}→{new_sl:.2f}"
            )
            _be_pending.pop(pos.ticket, None)
            modified += 1

    return modified


# ── Partial Close ────────────────────────────────────────────────────────────
_partial_state: dict[int, dict] = {}   # ticket → {"done": set[str], "r_pips": float}
_be_pending:    dict[int, int]  = {}   # ticket → consecutive cycles above BE trigger
_MIN_R_PIPS    = 300                   # ต่ำกว่านี้ = SL ถูกขยับมา BE แล้ว ข้าม

# ── Zone-Break Close + False-Break Re-entry ──────────────────────────────────
_zone_state:                 dict[int, dict] = {}  # ticket → htf_zone dict
_zone_break_pending_reentry: list[dict]      = []  # [{zone, direction, since}]

ZONE_BREAK_BUFFER_PIPS = 800  # ปิดถ้า zone ทะลุเกิน 800 pips ($8) จาก level — gold noise ≈$3-5
ZONE_REENTRY_WINDOW_H  = 4    # re-entry window หลัง close (ชั่วโมง)


def _partial_close_pos(pos, lot: float, tick) -> bool:
    """ปิดบางส่วนของ position ที่ราคาตลาด"""
    is_buy      = pos.type == 0
    close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask
    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         close_type,
        "position":     pos.ticket,
        "price":        close_price,
        "deviation":    20,
        "magic":        SYSTEM_MAGIC,
        "comment":      _safe_comment("PARTIAL"),
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = result.retcode if result else mt5.last_error()
        logger.error(f"Partial close failed ticket={pos.ticket}: {err}")
        return False
    return True


def _set_sl_tp(ticket: int, new_sl: float, tp: float) -> bool:
    """ขยับ SL โดยไม่เปลี่ยน TP"""
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   SYMBOL,
        "position": ticket,
        "sl":       round(new_sl, 2),
        "tp":       tp,
    }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = result.retcode if result else mt5.last_error()
        logger.error(f"Set SL failed ticket={ticket}: {err}")
        return False
    return True


def manage_partial_close() -> int:
    """
    Scale out SYSTEM positions ที่ profit milestone:
    - 1R (profit ≥ original SL): ปิด 50%, ขยับ SL → Breakeven
    - 2R (profit ≥ 2× original SL): ปิด 60% ของที่เหลือ (=30% ของ original), trail SL 50% of move

    State เก็บ in-memory — reset เมื่อ bot restart (ปลอดภัยเพราะ guard r_pips < 300)
    Returns: จำนวน partial closes ที่ทำสำเร็จ
    """
    global _partial_state

    info = mt5.symbol_info(SYMBOL)
    if not info:
        return 0
    point = info.point

    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        _partial_state = {}
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return 0

    closed = 0
    active: set[int] = set()

    for pos in positions:
        if pos.magic != SYSTEM_MAGIC:
            continue

        ticket  = pos.ticket
        active.add(ticket)
        entry   = pos.price_open
        is_buy  = pos.type == 0
        current = tick.bid if is_buy else tick.ask

        # บันทึก original R ครั้งแรกที่เห็น ticket นี้
        if ticket not in _partial_state:
            if pos.sl == 0:
                continue
            r_pips = abs(entry - pos.sl) / point
            if r_pips < _MIN_R_PIPS:
                continue   # SL ถูกขยับมา BE แล้ว หรือ SL แคบเกิน — ข้าม
            _partial_state[ticket] = {"done": set(), "r_pips": r_pips}

        state       = _partial_state[ticket]
        r_pips      = state["r_pips"]
        done        = state["done"]
        profit_pips = ((current - entry) if is_buy else (entry - current)) / point

        # ── 1R: ปิด 50% ──────────────────────────────────────────────
        if "1R" not in done and profit_pips >= r_pips:
            lot = round(pos.volume * 0.50, 2)
            if lot >= info.volume_min:
                if _partial_close_pos(pos, lot, tick):
                    done.add("1R")
                    closed += 1
                    _buf = getattr(_cfg, "BE_BUFFER_PIPS", BREAKEVEN_BUFFER_PIPS)
                    be_sl = round(
                        entry + _buf * point if is_buy
                        else entry - _buf * point, 2
                    )
                    _set_sl_tp(ticket, be_sl, pos.tp)
                    logger.info(
                        f"Partial 1R: ticket={ticket} {'BUY' if is_buy else 'SELL'} "
                        f"ปิด {lot}lot profit={profit_pips:.0f}p → BE SL={be_sl:.2f}"
                    )
            else:
                logger.debug(f"Partial 1R skip ticket={ticket}: lot={pos.volume} < min×2")

        # ── 2R: ปิด 60% ของที่เหลือ (=30% original) ─────────────────
        elif "1R" in done and "2R" not in done and profit_pips >= r_pips * 2:
            lot = round(pos.volume * 0.60, 2)
            if lot >= info.volume_min:
                if _partial_close_pos(pos, lot, tick):
                    done.add("2R")
                    closed += 1
                    trail_sl = round(
                        entry + profit_pips * point * 0.50 if is_buy
                        else entry - profit_pips * point * 0.50, 2
                    )
                    _set_sl_tp(ticket, trail_sl, pos.tp)
                    logger.info(
                        f"Partial 2R: ticket={ticket} {'BUY' if is_buy else 'SELL'} "
                        f"ปิด {lot}lot profit={profit_pips:.0f}p → trail SL={trail_sl:.2f}"
                    )
            else:
                logger.debug(f"Partial 2R skip ticket={ticket}: lot={pos.volume} < min×2")

    # ลบ tickets ที่ปิดแล้ว
    _partial_state = {t: v for t, v in _partial_state.items() if t in active}
    return closed


def _force_breakeven_opposing(new_direction: str) -> int:
    """เมื่อเปิด order ใหม่ ขยับ SL ของทุก position ฝั่งตรงข้ามมาหน้าทุนทันที
    ไม่รอ BREAKEVEN_TRIGGER_PIPS — trigger เพราะมี order ฝั่งตรงข้ามเปิดใหม่"""
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        logger.warning("Force-BE: symbol_info None")
        return 0
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        logger.debug("Force-BE: no open positions")
        return 0
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logger.warning("Force-BE: tick None")
        return 0

    point    = info.point
    opp_type = 1 if new_direction == "BUY" else 0   # new BUY → protect SELL(1), new SELL → protect BUY(0)
    modified = 0

    logger.debug(
        f"Force-BE scan: new={new_direction} protecting={'SELL' if opp_type==1 else 'BUY'} "
        f"positions — total open={len(positions)} bid={tick.bid:.2f} ask={tick.ask:.2f}"
    )

    for pos in positions:
        tag = f"ticket={pos.ticket} type={'BUY' if pos.type==0 else 'SELL'} entry={pos.price_open:.2f} sl={pos.sl:.2f}"

        if pos.type != opp_type:
            logger.debug(f"Force-BE skip {tag}: same direction as new order")
            continue

        entry   = pos.price_open
        is_buy  = pos.type == 0
        current = tick.bid if is_buy else tick.ask
        profit_pips = ((current - entry) if is_buy else (entry - current)) / point

        # ข้ามถ้าขาดทุนอยู่ — ตั้ง BE ไม่ได้
        if profit_pips <= 0:
            logger.debug(f"Force-BE skip {tag}: in loss ({profit_pips:.0f}pips)")
            continue

        # ลด buffer ถ้ากำไรน้อยกว่า BE_BUFFER_PIPS
        _buf = getattr(_cfg, "BE_BUFFER_PIPS", BREAKEVEN_BUFFER_PIPS)
        safe_buffer = min(_buf, profit_pips - 10)
        if safe_buffer < 0:
            logger.debug(
                f"Force-BE skip {tag}: profit {profit_pips:.0f}pips too small (need >10 pips)"
            )
            continue

        new_sl = round(entry + safe_buffer * point, 2) if is_buy \
            else round(entry - safe_buffer * point, 2)

        # ข้ามถ้า SL อยู่หน้าทุนแล้ว
        if is_buy and pos.sl >= new_sl:
            logger.debug(f"Force-BE skip {tag}: SL already at/above BE ({pos.sl:.2f} >= {new_sl:.2f})")
            continue
        if not is_buy and pos.sl != 0 and pos.sl <= new_sl:
            logger.debug(f"Force-BE skip {tag}: SL already at/below BE ({pos.sl:.2f} <= {new_sl:.2f})")
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
            logger.error(f"Force-BE failed {tag}: order_send None — {mt5.last_error()}")
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Force-BE failed {tag}: retcode={result.retcode} comment={result.comment}")
        else:
            direction_str = "BUY" if is_buy else "SELL"
            logger.info(
                f"Force breakeven OK: ticket={pos.ticket} {direction_str} "
                f"entry={entry:.2f} profit={profit_pips:.0f}pips "
                f"SL {pos.sl:.2f}→{new_sl:.2f}"
            )
            modified += 1

    if modified == 0:
        logger.info("Force-BE: 0 positions modified (all skipped or no opposing positions)")
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


def _is_momentum_strong(direction: str, min_score: int = 4) -> bool:
    """
    ตรวจ momentum แบบ lightweight จากข้อมูล M15 โดยตรง — ไม่เรียก AI
    คืน True ถ้า momentum แรง (score ≥ min_score) สอดคล้องกับ direction
    สัญญาณ: RSI(14) slope, MACD hist + expansion, Price ROC(5), EMA stack
    max score = 5 (rsi 1 + macd 2 + roc 1 + ema 1) — min_score=5 = ต้อง align ครบ
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

    if roc5 >  0.15: up += 1    # 0.15% ≈ $5 move on gold — threshold ที่มีความหมาย
    elif roc5 < -0.15: dn += 1

    if ema_bull: up += 1
    elif ema_bear: dn += 1

    return (up >= min_score and up > dn) if is_buy else (dn >= min_score and dn > up)


# ── Momentum exit thresholds (STRICT) ────────────────────────────────
# เดิม 500p / 0.60 / score≥4 ตัดไม้เร็วเกินไป → ไม้ที่ drawdown ปกติถูกล็อกขาดทุน
# ก่อนได้โอกาสฟื้นไป TP (TP=3R). วิเคราะห์ DB: ไม้ถือ <30m = WR 34% avg -145฿,
# ไม้ถือ >8h = WR 73% avg +220฿ → ให้ไม้หายใจนานขึ้นคุ้มกว่ามาก
MOMENTUM_EXIT_MIN_LOSS_PIPS = 800   # floor (pips) — ต้องขาดทุน ≥$8 ก่อน (เดิม 500/$5)
MOMENTUM_EXIT_SL_FRACTION   = 0.85  # ต้องขาดทุน ≥85% ของ SL distance ก่อน trigger (เดิม 0.60)
MOMENTUM_EXIT_MIN_SCORE     = 5     # momentum ต้อง align ครบทุกสัญญาณ (เดิม 4)
M1_SPIKE_EXIT_PIPS          = 1000  # spike จริงเท่านั้น (flash crash/news) ออกทันที (เดิม 800)


def _is_1m_spike(counter_dir: str) -> bool:
    """
    คืน True ถ้า M1 candle ล่าสุด (หรือกำลังก่อตัว) วิ่งเกิน M1_SPIKE_EXIT_PIPS
    ในทิศ counter_dir (spike แรงผิดปกติ — flash crash / news spike)
    ใช้ 2 candles ล่าสุดเพื่อ detect เร็ว
    """
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 3)
    if bars is None or len(bars) < 2:
        return False
    sym_info = mt5.symbol_info(SYMBOL)
    if sym_info is None:
        return False
    point = sym_info.point
    is_sell = counter_dir.upper() == "SELL"
    for candle in bars[-2:]:   # candle ปิดแล้ว + candle กำลังก่อตัว
        rng        = (candle["high"] - candle["low"]) / point
        is_bearish = candle["close"] < candle["open"]
        if rng >= M1_SPIKE_EXIT_PIPS and (is_sell == is_bearish):
            return True
    return False


def manage_momentum_exit() -> int:
    """
    ปิด SYSTEM_MAGIC position ทันทีเมื่อ momentum แรงสวนทาง — ไม่รอ SL hit
    Trigger 1: loss >= MOMENTUM_EXIT_MIN_LOSS_PIPS + _is_momentum_strong(counter)
    Trigger 2: M1 spike >= M1_SPIKE_EXIT_PIPS ทิศสวน (ออกทันที ไม่ต้องรอ loss)
    """
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return 0

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 0

    sym_info = mt5.symbol_info(SYMBOL)
    if sym_info is None:
        return 0
    point   = sym_info.point
    closed  = 0

    for pos in positions:
        if pos.magic != SYSTEM_MAGIC:
            continue

        is_buy       = pos.type == 0
        current      = tick.bid if is_buy else tick.ask
        profit_pips  = ((current - pos.price_open) if is_buy else (pos.price_open - current)) / point
        counter_dir  = "SELL" if is_buy else "BUY"

        # threshold = max(floor, 60% of actual SL distance) — ป้องกัน exit ก่อน SL ถึง
        sl_dist_pips = abs(pos.price_open - pos.sl) / point if pos.sl > 0 else 0
        threshold    = max(MOMENTUM_EXIT_MIN_LOSS_PIPS, sl_dist_pips * MOMENTUM_EXIT_SL_FRACTION)

        spike    = _is_1m_spike(counter_dir)
        momentum = profit_pips <= -threshold and _is_momentum_strong(counter_dir, MOMENTUM_EXIT_MIN_SCORE)

        if not spike and not momentum:
            continue

        reason = "M1_SPIKE" if spike else "MOMENTUM_STRONG"
        tag = (
            f"ticket={pos.ticket} {'BUY' if is_buy else 'SELL'} "
            f"entry={pos.price_open:.2f} pnl={profit_pips:.0f}pips "
            f"(threshold={threshold:.0f}p) [{reason}]"
        )

        if DRY_RUN:
            logger.info(f"[DRY_RUN] Momentum exit would close: {tag}")
            continue

        req = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    SYMBOL,
            "volume":    pos.volume,
            "type":      mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position":  pos.ticket,
            "price":     tick.bid if is_buy else tick.ask,
            "deviation": 20,
            "magic":     SYSTEM_MAGIC,
            "comment":   "MOMENTUM_EXIT",
        }
        result = mt5.order_send(req)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error() if result is None else f"retcode={result.retcode} comment={result.comment}"
            logger.error(f"Momentum exit FAILED {tag}: {err}")
        else:
            logger.warning(f"[MOMENTUM_EXIT] Closed early: {tag}")
            closed += 1

    return closed


def manage_zone_break_close(chart_data: dict) -> int:
    """
    ปิด SYSTEM_MAGIC position เมื่อ HTF zone ที่เข้า trade ถูกทะลุจริง
    แล้วรอ false break — ถ้า M15 close กลับข้าม zone level ภายใน ZONE_REENTRY_WINDOW_H
    → re-enter ใหม่ทันที (false breakout recovery)

    Zone break: M15 close ต่ำกว่า SUPPORT − buffer (BUY)
                          สูงกว่า RESISTANCE + buffer (SELL)
    """
    from datetime import datetime, timedelta, timezone as _tz

    global _zone_state, _zone_break_pending_reentry

    positions = mt5.positions_get(symbol=SYMBOL) or []
    info      = mt5.symbol_info(SYMBOL)
    tick      = mt5.symbol_info_tick(SYMBOL)
    if not info or not tick:
        return 0
    point = info.point

    # ลบ tickets ที่ปิดแล้ว
    active      = {p.ticket for p in positions}
    _zone_state = {t: z for t, z in _zone_state.items() if t in active}

    # M15 แท่งปิดล่าสุด (index=1 = completed candle)
    m15_rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 1, 1)
    if m15_rates is None or len(m15_rates) == 0:
        return 0
    m15_close = float(m15_rates["close"][0])

    buffer  = ZONE_BREAK_BUFFER_PIPS * point
    actions = 0

    # ── Phase 1: ตรวจ zone break → force close ───────────────────────────────
    for pos in positions:
        if pos.magic != SYSTEM_MAGIC:
            continue
        is_buy = pos.type == 0

        # Auto-register: ใช้ htf_zone ใน chart_data ถ้าใกล้ entry price (< 0.8%)
        if pos.ticket not in _zone_state:
            htf = chart_data.get("htf_zone")
            if htf and abs(pos.price_open - htf["level"]) / max(pos.price_open, 1) * 100 < 0.8:
                _zone_state[pos.ticket] = htf
                logger.info(
                    f"[ZONE] registered ticket={pos.ticket} "
                    f"{htf['tf']} {htf['zone_type']} @ {htf['level']:.2f}"
                )
            continue  # รอรอบหน้า (เพิ่ง register หรือ register ไม่ได้)

        zone  = _zone_state[pos.ticket]
        level = zone["level"]
        ztype = zone["zone_type"]

        broke = (    is_buy and ztype == "SUPPORT"    and m15_close < level - buffer) or \
                (not is_buy and ztype == "RESISTANCE" and m15_close > level + buffer)
        if not broke:
            continue

        dir_str = "BUY" if is_buy else "SELL"
        if _cfg.DRY_RUN:
            logger.warning(
                f"[DRY_RUN][ZONE BREAK] would close {dir_str} ticket={pos.ticket} "
                f"— {ztype} @ {level:.2f} ทะลุ (M15={m15_close:.2f})"
            )
        else:
            close_price = tick.bid if is_buy else tick.ask
            req = mt5.order_send({
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       SYMBOL,
                "volume":       pos.volume,
                "type":         mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position":     pos.ticket,
                "price":        close_price,
                "deviation":    20,
                "magic":        SYSTEM_MAGIC,
                "comment":      _safe_comment("ZONE_BREAK"),
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })
            if req is None or req.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"[ZONE BREAK] close failed ticket={pos.ticket}: "
                    f"{req.retcode if req else mt5.last_error()}"
                )
                continue
            logger.warning(
                f"[ZONE BREAK] closed {dir_str} ticket={pos.ticket} @ {close_price:.2f} "
                f"| {zone['tf']} {ztype} @ {level:.2f} ทะลุ {abs(m15_close - level) / point:.0f}p"
            )

        # เก็บไว้รอ false-break re-entry (ทั้ง live + DRY_RUN)
        _zone_break_pending_reentry.append({
            "zone":      zone,
            "direction": "BUY" if is_buy else "SELL",
            "since":     datetime.now(_tz.utc),
        })
        del _zone_state[pos.ticket]
        actions += 1

    # ── Phase 2: False Break → Re-entry ──────────────────────────────────────
    now   = datetime.now(_tz.utc)
    still = []

    for pending in _zone_break_pending_reentry:
        if now - pending["since"] > timedelta(hours=ZONE_REENTRY_WINDOW_H):
            logger.info(
                f"[ZONE BREAK] re-entry window expired: "
                f"{pending['direction']} zone @ {pending['zone']['level']:.2f}"
            )
            continue  # หมดเวลา — ทิ้งไป

        zone  = pending["zone"]
        level = zone["level"]
        ztype = zone["zone_type"]
        dirc  = pending["direction"]

        # ตรวจ recovery: M15 close กลับข้าม zone level
        recovered = (dirc == "BUY"  and m15_close > level) or \
                    (dirc == "SELL" and m15_close < level)
        if not recovered:
            still.append(pending)
            continue

        # มี position ทิศนี้อยู่แล้ว → ไม่ re-enter ซ้ำ
        same_open = [p for p in positions
                     if p.magic == SYSTEM_MAGIC and p.type == (0 if dirc == "BUY" else 1)]
        if same_open:
            logger.info(f"[ZONE BREAK] re-entry skip: มี {dirc} position อยู่แล้ว")
            continue  # consumed — ไม่ใส่กลับ still

        sl_pips = float(MONEY_MANAGEMENT["default_sl_pips"])
        tp_pips = float(MONEY_MANAGEMENT["default_tp_pips"])
        logger.warning(
            f"[ZONE BREAK] false break confirmed — re-entering {dirc} @ M15={m15_close:.2f} "
            f"({zone['tf']} {ztype} @ {level:.2f} recovered)"
        )
        result = open_order(dirc, sl_pips, tp_pips, comment="ZONE_REENTRY")
        if result.get("success"):
            new_ticket = result.get("ticket", 0)
            if new_ticket and new_ticket > 0:
                _zone_state[new_ticket] = zone   # re-register zone ให้ position ใหม่
            actions += 1
        else:
            logger.error(f"[ZONE BREAK] re-entry failed: {result.get('error')}")

    _zone_break_pending_reentry = still
    return actions


def manage_dynamic_tp() -> int:
    """
    ตรวจ open positions ที่กำไร — เมื่อราคาเข้าใกล้ TP และ momentum แรง
    ขยับ TP ออกไปอีก TP_EXT_PIPS (สูงสุด TP_EXT_MAX ครั้ง)
    คืนจำนวน positions ที่ขยาย TP
    """
    if not _cfg.DYNAMIC_TP:
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


def _find_sr_tp(entry: float, is_buy: bool, chart_data: dict, point: float) -> float | None:
    """
    หา S/R level ที่ใกล้ที่สุดในทิศทาง TP จาก chart_data
    BUY  → resistance ที่ต่ำสุดที่สูงกว่า entry (จะเดินไปชน)
    SELL → support ที่สูงสุดที่ต่ำกว่า entry
    คืน None ถ้าหาไม่เจอ
    """
    sr = chart_data.get("sr_zones", {})
    min_dist = entry * 0.001   # ห่างขั้นต่ำ 0.1% จาก entry

    if is_buy:
        candidates = [r for r in sr.get("resistance", []) if r > entry + min_dist]
        return round(min(candidates), 2) if candidates else None
    else:
        candidates = [s for s in sr.get("support", []) if s < entry - min_dist]
        return round(max(candidates), 2) if candidates else None


def manage_post_event_tp(chart_data: dict | None = None) -> int:
    """
    ตรวจ open positions ที่เปิดแบบ No-TP (tp=0) — เมื่อเวลาผ่านไปครบ NO_TP_WAIT_MINUTES
    และ momentum สงบแล้ว ให้ตั้ง TP ที่ S/R level ใกล้สุด (ถ้ามี) หรือ default_tp_pips
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
    min_rr          = MONEY_MANAGEMENT["min_rr_ratio"]
    set_count = 0

    for pos in positions:
        if pos.tp != 0:
            continue   # มี TP แล้ว — ข้าม

        is_buy       = pos.type == 0
        direction    = "BUY" if is_buy else "SELL"
        elapsed_mins = (now - pos.time) / 60

        if elapsed_mins < _cfg.NO_TP_WAIT_MINUTES:
            logger.debug(
                f"No-TP ticket={pos.ticket} — รออีก {_cfg.NO_TP_WAIT_MINUTES - elapsed_mins:.0f}min"
            )
            continue

        # ยังรอ momentum สงบ
        if _is_momentum_strong(direction):
            logger.info(
                f"No-TP ticket={pos.ticket} — elapsed {elapsed_mins:.0f}min "
                "แต่ momentum ยังแรง — รอต่อ"
            )
            continue

        entry   = pos.price_open
        sl_dist = abs(entry - pos.sl) / point if pos.sl else default_tp_pips / min_rr

        # ── หา TP จาก S/R level ก่อน ──────────────────────────────
        sr_tp = _find_sr_tp(entry, is_buy, chart_data or {}, point)
        if sr_tp is not None:
            sr_dist = abs(sr_tp - entry) / point
            rr      = sr_dist / sl_dist if sl_dist > 0 else 0
            if rr >= min_rr * 0.8:   # ผ่อนปรน 20% เพราะเปิดไปแล้ว
                new_tp = sr_tp
                logger.info(
                    f"No-TP ticket={pos.ticket} {direction} "
                    f"ตั้ง TP ที่ S/R {new_tp:.2f} (dist={sr_dist:.0f}pips RR={rr:.2f})"
                )
            else:
                sr_tp = None   # RR ต่ำเกิน → ใช้ default แทน

        if sr_tp is None:
            # fallback: fixed pips จาก entry
            new_tp = round(entry + default_tp_pips * point, 2) if is_buy \
                else round(entry - default_tp_pips * point, 2)
            logger.info(
                f"No-TP ticket={pos.ticket} {direction} "
                f"ตั้ง TP default {new_tp:.2f} (ไม่มี S/R หรือ RR ต่ำ)"
            )

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
    if _cfg.DRY_RUN:
        logger.warning(f"[DRY_RUN] would have cancelled pending ticket={ticket}")
        return True

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
