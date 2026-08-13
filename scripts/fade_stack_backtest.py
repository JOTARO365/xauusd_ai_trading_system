#!/usr/bin/env python
"""scripts/fade_stack_backtest.py — 2 fade algo: stack S/R gate + confirm rev-pin + bounded intraday exit → ดัน +?

MFE diag พิสูจน์: fade ราคาไปถูกทิศช่วงแรก แต่ MAE≈MFE (ไม่มี edge) → exit-tuning อย่างเดียวไม่ข้ามศูนย์.
สมมติฐาน: กรอง entry ให้ยิงเฉพาะ "จุดกลับตัวจริง" อาจสร้าง edge:
  ชั้น 1 S/R gate  — ไม่ fade เข้าหากำแพงตรงข้าม (sr_entry_gate.blocks_at)
  ชั้น 2 confirm rev — แท่งสัญญาณต้องเป็น pin/hammer กลับตัวที่ปลาย (confirm_gate mode=rev)
  ชั้น 3 bounded exit — SL/TP fixed จุด, ปิดสิ้นวัน (intraday)

วัด expectancy (จุด/ไม้) ทีละชั้น: baseline → +SR → +confirm → +both. + scan SL×TP ใต้ full stack.
รัน: python scripts/fade_stack_backtest.py   → docs/reviews/fade-stack.md
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                       # noqa: E402
import mfe_rr_diag as M                                      # noqa: E402  (reuse entries + intraday outcome)
from agents import sr_entry_gate as SR                       # noqa: E402
from agents import confirm_gate as CF                        # noqa: E402

SL_GRID = [500, 750, 1000, 1500]
TP_GRID = [1000, 1500, 2000, 2500, 3000]
REPORT = os.path.join(_ROOT, "docs", "reviews", "fade-stack.md")
MIN_N = 40                                                  # fade + filter = ไม้น้อยลงมาก; รายงานถ้า ≥ นี้


def _filtered(entries, h, l, c, atr, use_sr, use_cf):
    """คืน entries ที่ผ่าน filter (causal, ที่ signal bar i). sr_p/cf_p จาก config."""
    sr_p = SR.params_from_config()
    cf_p = (CF.params_from_config()[0], "rev")
    out = []
    for (i, d, px, sld) in entries:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if use_sr and SR.blocks_at(h, l, i, px, d, av, sr_p):
            continue
        if use_cf and CF.blocks_at(h, l, i, px, d, av, cf_p):
            continue
        out.append((i, d, px, sld))
    return out


def _expectancy(entries, h, l, c, day, pt, cost, slp, tpp):
    if not entries:
        return None, 0
    ends = [M._day_end_idx(day, i) for (i, d, px, sld) in entries]
    rs = np.array([M._outcome_pts(h, l, c, i, s, px, pt, slp, tpp, cost, ends[k])
                   for k, (i, s, px, sld) in enumerate(entries)])
    return (round(float(rs.mean()), 1), round(float((rs > 0).mean()) * 100, 1)), len(entries)


def _best_grid(entries, h, l, c, day, pt, cost):
    best = None
    for slp in SL_GRID:
        for tpp in TP_GRID:
            r, n = _expectancy(entries, h, l, c, day, pt, cost, slp, tpp)
            if r and (best is None or r[0] > best[1]):
                best = ((slp, tpp), r[0], r[1], n)
    return best   # ((sl,tp), exp, wr, n)


def analyze(algo, entries, h, l, c, day, pt, cost):
    atr = R.atr(h, l, c)
    stages = {}
    for tag, sr, cf in (("baseline", False, False), ("+SR", True, False),
                        ("+confirm", False, True), ("+both", True, True)):
        fe = _filtered(entries, h, l, c, atr, sr, cf)
        stages[tag] = _best_grid(fe, h, l, c, day, pt, cost)   # best SL/TP ต่อ stage
    return stages


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    bm = _broker_map() or {}
    cost_of = lambda lg: (_sc.cost_pips(lg) if _sc else None) or 30.0    # noqa: E731

    pairs = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY"]        # gold-complex (จุด grid calibrated ทอง)
    res = {"mean_reversion": [], "sweep_reversal": []}
    for lg in pairs:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
        except Exception:
            info = rh = None
        if not info or rh is None or len(rh) < 800:
            continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"]
        day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
        res["mean_reversion"].append((lg, analyze("mean_reversion", M._entries_meanrev(h, l, c), h, l, c, day, pt, cost)))
        res["sweep_reversal"].append((lg, analyze("sweep_reversal", M._entries_sweep(h, l, c, tm), h, l, c, day, pt, cost)))
        print(f"  {lg}: done")
    mt5.shutdown()

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(f"# Fade stack — S/R gate + confirm rev-pin + bounded intraday exit ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write("expectancy (จุด/ไม้, best SL/TP ต่อ stage) ทีละชั้น filter. intraday (ปิดสิ้นวัน UTC). หัก spread.\n")
        f.write(f"เป้า: edge โผล่มั้ย (exp > 0) เมื่อกรอง entry. n<{MIN_N} = ไม้น้อยไป (เชื่อไม่ได้).\n\n")
        for algo, rows in res.items():
            f.write(f"## {algo}\n\n")
            f.write("| คู่ | baseline exp/wr/n | +SR | +confirm | **+both** | best SL/TP (both) |\n")
            f.write("|---|---|---|---|---|---|\n")
            for lg, st in rows:
                def cell(tag):
                    b = st.get(tag)
                    if not b or b[3] < MIN_N:
                        return f"— (n{b[3] if b else 0})"
                    return f"{b[1]:+.0f}/{b[2]}%/{b[3]}"
                both = st.get("+both")
                bslt = f"{both[0][0]}/{both[0][1]}" if (both and both[3] >= MIN_N) else "—"
                f.write(f"| {lg} | {cell('baseline')} | {cell('+SR')} | {cell('+confirm')} | **{cell('+both')}** | {bslt} |\n")
            f.write("\n")
    print(f"\nreport → {REPORT}\n")
    for algo, rows in res.items():
        for lg, st in rows:
            b0 = st.get("baseline"); bb = st.get("+both")
            if b0 and bb:
                print(f"  {algo:16s} {lg:7s} baseline {b0[1]:+.0f}จุด (n{b0[3]}) -> +both {bb[1]:+.0f}จุด "
                      f"win{bb[2]}% (n{bb[3]}) SL/TP {bb[0][0]}/{bb[0][1]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
