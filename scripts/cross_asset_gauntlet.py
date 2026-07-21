#!/usr/bin/env python
"""cross_asset_gauntlet.py — angle ใหม่: cross-asset LEAD → gold มี tradeable edge ไหม?

⚠️ OFFLINE. price-action ทิศทางพิสูจน์แล้วว่าไม่มี edge (fade/momentum ทุกแบบ). angle ที่ยังไม่แตะ:
driver (EURUSD/USDJPY/silver/DXY) **นำ** gold ไหม?

หัวใจ: ถ้า gold-driver correlate แค่ **lag 0** (react ข่าวเดียวกันพร้อมกัน) = เทรดไม่ได้.
จะเทรดได้ต้องมี **lag+k corr** (driver ขยับ *ก่อน* gold). ⇒ Stage 1 (corr scan) ถูกและชี้ขาด:
lag+1 ≈ 0 → จบ (no lead). มี lag+1 → Stage 2 (momentum-spillover trade gauntlet).

align: gold H1 กับ driver H1 ต่าง row-count/ช่วงเวลา → inner-join ด้วย timestamp.
sign correlation: EURUSD/XAG +(ขึ้น→BUY gold), USDJPY/DXY −(ขึ้น→SELL gold).
รัน: & $PY scripts\cross_asset_gauntlet.py
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

RR = 2.0
SL_ATR = 1.5
MAX_HOLD = 24
LAGS = range(-3, 4)                 # -3..+3 (บวก = driver นำ gold)
L_SWEEP = (1, 3, 6)                 # momentum lookback (common-ts bars) — sweep เล็ก (multiple-testing = 4 driver × 3 L)
# +corr → ขึ้น = BUY gold; −corr → ขึ้น = SELL gold
DRIVERS = {"eurusd": +1, "usdjpy": -1, "xag": +1, "dxy": -1}


def _load(name):
    d = np.array(json.load(open(os.path.join(_BASE, "data", f"{name}.json"))), dtype=float)
    return d


def align(gold, drv):
    """inner-join ด้วย timestamp. คืน gi[] (index ใน gold), gc[] (gold close), dc[] (driver close) เรียงเวลา."""
    gmap = {int(gold[i, 0]): i for i in range(len(gold))}
    gi, gc, dc = [], [], []
    for k in range(len(drv)):
        ts = int(drv[k, 0])
        j = gmap.get(ts)
        if j is not None:
            gi.append(j); gc.append(gold[j, 4]); dc.append(drv[k, 4])
    return np.array(gi), np.array(gc), np.array(dc)


def leadlag(gret, dret):
    """corr(gold_ret[t], driver_ret[t-lag]) — lag>0 = driver นำ. คืน dict lag→corr."""
    out = {}
    for lag in LAGS:
        if lag >= 0:
            a, b = gret[lag:], dret[:len(dret) - lag] if lag > 0 else dret
        else:
            a, b = gret[:len(gret) + lag], dret[-lag:]
        m = min(len(a), len(b))
        if m < 100:
            out[lag] = float("nan"); continue
        a, b = a[:m], b[:m]
        out[lag] = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else float("nan")
    return out


def gen(gold, gi, dc, sign, L, atr_g, random_time=False, seed=0):
    """momentum-spillover: driver L-bar return (อดีต) → เข้า gold ทิศ sign. เข้า gold ที่ index อดีตที่ knowable.
    entry_i = gi[k] (gold close ปัจจุบัน, รู้แล้ว), outcome จาก gi[k]+1 (อนาคต) = ไม่ look-ahead."""
    rng = np.random.RandomState(seed)
    high, low, close = gold[:, 2], gold[:, 3], gold[:, 4]
    n = len(close); lo_i = gi.min() + 5; hi_i = n - 1
    dret = np.zeros(len(dc))
    dret[L:] = np.log(dc[L:] / dc[:-L])
    thr = np.median(np.abs(dret[dret != 0])) if np.any(dret != 0) else 0.0
    out = []
    for k in range(L + 1, len(gi)):
        mom = dret[k]
        if mom == 0 or abs(mom) <= thr:          # filter: momentum แรงกว่า median เท่านั้น
            continue
        direction = "BUY" if (np.sign(mom) * sign) > 0 else "SELL"
        ei = gi[k]
        if random_time:
            ei = rng.randint(lo_i, hi_i)
        if ei >= hi_i or ei < lo_i:
            continue
        sl_pips = max(1, int(round(SL_ATR * atr_g[ei] / R.POINT)))
        r_g, bars, mfe, mae, why = BT.simulate_trade(ei, direction, sl_pips, int(round(sl_pips * RR)),
                                                     MAX_HOLD, high, low, close)
        out.append({"i": ei, "k": k, "dir": direction, "sl_pips": sl_pips, "R_gross": r_g, "why": why})
    return out


def scan_tf(tf):
    gold = _load(f"xau_{tf}")
    atr_g = R.atr(gold[:, 2], gold[:, 3], gold[:, 4])
    print("=" * 86)
    print(f"CROSS-ASSET LEAD → GOLD | gold {tf.upper()} {len(gold)} bars | intrabar+cost RR={RR}")
    print("driver นำ gold ไหม? lag>0 corr = tradeable lead; แค่ lag0 = react พร้อมกัน (เทรดไม่ได้)")
    print("=" * 86)

    for name, sign in DRIVERS.items():
        drv = _load(f"drv_{name}_{tf}")
        gi, gc, dc = align(gold, drv)
        if len(gi) < 500:
            print(f"\n── {name.upper()} ── overlap N={len(gi)} < 500 — data น้อยไป, ข้าม"); continue
        gret = np.diff(np.log(gc)); dret_full = np.diff(np.log(dc))
        m = min(len(gret), len(dret_full)); gret, dret_full = gret[:m], dret_full[:m]
        ll = leadlag(gret, dret_full)
        c0 = ll.get(0, float("nan"))
        print(f"\n── {name.upper()} (sign {sign:+d}) ── overlap {len(gi)} bars | contemporaneous corr(lag0)={c0:+.3f}")
        print("  lead-lag corr:  " + "  ".join(
            f"lag{lag:+d}={ll[lag]:+.3f}" + ("*" if abs(ll[lag]) >= 0.05 and lag > 0 else "")
            for lag in LAGS))
        lead = max((abs(ll[l]) for l in (1, 2, 3) if ll[l] == ll[l]), default=0.0)
        if lead < 0.05:
            print(f"  → lag+ corr สูงสุด={lead:.3f} < 0.05 = ไม่มี tradeable lead (correlate แค่พร้อมกัน). ข้าม Stage 2")
            continue
        print(f"  → lag+ corr={lead:.3f} ≥ 0.05 = อาจมี lead → Stage 2 trade gauntlet:")
        for L in L_SWEEP:
            real = gen(gold, gi, dc, sign, L, atr_g)
            if len(real) < BT.MIN_N:
                print(f"    L={L}: N={len(real)} < {BT.MIN_N} — noise"); continue
            null = gen(gold, gi, dc, sign, L, atr_g, random_time=True, seed=1)
            print(f"    ┌ L={L} ({len(real)} signals)")
            for c in BT.COST_PIPS_GRID:
                BT.print_row(BT.summarize(f"{name}L{L}", real, c))
            ns = BT.summarize("null", null, 30)
            nn = len(real)
            qparts = []
            for q in range(4):
                seg = real[nn * q // 4: nn * (q + 1) // 4]
                qe = BT.summarize("q", seg, 30)["exp_R"] if len(seg) >= 30 else float("nan")
                qparts.append(f"Q{q+1}:{qe:+.3f}")
            print(f"    └ null(timing สุ่ม)@30p: expR={ns['exp_R']:+.3f} WR={ns['wr']*100:.1f}% | "
                  f"quartile@30p: " + " ".join(qparts))
    print("\n" + "=" * 86)
    print("ผ่าน = lag+ corr ชัด + Stage2 expR>0 ทุก cost + PSR>0.95 + ชนะ null + บวกหลาย quartile. ไม่งั้น = no edge")


def main():
    for tf in ("h1", "m15"):
        try:
            scan_tf(tf)
        except FileNotFoundError as e:
            print(f"\n[{tf}] ข้าม — ไม่มีไฟล์ ({e.filename})")
        print()


if __name__ == "__main__":
    main()
