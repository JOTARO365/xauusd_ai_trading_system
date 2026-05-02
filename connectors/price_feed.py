import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL
from loguru import logger


def connect_mt5() -> bool:
    if not mt5.initialize():
        logger.error(f"MT5 initialize failed: {mt5.last_error()}")
        return False
    if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        logger.error(f"MT5 login failed: {mt5.last_error()}")
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
    # ตรวจสอบ symbol ก่อนดึงข้อมูล
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        logger.error(f"Cannot get OHLCV for {symbol}: {mt5.last_error()}")
        return None
    return rates


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
