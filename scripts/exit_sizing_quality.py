#!/usr/bin/env python
"""exit_sizing_quality.py — #1 คุณภาพ exit/sizing ของ signal population จริง (momentum_breakout TREND).

⚠️ OFFLINE, diagnostic. กรอบความซื่อสัตย์: entry = ~0-edge (พิสูจน์แล้ว) → exit tuning **สร้าง EV บวกไม่ได้**
(= data-snooping). ค่าจริงของ #1: (A/B) diagnostic ว่า exit รั่วไหม, (C) exit alt ทดสอบ OOS skeptical
(คาด: variance เปลี่ยน ไม่ใช่ mean), (D) **vol-target sizing = ลด risk/ruin ได้จริงไม่ขึ้นกับ edge**.

live rule ปัจจุบัน: SL=1.5·ATR, TP=2·SL=3·ATR (fixed, ไม่มี trailing/time-stop); sizing=fixed lot.
signal = algo_momentum_breakout เฉพาะ regime TREND (เหมือน route() ที่บอทใช้).
รัน: & $PY scripts\exit_sizing_quality.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROBE = 48          # bars สังเกต excursion (ไม่มี early exit)
COST = 30           # pips — cost กลางสำหรับ diagnostic


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4]


def signals(high, low, close):
    """momentum_breakout เฉพาะ TREND regime (เหมือน route()). คืน list ของ (i, dir, sl_pips, atr)."""
    er = R.efficiency_ratio(close, R.VOL_WIN)
    adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close)
    atr_v = R.atr(high, low, close)
    out = []
    start = max(R.BRK_WIN, R.VOL_LOOKBACK) + 2
    for i in range(start, len(close) - 1):
        regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct)
        if regime == "TREND" and sig:
            out.append((i, sig["dir"], sig["sl_pips"], float(atr_v[i])))
    return out, atr_v


def probe(i, direction, high, low, close):
    """MFE/MAE (pips) + bar-of-max-MFE ใน PROBE bars ถัดไป (ไม่มี early exit)."""
    entry = close[i]; sign = 1.0 if direction == "BUY" else -1.0
    end = min(i + PROBE, len(close) - 1)
    mfe = mae = 0.0; t_mfe = 0
    for j in range(i + 1, end + 1):
        fav = sign * (high[j] - entry) if direction == "BUY" else sign * (entry - low[j])
        adv = (entry - low[j]) if direction == "BUY" else (high[j] - entry)
        if fav > mfe:
            mfe, t_mfe = fav, j - i
        mae = max(mae, adv)
    return mfe / R.POINT, mae / R.POINT, t_mfe


def pct(a, ps):
    a = np.asarray(a, float)
    return {p: (np.percentile(a, p) if len(a) else float("nan")) for p in ps}


def main():
    high, low, close = _load()
    sigs, atr_v = signals(high, low, close)
    n = len(sigs)
    print("=" * 88)
    print(f"EXIT/SIZING QUALITY — momentum_breakout (TREND) | gold H1 | {n} signals | probe {PROBE} bars")
    print("live rule: SL=1.5·ATR TP=3·ATR fixed. entry ~0-edge → exit ปรับ variance ไม่ใช่ EV; sizing = ของจริง")
    print("=" * 88)
    if n < BT.MIN_N:
        print(f"N={n} < {BT.MIN_N} — noise"); return

    # ── build per-trade record: excursion (R-space) + outcome ภายใต้ rule ปัจจุบัน ──
    recs = []
    for (i, d, sl_pips, atr) in sigs:
        mfe_p, mae_p, t_mfe = probe(i, d, high, low, close)
        r_g, bars, _, _, why = BT.simulate_trade(i, d, sl_pips, round(sl_pips * R.RR), PROBE, high, low, close)
        recs.append({"i": i, "dir": d, "sl_pips": sl_pips, "atr": atr, "R_gross": r_g,
                     "mfe_R": mfe_p / sl_pips, "mae_R": mae_p / sl_pips,  # excursion หน่วย R (÷ SL distance)
                     "t_mfe": t_mfe, "R_net": r_g - COST / sl_pips, "why": why})
    mfe = np.array([r["mfe_R"] for r in recs])
    mae = np.array([r["mae_R"] for r in recs])
    winners = [r for r in recs if r["R_net"] > 0]
    losers = [r for r in recs if r["R_net"] <= 0]

    # ── A. excursion distributions (R-space) ──
    print(f"\n── A. Excursion distributions (หน่วย R = ÷ SL distance) ──")
    print(f"  MFE (favorable) pctile:  " + "  ".join(f"p{p}={v:.2f}R" for p, v in pct(mfe, [25, 50, 75, 90]).items()))
    print(f"  MAE (adverse)   pctile:  " + "  ".join(f"p{p}={v:.2f}R" for p, v in pct(mae, [25, 50, 75, 90]).items()))
    if winners:
        wmae = pct([r["mae_R"] for r in winners], [50, 75, 90, 95])
        print(f"  MAE ของ WINNERS:         " + "  ".join(f"p{p}={v:.2f}R" for p, v in wmae.items())
              + "  ← SL ควรอยู่เลย p90 (กันตัด winner ด้วย noise)")
    tmfe = pct([r["t_mfe"] for r in recs], [50, 75, 90])
    print(f"  time-to-MFE (bars):      " + "  ".join(f"p{p}={v:.0f}" for p, v in tmfe.items())
          + "  ← time-stop horizon")

    # ── B. current-rule diagnostic ──
    s = BT.summarize("cur", recs, COST)
    cap = np.clip([min(r["R_net"], r["mfe_R"]) / r["mfe_R"] if r["mfe_R"] > 0 else 0 for r in recs], -1, 1)
    win_sl_hit = sum(1 for r in recs if r["mfe_R"] >= R.RR and r["why"] in ("SL", "SL_TP_ambig"))
    print(f"\n── B. Current rule (SL=1.5ATR/RR2) diagnostic @cost{COST}p ──")
    print(f"  N={s['n']} WR={s['wr']*100:.1f}% expR={s['exp_R']:+.3f} Sharpe={s['sharpe']:+.3f} PSR₀={s['psr0']:.2f}")
    print(f"  MFE-capture เฉลี่ย={np.mean(cap):+.2f} (1.0=จับได้เต็ม, ต่ำ=คืนกำไร/ตัดเร็ว)")
    print(f"  ไม้ที่ MFE ถึง TP (≥{R.RR:.0f}R) แต่จบด้วย SL (path ซวย/SL แคบ): {win_sl_hit} ({win_sl_hit/n*100:.1f}%)")
    print(f"  winners={len(winners)} losers={len(losers)}")

    # ── C. exit alternatives (pre-specified จาก distribution, OOS+null) ──
    split = int(len(recs) * 0.6)
    def rule(sl_mult, rr, tstop):
        out = []
        for (i, d, _, atr) in sigs:
            slp = max(1, round(sl_mult * atr / R.POINT))
            mh = tstop if tstop else PROBE
            r_g, *_ = BT.simulate_trade(i, d, slp, round(slp * rr), mh, high, low, close)
            out.append({"i": i, "R_gross": r_g, "sl_pips": slp})
        return out
    print(f"\n── C. Exit alternatives (OOS 60/40, @cost{COST}p) — คาด: mean ~เท่าเดิม (entry 0-edge) ──")
    print(f"  {'rule':<26}{'N':>5}{'expR':>8}{'OOS':>8}{'PSR0':>7}")
    cands = [("current 1.5ATR/RR2/no-ts", 1.5, 2.0, 0),
             ("wider-SL 2.5ATR/RR2", 2.5, 2.0, 0),
             ("tight-SL 1.0ATR/RR2", 1.0, 2.0, 0),
             ("RR1 1.5ATR (จับเร็ว)", 1.5, 1.0, 0),
             ("RR3 1.5ATR (ปล่อยวิ่ง)", 1.5, 3.0, 0),
             (f"time-stop {int(tmfe[75])}b 1.5ATR/RR2", 1.5, 2.0, int(tmfe[75]))]
    for label, sm, rr, ts in cands:
        t = rule(sm, rr, ts)
        st = BT.summarize("c", t, COST)
        oos = BT.summarize("o", [x for x in t if x["i"] >= sigs[split][0]], COST)
        print(f"  {label:<26}{st['n']:>5}{st['exp_R']:>+8.3f}{oos['exp_R']:>+8.3f}{st['psr0']:>7.2f}")
    # quartile consistency สำหรับ rule ที่ดูดีขึ้น — OOS=ช่วงล่าสุด(Q4 regime ดี) หลอกตา; ต้องบวกหลาย Q
    print(f"  ── quartile consistency (expR@cost{COST}p) — เช็คว่า 'ดีขึ้น' = จริง หรือแค่ Q4 regime ──")
    imax = sigs[-1][0]
    for label, sm, rr, ts in [("current", 1.5, 2.0, 0), ("wider-SL 2.5ATR", 2.5, 2.0, 0), ("RR3 ปล่อยวิ่ง", 1.5, 3.0, 0)]:
        t = rule(sm, rr, ts)
        qs = []
        for q in range(4):
            lo, hi = imax * q // 4, imax * (q + 1) // 4
            seg = [x for x in t if lo <= x["i"] < hi]
            qe = BT.summarize("q", seg, COST)["exp_R"] if len(seg) >= 30 else float("nan")
            qs.append(f"Q{q+1}:{qe:+.3f}")
        print(f"    {label:<18} " + " ".join(qs))

    # ── D. vol-target sizing (defensible risk win, ไม่ขึ้นกับ edge) ──
    slps = np.array([r["sl_pips"] for r in recs], float)          # SL distance (pips) = 1.5·ATR/point
    # fixed lot: $risk ∝ sl_pips (SL กว้าง=เสียเยอะ). vol-target: lot ∝ 1/sl_pips → $risk คงที่
    fixed_risk = slps / np.median(slps)                          # $risk ต่อไม้ (normalize ที่ median=1)
    print(f"\n── D. Vol-target sizing (fixed lot → $risk แปรตาม ATR) ──")
    print(f"  SL distance (pips): p10={np.percentile(slps,10):.0f} median={np.median(slps):.0f} p90={np.percentile(slps,90):.0f} max={slps.max():.0f}")
    print(f"  fixed-lot $risk/ไม้ (median=1.0): p90={np.percentile(fixed_risk,90):.2f}× max={fixed_risk.max():.2f}×")
    print(f"    → ไม้ ATR สูงสุด เสี่ยงเงิน {fixed_risk.max():.1f}× ของ median ไม้เดียว (worst SL-hit = {fixed_risk.max():.1f}R$)")
    # vol-target: R เท่าเดิม (R = ÷ SL) แต่ $ ต่อไม้เท่ากันทุกไม้ → variance ของ $ risk = 0
    R_net = np.array([r["R_net"] for r in recs])
    dollar_fixed = R_net * fixed_risk                           # $-P&L ถ่วงด้วย $risk จริง (fixed lot)
    print(f"  P&L variance (หน่วย R$): fixed-lot std={dollar_fixed.std():.2f} vs vol-target std={R_net.std():.2f}"
          f"  → ลด {(1-R_net.std()/dollar_fixed.std())*100:.0f}%")
    print(f"  max single loss: fixed-lot={dollar_fixed.min():.2f}R$ vs vol-target={R_net.min():.2f}R$")

    print("\n" + "=" * 88)
    print("สรุป: A/B=diagnostic exit รั่วไหม; C=exit alt (คาด mean เท่าเดิม ยืนยัน 0-edge); D=vol-target ลด $-variance จริง")


if __name__ == "__main__":
    main()
