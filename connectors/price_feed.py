import os
import time
import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL
from loguru import logger

AI_QUIET_RATIO = float(os.getenv("AI_QUIET_RATIO") or 0.6)  # recent/ref range < นี้ = เงียบจริง


def is_mt5_connected() -> bool:
    """ตรวจว่า MT5 ยังต่ออยู่ไหม โดยไม่ทำ initialize/shutdown"""
    try:
        info = mt5.terminal_info()
        if info is None:
            return False
        acc = mt5.account_info()
        return acc is not None
    except Exception:
        return False


def connect_mt5() -> bool:
    # Clear stale IPC state จาก connection เดิมที่ค้าง (ป้องกัน IPC timeout)
    try:
        mt5.shutdown()
    except Exception:
        pass

    # initialize + login ในขั้นตอนเดียว พร้อม timeout 10s (default 60s นานเกิน)
    ok = mt5.initialize(
        login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER,
        timeout=10000,
    )
    if not ok:
        err = mt5.last_error()
        logger.error(f"MT5 initialize failed: {err}")
        # ถ้าเป็น IPC timeout ลอง shutdown แล้ว retry 1 ครั้งแบบ initialize-only
        if err and err[0] == -10005:
            time.sleep(2)
            try:
                mt5.shutdown()
            except Exception:
                pass
            time.sleep(1)
            if not mt5.initialize(timeout=10000):
                logger.error(f"MT5 retry initialize failed: {mt5.last_error()}")
                return False
            if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                return False
        else:
            return False
    logger.info(f"MT5 connected — account: {MT5_LOGIN}")

    # enable symbol และหาชื่อที่ถูกต้อง
    _enable_symbol(SYMBOL)
    return True


def _enable_symbol(symbol: str):
    """เปิดใช้งาน symbol ใน MT5 และตรวจสอบชื่อที่ถูกต้อง"""
    info = mt5.symbol_info(symbol)
    if info is None:
        # ลองค้นหาชื่อที่คล้ายกัน
        all_symbols = mt5.symbols_get()
        candidates = [s.name for s in all_symbols if "XAU" in s.name or "GOLD" in s.name.upper()]
        logger.warning(f"Symbol '{symbol}' ไม่พบ — ชื่อที่อาจใช้ได้: {candidates}")
        return False

    if not info.visible:
        mt5.symbol_select(symbol, True)
        logger.info(f"เปิดใช้งาน symbol: {symbol}")

    logger.info(f"Symbol OK: {symbol} | Digits: {info.digits} | Point: {info.point}")
    return True


def disconnect_mt5():
    mt5.shutdown()
    logger.info("MT5 disconnected")


def get_current_price(symbol: str = SYMBOL) -> dict:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"Cannot get tick for {symbol}: {mt5.last_error()}")
        return {}
    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "time": tick.time,
    }


def get_ohlcv(symbol: str = SYMBOL, timeframe=mt5.TIMEFRAME_H1, count: int = 100):
    mt5.symbol_select(symbol, True)
    for attempt in range(3):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is not None and len(rates) > 0:
            return rates
        err = mt5.last_error()
        if attempt < 2:
            logger.debug(f"OHLCV retry {attempt+1}/3 for {symbol}: {err}")
            time.sleep(1.5)
    logger.error(f"Cannot get OHLCV for {symbol}: {mt5.last_error()}")
    return None


def recent_movement(lookback: int = 50, recent_n: int = 4) -> dict:
    """Cheap pure-data movement probe (NO AI call) for the idle AI-throttle gate.

    Self-calibrating: compares the last `recent_n` M15 bars' average range to the
    median range of the last `lookback` bars, so 'quiet' adapts to the current
    volatility regime instead of a hardcoded pip value. Measured data showed even
    the quietest UTC hours carry a tail of large bars (a $30-46 M15 move in the
    'Late'/Asian session), so the gate MUST read realized movement, never the
    clock — extending the throttle only when the market is genuinely flat.

    Returns {ok, recent_atr_pts, ref_med_pts, ratio, last_range_pts, quiet}.
    Any failure → ok=False, quiet=False (fail-safe: run AI as usual, never skip).
    """
    try:
        rates = get_ohlcv(timeframe=mt5.TIMEFRAME_M15, count=lookback)
        if rates is None or len(rates) < recent_n + 10:
            return {"ok": False, "quiet": False}
        import numpy as np
        rng = (rates["high"] - rates["low"]) / 0.01          # per-bar range in points
        ref_med    = float(np.median(rng))
        recent_atr = float(np.mean(rng[-recent_n:]))
        ratio = recent_atr / ref_med if ref_med > 0 else 1.0
        return {"ok": True, "recent_atr_pts": recent_atr, "ref_med_pts": ref_med,
                "ratio": ratio, "last_range_pts": float(rng[-1]),
                "quiet": ratio < AI_QUIET_RATIO}
    except Exception as e:
        logger.debug(f"recent_movement probe failed: {e}")
        return {"ok": False, "quiet": False}


def get_account_info() -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "currency": info.currency,
    }
