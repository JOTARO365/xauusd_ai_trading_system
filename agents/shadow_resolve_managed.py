"""agents/shadow_resolve_managed.py — paper-order resolver ที่ผ่าน management จริง (BE + trailing + SL/TP).

ต่างจาก shadow_resolve (เชิงกล SL/TP/timeout ตายตัว): ตัวนี้จำลอง "paper order" ที่เดินทีละแท่ง แล้ว
manage เหมือน live — breakeven (BE_TRIGGER_R → ย้าย SL เป็น entry±BE_BUFFER) + swing/ATR trailing
(หลัง TRAILING_MIN_PROFIT_R) → SL ที่ขยับได้ → realized R สะท้อนของจริง (ไม่ใช่แค่ entry ดิบ).

ใช้ config เดียวกับ live (BE_TRIGGER_R/BE_BUFFER_PIPS/TRAILING_*). SL-first บนบาร์กำกวม (pessimistic).
READ-ONLY (คำนวณล้วน ไม่แตะ MT5/order). ใช้โดย backtest ที่ regen สถิติ shadow.
"""
import config as _cfg


def _cfgf(name, default):
    try:
        return float(getattr(_cfg, name, default))
    except Exception:
        return default


def _simple_atr(high, low, close, period=14):
    """ATR(14) Wilder inline (self-contained — ไม่พึ่ง regime_lib ที่อยู่ใน scripts/)."""
    n = len(close)
    out = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = float(high[i]), float(low[i]), float(close[i - 1])
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    s = 0.0
    for i in range(1, n):
        if i <= period:
            s += tr[i]
            out[i] = s / i
        else:
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def _find_i0(times, bar_ts):
    """หา index ของแท่ง entry จาก bar_ts (iso) — สำหรับ forward engine ที่ไม่ส่ง i0."""
    if bar_ts is None:
        return None
    from datetime import datetime, timezone
    for k in range(len(times)):
        if datetime.fromtimestamp(int(times[k]), timezone.utc).isoformat() == bar_ts:
            return k
    return None


def resolve_managed(rec, high, low, close, times, atr_v=None, *, point, cost_pips,
                    max_hold_bars, price_digits=2, i0=None):
    """เดิน paper order จากบาร์ i0 → คืน outcome dict (result TP/SL/TIMEOUT, realized_R net, bars_held, mfe/mae R).
    SL/TP เป็น pips (จาก signal); BE/trailing ปรับ sl_price ระหว่างทาง. R วัดเทียบ SL distance เริ่มต้น.
    i0/atr_v = None → หา/คำนวณเอง (drop-in สำหรับ shadow_engine forward)."""
    if i0 is None:
        i0 = _find_i0(times, rec.get("bar_ts"))
        if i0 is None:
            return None
    if atr_v is None:
        atr_v = _simple_atr(high, low, close)
    is_buy = rec["dir"] == "BUY"
    entry = float(rec["entry"])
    sl_pips0 = float(rec["sl_pips"])
    tp_pips = float(rec["tp_pips"])
    if sl_pips0 <= 0:
        return None
    sl_dist = sl_pips0 * point                                  # ระยะ SL เริ่มต้น (ราคา) = 1R
    sl_price = entry - sl_dist if is_buy else entry + sl_dist
    tp_price = (entry + tp_pips * point) if is_buy else (entry - tp_pips * point)
    has_tp = tp_pips > 0

    # config management (เหมือน live)
    be_trig_r = _cfgf("BE_TRIGGER_R", 0.8)
    be_buf = _cfgf("BE_BUFFER_PIPS", 200) * point
    tr_on = bool(getattr(_cfg, "TRAILING_STOP", False))
    tr_min_r = _cfgf("TRAILING_MIN_PROFIT_R", 1.5)
    tr_mult = _cfgf("TRAILING_ATR_MULT", 0.8)
    tr_look = int(_cfgf("TRAILING_LOOKBACK", 6))
    cost_price = cost_pips * point

    n = len(close)
    mfe = mae = 0.0
    be_done = False

    def _r(px):                                                # R (net cost) ที่ราคา px
        raw = (px - entry) if is_buy else (entry - px)
        return (raw - cost_price) / sl_dist

    for j in range(i0 + 1, n):
        hi, lo = float(high[j]), float(low[j])
        fav = (hi - entry) if is_buy else (entry - lo)         # excursion บวกสุดของบาร์
        adv = (entry - lo) if is_buy else (hi - entry)
        mfe = max(mfe, fav / sl_dist)
        mae = min(mae, -adv / sl_dist)
        hit_sl = (lo <= sl_price) if is_buy else (hi >= sl_price)
        hit_tp = has_tp and ((hi >= tp_price) if is_buy else (lo <= tp_price))
        if hit_sl and hit_tp:                                  # กำกวม → SL-first
            hit_tp = False
        if hit_sl:
            r = _r(sl_price)
            res = "TP" if r > 0 else "SL"                      # SL ที่ขยับหนีทุน = ปิดบวก (นับ TP-ish)
            return _out(res, r, j - i0, sl_price, times[j], mfe, mae, price_digits)
        if hit_tp:
            return _out("TP", _r(tp_price), j - i0, tp_price, times[j], mfe, mae, price_digits)

        # ── manage: อัปเดต SL จาก close ของบาร์นี้ (เหมือน per-cycle) ──
        c = float(close[j])
        prof_r = ((c - entry) if is_buy else (entry - c)) / sl_dist
        # breakeven: profit ≥ trigger → ย้าย SL เป็น entry ± buffer (improve เท่านั้น)
        if not be_done and prof_r >= be_trig_r:
            be_sl = entry + be_buf if is_buy else entry - be_buf
            if (be_sl > sl_price) if is_buy else (be_sl < sl_price):
                sl_price = be_sl
            be_done = True
        # trailing: หลัง min_profit_r → trail ที่ swing(look) ± mult×ATR
        if tr_on and prof_r >= tr_min_r and j >= tr_look:
            atr = float(atr_v[j]) if atr_v is not None and j < len(atr_v) else 0.0
            if atr > 0:
                buf = tr_mult * atr
                if is_buy:
                    swing = min(float(low[k]) for k in range(j - tr_look, j))
                    t_sl = swing - buf
                    if t_sl > sl_price:
                        sl_price = t_sl
                else:
                    swing = max(float(high[k]) for k in range(j - tr_look, j))
                    t_sl = swing + buf
                    if t_sl < sl_price:
                        sl_price = t_sl
        if (j - i0) >= max_hold_bars:                          # timeout → mark-to-market
            return _out("TIMEOUT", _r(c), j - i0, c, times[j], mfe, mae, price_digits)

    return {"result": "OPEN", "bars_held": n - 1 - i0}         # tail: ยังไม่จบ (backtest ตัดทิ้ง)


def _out(result, r, bars, exit_px, exit_ts, mfe, mae, digits):
    return {"result": result, "realized_R": round(r, 3), "realized_R_gross": round(r, 3),
            "bars_held": int(bars), "exit_price": round(float(exit_px), digits),
            "mfe_R": round(mfe, 3), "mae_R": round(mae, 3)}
