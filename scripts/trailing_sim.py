#!/usr/bin/env python
"""trailing_sim.py — bar-stepping simulator รองรับ trailing stop + dynamic/removable TP (strategy ผู้ใช้).

harness เดิม (regime_backtest.simulate_trade) ใช้ SL/TP คงที่ — ทำ 3 อย่างนี้ไม่ได้:
  (1) stop เลื่อนทุกบาร์ (trailing)  (2) TP ลบกลางไม้ได้ (vol-breakout removal)  (3) state ข้ามบาร์.
simulate_dynamic เพิ่ม 3 อย่างนี้. คงกติกา intrabar H/L + pessimistic (SL ก่อน TP บาร์เดียวกัน) ตามเดิม.
research-only — ไม่แตะ live path / _run_gates.
"""
import numpy as np

import regime_lib as R

POINT = R.POINT


def simulate_dynamic(entry_i, direction, high, low, close, atr_v,
                     init_sl_pips, tp_price=None, max_hold=120,
                     trail_mult=3.0, trail_start_R=0.0,
                     removal_fn=None, runner_mult=1.5):
    """คืน (R_net_gross, bars, mfe_pips, mae_pips, exit_reason, tp_removed).
    trailing = peak − trail_mult·ATR(entry) ratchet. tp_price=None → ไม่มี TP (trail อย่างเดียว).
    removal_fn(j, ctx)->bool : เมื่อ True ที่บาร์ j → ลบ TP + tighten trail เป็น runner_mult. (เรียกเมื่อราคาเข้าโซน TP)"""
    sign = 1.0 if direction == "BUY" else -1.0
    entry = close[entry_i]
    atr0 = float(atr_v[entry_i])
    risk = init_sl_pips * POINT
    if risk <= 0 or atr0 <= 0:
        return 0.0, 0, 0.0, 0.0, "BAD", False
    # initial hard stop
    sl = entry - sign * init_sl_pips * POINT
    peak = entry                                            # running favorable extreme
    cur_mult = trail_mult
    tp_removed = False
    activated = (trail_start_R <= 0)
    mfe = mae = 0.0
    end = min(entry_i + max_hold, len(close) - 1)
    for j in range(entry_i + 1, end + 1):
        hi, lo = high[j], low[j]
        fav = sign * (hi - entry) if direction == "BUY" else sign * (entry - lo)
        adv = (entry - lo) if direction == "BUY" else (hi - entry)
        mfe = max(mfe, fav); mae = max(mae, adv)
        # อัปเดต peak + activation
        peak = max(peak, hi) if direction == "BUY" else min(peak, lo)
        if not activated and fav >= trail_start_R * risk:
            activated = True
        # trailing (ratchet, only-tighten)
        if activated:
            trail = (peak - cur_mult * atr0) if direction == "BUY" else (peak + cur_mult * atr0)
            sl = max(sl, trail) if direction == "BUY" else min(sl, trail)
        # TP-removal (เมื่อราคาเข้าโซน TP + removal_fn ยืนยัน) — ครั้งเดียว/ไม้
        if (tp_price is not None) and (not tp_removed) and removal_fn is not None:
            near = (hi >= tp_price - 0.25 * atr0) if direction == "BUY" else (lo <= tp_price + 0.25 * atr0)
            if near and removal_fn(j, {"entry": entry, "atr0": atr0, "res": tp_price, "dir": direction}):
                tp_price = None; tp_removed = True
                cur_mult = min(cur_mult, runner_mult)       # tighten trail กัน give-back
        # exit — pessimistic: SL ก่อน TP บาร์เดียวกัน
        hit_sl = lo <= sl if direction == "BUY" else hi >= sl
        hit_tp = (tp_price is not None) and (hi >= tp_price if direction == "BUY" else lo <= tp_price)
        if hit_sl and hit_tp:
            return (sl - entry) * sign / risk, j - entry_i, mfe / POINT, mae / POINT, "SL_TP_ambig", tp_removed
        if hit_sl:
            return (sl - entry) * sign / risk, j - entry_i, mfe / POINT, mae / POINT, "TRAIL/SL", tp_removed
        if hit_tp:
            return (tp_price - entry) * sign / risk, j - entry_i, mfe / POINT, mae / POINT, "TP", tp_removed
    # time-stop
    return sign * (close[end] - entry) / risk, end - entry_i, mfe / POINT, mae / POINT, "TIME", tp_removed


def swing_high(i, high, k, lookback=100):
    """fractal pivot high ล่าสุดที่ confirmed ณ บาร์ i (ยืนยันช้า k บาร์ = no-lookahead). คืน (level, idx) หรือ None."""
    for p in range(i - k, max(i - k - lookback, k) - 1, -1):
        if p - k < 0 or p + k >= len(high):
            continue
        seg = high[p - k:p + k + 1]
        if high[p] == seg.max() and high[p] > high[p - 1] and high[p] > high[p + 1]:
            return float(high[p]), p
    return None


def swing_low(i, low, k, lookback=100):
    for p in range(i - k, max(i - k - lookback, k) - 1, -1):
        if p - k < 0 or p + k >= len(low):
            continue
        seg = low[p - k:p + k + 1]
        if low[p] == seg.min() and low[p] < low[p - 1] and low[p] < low[p + 1]:
            return float(low[p]), p
    return None
