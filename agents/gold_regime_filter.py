"""agents/gold_regime_filter.py — block-neutral filter (gold-fit tune, user 08-22).

backtest (scripts/trend_filter_backtest.py): momentum_breakout ทองตอน **D1-drift NEUTRAL** (choppy) =
เจ๊ง robust (−0.199R t−2.62 ลบทุก quartile). block slice นี้ → gold algo −0.054→−0.018 (ตัด loss 74%);
+ long-bias → +0.047. = gold-fit (เลี่ยง chop + ตาม drift). ⚠️ drift-harvest ไม่ใช่ alpha (t0.93 ไม่ significant).

drift state = causal EMA(480≈D1-MA20 บน H1) + slope — **parity เป๊ะกับ backtest _trend** (n=480, lb=48).
UP = close>ema & ema rising · DOWN = ตรงข้าม · NEUTRAL = อื่น (block ตอนนี้). block-only, fail-open, 0 token.
flag: TREND_BLOCK_NEUTRAL (enforce) · TREND_BLOCK_NEUTRAL_SHADOW (log-only). default shadow.
"""
from loguru import logger

_EMA_N = 480
_SLOPE_LB = 48


def _cfg(n, d):
    import config as _c
    return getattr(_c, n, d)


def _ema(x, n):
    a = 2.0 / (n + 1.0)
    out = x[0]
    e = [out]
    for v in x[1:]:
        out = a * v + (1 - a) * out
        e.append(out)
    return e


def _broker_sym(symbol):
    """map logical → broker symbol (XAUUSD→GOLD#). ทองใช้ config.SYMBOL."""
    if symbol in (None, "XAUUSD", "GOLD"):
        return _cfg("SYMBOL", "GOLD#")
    try:
        from connectors.pair_collector import _broker_map
        return (_broker_map() or {}).get(symbol, symbol)
    except Exception:
        return symbol


def drift_state(symbol=None):
    """causal D1-drift proxy บน H1 closed bars. คืน 'UP'|'DOWN'|'NEUTRAL'|None(data ไม่พอ). fail-soft."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        need = _EMA_N + _SLOPE_LB + 5
        r = get_ohlcv(symbol=_broker_sym(symbol), timeframe=mt5.TIMEFRAME_H1, count=need + 5)
        if r is None or len(r) < need:
            return None
        c = [float(x["close"]) for x in r][:-1]              # ตัดแท่งกำลังก่อตัว (causal)
        if len(c) < need:
            return None
        e = _ema(c, _EMA_N)
        i = len(c) - 1
        rising = e[i] > e[i - _SLOPE_LB]
        if c[i] > e[i] and rising:
            return "UP"
        if c[i] < e[i] and not rising:
            return "DOWN"
        return "NEUTRAL"
    except Exception as ex:
        logger.debug("[GOLD-REGIME] drift_state fail-soft: %s" % ex)
        return None


def blocks_neutral(symbol="XAUUSD"):
    """(block, reason). block=True ถ้า D1-drift NEUTRAL (choppy = slice ที่เจ๊ง). shadow → log-only คืน False.
    ไม่เปิด flag → pass-through. fail-open (drift None → ไม่ block)."""
    if not _cfg("TREND_BLOCK_NEUTRAL", False):
        return False, ""
    st = drift_state(symbol)
    if st is None or st != "NEUTRAL":
        return False, ""
    if _cfg("TREND_BLOCK_NEUTRAL_SHADOW", True):
        logger.info("[GOLD-REGIME] would-block %s: D1-drift NEUTRAL (shadow — ไม่ block จริง)" % symbol)
        return False, "shadow: D1-neutral"
    logger.warning("[GOLD-REGIME] BLOCK %s: D1-drift NEUTRAL (choppy = slice เจ๊ง −0.199R)" % symbol)
    return True, "D1-drift NEUTRAL (block-neutral filter)"
