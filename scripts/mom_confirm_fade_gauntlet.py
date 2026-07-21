#!/usr/bin/env python
"""mom_confirm_fade_gauntlet.py — ทดสอบ: fade ที่แนวใหญ่ (D1) + รอ momentum ยืนยัน ดีกว่า blind fade ไหม?

⚠️ OFFLINE. idea (owner): blind fade แพ้เพราะ fill ทุกครั้งที่แตะ (รวมตอนทะลุ 61%). ถ้าเข้าแนว D1 แล้ว
**รอ momentum เปลี่ยน (เด้งยืนยัน)** ก่อน → ตัดไม้ทะลุออก อาจ +EV.

confirm (support→BUY): แตะโซน → รอบาร์ปิดเหนือ high บาร์ก่อน (momentum turn ขึ้น) ภายใน CONFIRM_K โดยไม่ปิดหลุดโซน.
เทียบ: blind (เข้าตอนแตะ) vs confirmed (รอ momentum) vs null (random). gauntlet EV/PSR/OOS.
รัน: & $PY scripts\mom_confirm_fade_gauntlet.py
"""
import json
import os
import sys

import numpy as np
from scipy.stats import gaussian_kde
from scipy.signal import argrelextrema

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MULT = 24              # H1 → D1
LOOKBACK_TF = 200
BAND_ATR = 0.25
SL_ATR = 1.0
MAX_HOLD = 48
COOLDOWN = 48
CONFIRM_K = 6          # รอ momentum ยืนยันภายใน 6 H1 บาร์หลังแตะ
RR = 2.0


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4], d[:, 5]


def _agg(h, l, c, v, m):
    n = (len(c) // m) * m
    return (h[:n].reshape(-1, m).max(1), l[:n].reshape(-1, m).min(1),
            c[:n].reshape(-1, m)[:, -1], v[:n].reshape(-1, m).sum(1))


def _zones(hw, lw, cw, vw, atr):
    if cw.std() == 0 or atr <= 0:
        return []
    band = BAND_ATR * atr
    kde = gaussian_kde(cw, weights=vw); kde.set_bandwidth(band / cw.std())
    g = np.linspace(cw.min(), cw.max(), 300); dens = kde(g)
    idx = argrelextrema(dens, np.greater, order=5)[0]
    return [g[i] for i in idx if dens[i] >= 0.20 * dens.max()]


def gen(high, low, close, vol, mode, rng=None):
    """mode: 'blind' (เข้าตอนแตะ) / 'confirm' (รอ momentum) / 'null' (confirm + timing สุ่ม). คืน trades."""
    TH, TL, TC, TV = _agg(high, low, close, vol, MULT)
    tfatr = R.atr(TH, TL, TC)
    trades = []; last = {}
    for j in range(LOOKBACK_TF, len(TC) - 1):
        atr = float(tfatr[j])
        if not np.isfinite(atr) or atr <= 0:
            continue
        band = BAND_ATR * atr
        zs = _zones(TH[j - LOOKBACK_TF:j], TL[j - LOOKBACK_TF:j], TC[j - LOOKBACK_TF:j], TV[j - LOOKBACK_TF:j], atr)
        a, b = j * MULT, min((j + 1) * MULT, len(close) - 1)
        for i in range(a, b):
            for z in zs:
                if abs(close[i] - z) > band or abs(close[i - 1] - z) <= band:
                    continue
                key = round(z, 1)
                if i - last.get(key, -10 ** 9) < COOLDOWN:
                    continue
                direction = "BUY" if close[i - 1] > z else "SELL"
                sl_pips = max(1, round(SL_ATR * atr / R.POINT))
                entry_i = i
                if mode in ("confirm", "null"):
                    # รอ momentum ยืนยัน: bar ปิดเหนือ high ก่อน (BUY) / ต่ำกว่า low ก่อน (SELL), ไม่หลุดโซน
                    conf = None
                    for k in range(i + 1, min(i + 1 + CONFIRM_K, len(close))):
                        if direction == "BUY":
                            if close[k] < z - band:            # หลุดโซน → ยกเลิก (ทะลุ = ไม่ fade)
                                break
                            if close[k] > high[k - 1]:         # momentum turn ขึ้น
                                conf = k; break
                        else:
                            if close[k] > z + band:
                                break
                            if close[k] < low[k - 1]:
                                conf = k; break
                    if conf is None:
                        continue
                    entry_i = conf
                    if mode == "null" and rng is not None:
                        entry_i = int(rng.randint(LOOKBACK_TF * MULT, len(close) - 1))   # timing สุ่ม
                last[key] = i
                r_g, bars, mfe, mae, why = BT.simulate_trade(entry_i, direction, sl_pips, round(sl_pips * RR),
                                                             MAX_HOLD, high, low, close)
                trades.append({"i": entry_i, "dir": direction, "sl_pips": sl_pips, "R_gross": r_g, "why": why})
    return trades


def main():
    high, low, close, vol = _load()
    n = len(close); split = int(n * 0.6)
    print("=" * 82)
    print(f"MOMENTUM-CONFIRM FADE @ D1 zones — รอ momentum ยืนยัน ดีกว่า blind ไหม? | {n} H1 bars RR={RR}")
    print("=" * 82)
    rng = np.random.RandomState(1)
    print(f"{'mode':>10} | {'N':>5} {'WR':>6} {'expR@30p':>9} {'PSR0':>6} | {'OOS-out':>9}")
    print("-" * 66)
    res = {}
    for mode in ("blind", "confirm"):
        t = gen(high, low, close, vol, mode)
        res[mode] = t
        if len(t) < 30:
            print(f"{mode:>10} | N={len(t)} < 30"); continue
        s = BT.summarize(mode, t, 30)
        out = [x for x in t if x["i"] >= split]
        so = BT.summarize("o", out, 30) if len(out) >= 30 else {"exp_R": float("nan")}
        f = "✅" if s["exp_R"] > 0 and so["exp_R"] > 0 else ""
        print(f"{mode:>10} | {s['n']:>5} {s['wr']*100:5.1f}% {s['exp_R']:>+9.3f} {s['psr0']:>6.2f} | {so['exp_R']:>+8.3f} {f}")
    nt = gen(high, low, close, vol, "null", rng)
    if len(nt) >= 30:
        ns = BT.summarize("null", nt, 30)
        print(f"{'null':>10} | {ns['n']:>5} {ns['wr']*100:5.1f}% {ns['exp_R']:>+9.3f} {ns['psr0']:>6.2f} |")
    print("\n" + "=" * 82)
    print("confirm expR > blind + > 0 + ชนะ null + OOS ยืน = momentum-confirm ช่วยจริง → เจอ TREND-fade edge!")
    print("ถ้า confirm ยัง ~0/−EV = แม้รอ momentum ก็ไม่พอ (แนว D1 efficient เกิน)")


if __name__ == "__main__":
    main()
