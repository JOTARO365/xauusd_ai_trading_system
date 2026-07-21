#!/usr/bin/env python
"""trailing_reentry_test.py — ทดสอบกลยุทธ์ผู้ใช้ (trailing + swing-TP + vol-breakout removal + re-entry).

synthesize 3 personas. การทดสอบชี้ขาด = **4-way ablation**: fixed SL/TP → +trailing → +removal(full).
+ breakout base-rate: P(ทะลุ | แตะแนวต้าน) ชนะ 0.5 ไหม (พิสูจน์ว่า vol ทำนาย breakout ได้จริงหรือ coin-flip).
entry = momentum breakout (known beta) เพื่อ isolate ว่า management เพิ่ม edge ไหม. net cost, gauntlet metrics.
รัน: & $PY scripts\trailing_reentry_test.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT
from trailing_sim import simulate_dynamic, swing_high, swing_low

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

POINT = R.POINT
TRAIL_MULT = 3.0        # chandelier
K = 3                   # fractal pivot order
RR_MIN = 0.8
H = 8                   # first-passage horizon (บาร์)
N_VOL = 30
Z_STAR = 0.412          # p*=0.68 → remove TP ถ้า z < z*
COST = 30               # pips net


def _load(tf="h1"):
    d = np.array(json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json"))), dtype=float)
    return d[:, 1], d[:, 2], d[:, 3], d[:, 4]     # o,h,l,c


def _make_removal(close, sigma, adx, er):
    """removal_fn: first-passage z<z* + momentum_confirm. คืน closure สำหรับ simulate_dynamic."""
    def fn(j, ctx):
        res = ctx["res"]; P = close[j]
        if P <= 0 or sigma[j] <= 0:
            return False
        d = np.log(res / P) if ctx["dir"] == "BUY" else np.log(P / res)   # ระยะถึง level (log, >0 = ยังไม่ถึง)
        z = (d / (sigma[j] * np.sqrt(H))) if d > 0 else -1.0
        return z < Z_STAR and adx[j] >= 25 and er[j] >= 0.4               # ใกล้พอ + ยังมีทิศ (momentum_confirm)
    return fn


def gen_entries(high, low, close, er, adx, Lb=20, COOL=6):
    """momentum breakout (Donchian + trend gate), long+short, cooldown. = known-beta entry."""
    n = len(close); start = max(Lb, R.VOL_LOOKBACK) + 2; out = []; last = -10 ** 9
    for i in range(start, n - 1):
        if i - last < COOL or np.isnan(er[i]) or np.isnan(adx[i]):
            continue
        hh = high[i - Lb:i].max(); ll = low[i - Lb:i].min()
        if close[i] > hh and er[i] >= 0.35 and adx[i] >= 25:
            out.append((i, "BUY")); last = i
        elif close[i] < ll and er[i] >= 0.35 and adx[i] >= 25:
            out.append((i, "SELL")); last = i
    return out


def run_mode(entries, mode, high, low, close, atr, sigma, adx, er):
    """mode: fixed / trail / full. คืน list trades {i,dir,sl_pips,R_gross,tp_removed}."""
    removal = _make_removal(close, sigma, adx, er) if mode == "full" else None
    tmult = 999.0 if mode == "fixed" else TRAIL_MULT      # 999 = ไม่ trail (fixed SL)
    out = []
    for (i, d) in entries:
        a = float(atr[i])
        if a <= 0:
            continue
        init_sl = max(1, round(TRAIL_MULT * a / POINT))   # init stop = 3·ATR (เท่ากันทุก mode)
        sign = 1.0 if d == "BUY" else -1.0
        synth = close[i] + sign * 2.0 * init_sl * POINT       # fallback RR2 เมื่อไม่มีแนวต้าน (ราคาทำ new high)
        if d == "BUY":
            sh = swing_high(i, high, K)
            tp = (sh[0] - 0.1 * a) if (sh and sh[0] > close[i] + 0.5 * a) else synth
        else:
            sl_ = swing_low(i, low, K)
            tp = (sl_[0] + 0.1 * a) if (sl_ and sl_[0] < close[i] - 0.5 * a) else synth
        rr = abs(tp - close[i]) / (init_sl * POINT)
        if rr < RR_MIN:
            continue
        r, bars, mfe, mae, why, rem = simulate_dynamic(
            i, d, high, low, close, atr, init_sl, tp_price=tp, max_hold=120,
            trail_mult=tmult, removal_fn=removal, runner_mult=1.5)
        out.append({"i": i, "dir": d, "sl_pips": init_sl, "R_gross": r, "tp_removed": rem, "rr": rr})
    return out


def breakout_baserate(high, low, close, atr, er, adx):
    """P(ทะลุ | แตะ swing-high) — triple-barrier. + แยกตาม vol/momentum (vol ทำนาย breakout ได้ไหม)."""
    n = len(close); base = []; hi_er = []; lo_er = []
    for i in range(60, n - H - 1):
        sh = swing_high(i, high, K)
        if not sh:
            continue
        lvl, _p = sh
        if not (high[i] >= lvl and high[i - 1] < lvl and close[i - 1] < lvl):   # touch จากล่าง
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        up, dn = lvl + 0.75 * a, lvl - 0.75 * a; lab = 0
        for j in range(i + 1, min(i + 1 + H, n)):
            if high[j] >= up:
                lab = 1; break
            if low[j] <= dn:
                lab = 0; break
        base.append(lab)
        (hi_er if er[i] >= 0.4 and adx[i] >= 25 else lo_er).append(lab)
    return base, hi_er, lo_er


def main():
    o, high, low, close = _load("h1")
    er = R.efficiency_ratio(close, R.VOL_WIN); adx = R.adx(high, low, close); atr = R.atr(high, low, close)
    lr = np.zeros(len(close)); lr[1:] = np.diff(np.log(close))
    sigma = np.array([lr[max(0, j - N_VOL):j].std() if j >= N_VOL else 0.0 for j in range(len(close))])
    entries = gen_entries(high, low, close, er, adx)

    print("=" * 92)
    print(f"TRAILING + SWING-TP + VOL-REMOVAL — 4-way ablation | gold H1 | entries={len(entries)} (momentum breakout)")
    print("=" * 92)
    print(f"{'mode':<26}{'N':>6}{'WR':>7}{'expR':>9}{'Sharpe':>8}{'PSR':>6}{'sumR':>8}{'TPrem':>7}")
    print("-" * 92)
    res = {}
    for mode in ("fixed", "trail", "full"):
        tr = run_mode(entries, mode, high, low, close, atr, sigma, adx, er)
        res[mode] = tr
        if len(tr) < BT.MIN_N:
            print(f"{mode:<26}{len(tr):>6}  N<{BT.MIN_N}"); continue
        s = BT.summarize(mode, tr, COST)
        nrem = sum(1 for t in tr if t["tp_removed"])
        print(f"{mode:<26}{s['n']:>6}{s['wr']*100:>6.1f}%{s['exp_R']:>+9.3f}{s['sharpe']:>+8.3f}"
              f"{s['psr0']:>6.2f}{s['sum_R']:>+8.1f}{nrem:>7}")
    print("-" * 92)
    # ablation gap = decision metric
    if all(len(res[m]) >= BT.MIN_N for m in ("fixed", "trail", "full")):
        sf, st, sfu = (BT.summarize(m, res[m], COST) for m in ("fixed", "trail", "full"))
        print(f"Δ trailing (trail−fixed): expR {st['exp_R']-sf['exp_R']:+.3f} · Sharpe {st['sharpe']-sf['sharpe']:+.3f}")
        print(f"Δ removal  (full−trail):  expR {sfu['exp_R']-st['exp_R']:+.3f} · Sharpe {sfu['sharpe']-st['sharpe']:+.3f}")

    # breakout base-rate
    base, hi, lo = breakout_baserate(high, low, close, atr, er, adx)
    print(f"\n── Breakout base-rate: P(ทะลุ | แตะแนวต้าน) — vol/momentum ทำนายได้ไหม ──")
    if base:
        print(f"  ทั้งหมด: {np.mean(base)*100:.1f}% (N={len(base)}) — ชนะ coin-flip 50% ไหม?")
        if hi:
            print(f"  high-ER+ADX (น่าทะลุ): {np.mean(hi)*100:.1f}% (N={len(hi)})")
        if lo:
            print(f"  low  (น่า reject):     {np.mean(lo)*100:.1f}% (N={len(lo)})")
        edge = (np.mean(hi) - np.mean(lo)) * 100 if hi and lo else 0
        print(f"  → lift (hi−lo) = {edge:+.1f}pp ({'มี signal' if abs(edge) > 5 else 'coin-flip/ไม่มี'})")
    print("\n" + "=" * 92)
    print("ตัดสิน: Δtrailing/Δremoval > 0 (Sharpe) + PSR>0.95 = management เพิ่ม edge จริง; base-rate>55%+lift = vol ทำนายได้")


if __name__ == "__main__":
    main()
