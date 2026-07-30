"""agents/htf_levels.py — D1/W1 swing-pivot S/R levels, symbol-agnostic. pure, 0 token, 0 order.

หา swing pivot (fractal high/low) จากบาร์ day+ ต่อ symbol → คืนแนวใกล้สุดฝั่งบน/ล่างของราคา.
ใช้เป็น "แหล่งโครงสร้าง" ให้ structural_sl วาง SL พิงแนวจริง (คู่ MSE ไม่มี chart_watcher จึงต้องมี source นี้).

CORE INVARIANT: level = swing จริงจาก closed bar (ไม่ prediction, ไม่มี AI).
"""


def _pivots(high, low, left=2, right=2, max_keep=60):
    """swing highs + lows จากบาร์ปิด (ตัดบาร์กำลังก่อตัว = index สุดท้าย).
    swing high[i] = high[i] ≥ ทุกบาร์ใน [i-left, i+right]; swing low ตรงข้าม. คืน list ของ level (float)."""
    n = len(high)
    levels = []
    last_closed = n - 2                                   # บาร์ปิดล่าสุด (เหมือน algo อื่นใช้ n-2)
    for i in range(left, last_closed - right + 1):
        h_win = [float(high[j]) for j in range(i - left, i + right + 1)]
        l_win = [float(low[j]) for j in range(i - left, i + right + 1)]
        hi = float(high[i]); lo = float(low[i])
        if hi >= max(h_win):
            levels.append(hi)
        if lo <= min(l_win):
            levels.append(lo)
    return levels[-max_keep:] if max_keep else levels


def _dedup(levels, tol):
    """รวมแนวที่ห่างกัน ≤ tol เป็นตัวเดียว (ค่าเฉลี่ย) — กันแนวซ้ำถี่ๆ."""
    if not levels:
        return []
    out = []
    for lv in sorted(levels):
        if out and abs(lv - out[-1]) <= tol:
            out[-1] = (out[-1] + lv) / 2.0
        else:
            out.append(lv)
    return out


def nearest_levels(bars_by_tf, price, atr=0.0, left=2, right=2):
    """แนว D1/W1 ที่ใกล้ราคาที่สุดฝั่งบน (resistance) / ล่าง (support).

    bars_by_tf = {"D1": (high, low, close, times), "W1": (...)} — arrays newest last.
    atr ใช้ตั้ง tolerance dedup (0.5·ATR); 0 → ข้าม dedup.
    คืน {"support": {"level","tf"} | None, "resistance": {...} | None, "n": int}.
    """
    price = float(price)
    tagged = []                                            # (level, tf)
    for tf, bars in (bars_by_tf or {}).items():
        if not bars:
            continue
        high, low, close, _t = bars
        if high is None or len(high) < left + right + 3:
            continue
        for lv in _pivots(high, low, left, right):
            tagged.append((lv, tf))
    if not tagged:
        return {"support": None, "resistance": None, "n": 0}

    tol = 0.5 * float(atr) if atr and atr > 0 else 0.0
    # dedup ต่อ tf (เก็บ tf tag) — รวมข้าม tf ไม่ทำ (แนว W1 กับ D1 แยกความหมาย)
    by_tf = {}
    for lv, tf in tagged:
        by_tf.setdefault(tf, []).append(lv)
    merged = []
    for tf, lvs in by_tf.items():
        for lv in (_dedup(lvs, tol) if tol else sorted(set(lvs))):
            merged.append((lv, tf))

    below = [(lv, tf) for lv, tf in merged if lv < price]
    above = [(lv, tf) for lv, tf in merged if lv > price]
    sup = max(below, key=lambda x: x[0]) if below else None     # แนวล่างที่สูงสุด (ใกล้ราคา)
    res = min(above, key=lambda x: x[0]) if above else None     # แนวบนที่ต่ำสุด (ใกล้ราคา)
    return {
        "support": {"level": round(sup[0], 5), "tf": sup[1]} if sup else None,
        "resistance": {"level": round(res[0], 5), "tf": res[1]} if res else None,
        "n": len(merged),
    }


def last_closed_wick(symbol, tf="D1"):
    """(high, low) ของแท่ง TF **ปิดล่าสุด** (index -2; -1 = แท่งกำลังก่อตัว) ต่อ symbol. None ถ้าดึงไม่ได้.
    tf ∈ {H4,D1,W1}. ใช้วาง SL ปลายไส้ (structural_sl). broker symbol เช่น OILCash#, GOLD#."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        tfmap = {"H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1}
        mt5_tf = tfmap.get(tf)
        if mt5_tf is None:
            return None
        r = get_ohlcv(symbol=symbol, timeframe=mt5_tf, count=5)
        if r is None or len(r) < 2:
            return None
        i = len(r) - 2                                     # แท่งปิดล่าสุด
        return (float(r["high"][i]), float(r["low"][i]))
    except Exception:
        return None


_TF_COUNT = {"D1": 400, "W1": 260, "H4": 500}                   # W1 260 ≈ 5 ปี


def from_mt5(symbol, price, tfs=("D1", "W1"), atr=0.0, count=None):
    """ดึงบาร์ day+ ต่อ symbol จาก MT5 → nearest_levels. fail-soft: คืน {} เมื่อดึงไม่ได้.
    symbol = broker symbol (เช่น OILCash#, GOLD#). ใช้ได้ทั้ง MSE + gold."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        tfmap = {"D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1, "H4": mt5.TIMEFRAME_H4}
        bars_by_tf = {}
        for tf in tfs:
            mt5_tf = tfmap.get(tf)
            if mt5_tf is None:
                continue
            c = count or _TF_COUNT.get(tf, 300)
            rates = get_ohlcv(symbol=symbol, timeframe=mt5_tf, count=c)
            if rates is None or len(rates) < 10:
                continue
            bars_by_tf[tf] = (rates["high"].astype(float), rates["low"].astype(float),
                              rates["close"].astype(float), rates["time"])
        if not bars_by_tf:
            return {}
        return nearest_levels(bars_by_tf, price, atr=atr)
    except Exception:
        return {}
