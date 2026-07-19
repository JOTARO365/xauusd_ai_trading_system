#!/usr/bin/env python
"""
regime_range_research.py — วิจัย+ทดสอบกลยุทธ์ RANGE (sideways) ผ่าน gauntlet (backtest→OOS→null).

plain z-score mean-reversion ตายไปแล้ว (−EV OOS+null). ทดสอบ candidate ที่ **เครื่องมือต่าง**:
  C1 RSI(2) extreme mean-reversion (Connors)   — RSI(2)<10 BUY / >90 SELL
  C2 Bollinger band fade → กลับ mid            — close<lower BUY / >upper SELL, TP=mid, SL เลย band
  C3 Squeeze breakout (BB width หด → ระเบิด)   — vol contraction แล้วทะลุ 10-bar high/low

ทั้งหมดยิงเฉพาะ RANGE bars (detect_regime==RANGE). ผ่าน = expR>0 ทุก cost + OOS test>0 + เหนือ null.
รัน:  python scripts\\regime_range_research.py [tf]   (default h1)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

COST = 30
SPLIT = 0.60
MR_HOLD = 24            # time-stop mean-reversion (bars)
BRK_HOLD = 200


# ── tools (เครื่องมือ) ──
def rsi(close, n):
    d = np.diff(close, prepend=close[0])
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    out = np.full(len(close), np.nan)
    au = np.mean(up[1:n + 1]); ad = np.mean(dn[1:n + 1])
    for i in range(n, len(close)):
        au = (au * (n - 1) + up[i]) / n
        ad = (ad * (n - 1) + dn[i]) / n
        out[i] = 100 - 100 / (1 + au / ad) if ad > 0 else 100.0
    return out


def bollinger(close, n=20, k=2.0):
    mid = np.full(len(close), np.nan); up = mid.copy(); lo = mid.copy(); width = mid.copy()
    for i in range(n, len(close)):
        w = close[i - n + 1:i + 1]; m = w.mean(); s = w.std()
        mid[i] = m; up[i] = m + k * s; lo[i] = m - k * s; width[i] = 2 * k * s
    return mid, up, lo, width


# ── candidates: คืน (dir, sl_pips, tp_pips, max_hold) หรือ None ──
def c1_rsi2(i, high, low, close, atr_v, T):
    r = T["rsi2"][i]
    if np.isnan(r) or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    d = "BUY" if r < 10 else ("SELL" if r > 90 else None)
    if not d:
        return None
    sl = round(1.5 * atr_v[i] / R.POINT)
    return d, sl, sl, MR_HOLD          # RR1 (mean-rev = WR สูง RR ต่ำ)


def c2_bbfade(i, high, low, close, atr_v, T):
    mid, up, lo = T["bb_mid"][i], T["bb_up"][i], T["bb_lo"][i]
    if np.isnan(mid) or atr_v[i] == 0:
        return None
    d = "BUY" if close[i] < lo else ("SELL" if close[i] > up else None)
    if not d:
        return None
    atr_floor = round(1.5 * atr_v[i] / R.POINT)
    tp = max(round(abs(close[i] - mid) / R.POINT), atr_floor)   # TP = กลับ mid
    sl = max(round(abs(close[i] - (lo if d == "BUY" else up)) / R.POINT) + atr_floor // 2, atr_floor)
    return d, sl, tp, MR_HOLD


def c3_squeeze(i, high, low, close, atr_v, T):
    if i < 30 or np.isnan(T["bb_w"][i]) or atr_v[i] == 0:
        return None
    wlb = T["bb_w"][i - 30:i]; wlb = wlb[~np.isnan(wlb)]
    if len(wlb) < 10 or T["bb_w"][i] > np.percentile(wlb, 20):   # ต้องอยู่ในภาวะ squeeze
        return None
    hh = high[i - 10:i].max(); ll = low[i - 10:i].min()
    d = "BUY" if close[i] > hh else ("SELL" if close[i] < ll else None)
    if not d:
        return None
    sl = round(1.5 * atr_v[i] / R.POINT)
    return d, sl, round(sl * 2.0), BRK_HOLD


CANDS = {"C1_rsi2": c1_rsi2, "C2_bbfade": c2_bbfade, "C3_squeeze": c3_squeeze}


def run_cand(fn, high, low, close, atr_v, er, adx_v, volpct, T):
    trades = []
    start = max(R.VOL_LOOKBACK, 40) + 2
    for i in range(start, len(close) - 1):
        if R.detect_regime(er[i], adx_v[i], volpct[i]) != "RANGE":     # เฉพาะ sideways
            continue
        sig = fn(i, high, low, close, atr_v, T)
        if not sig:
            continue
        d, sl, tp, hold = sig
        rg, bars, mfe, mae, why = BT.simulate_trade(i, d, sl, tp, hold, high, low, close)
        trades.append({"i": i, "sl_pips": sl, "R_gross": rg, "why": why})
    return trades


def block_null(fn, high, low, close, T_builder, real, B=200, blk=20):
    """null: block-bootstrap bars → รัน candidate เดิม → p-value."""
    logret = np.concatenate([[0.0], np.diff(np.log(close))])
    hr = high / close; lor = low / close
    rng = np.random.default_rng(777)
    n = len(close); null = []
    for _ in range(B):
        idx = []
        while len(idx) < n:
            s = rng.integers(0, n); idx.extend((s + k) % n for k in range(blk))
        idx = np.array(idx[:n]); lr = logret[idx]
        c = np.empty(n); c[0] = 100.0; c[1:] = 100.0 * np.exp(np.cumsum(lr[1:]))
        h = c * hr[idx]; l = c * lor[idx]
        er2 = R.efficiency_ratio(c); adx2 = R.adx(h, l, c); vp2 = R.vol_percentile(c); atr2 = R.atr(h, l, c)
        tr = run_cand(fn, h, l, c, atr2, er2, adx2, vp2, T_builder(c, h, l))
        if len(tr) >= 30:
            null.append(float(BT.net_R(tr, COST).mean()))
    null = np.array(null)
    return (null >= real).mean() if len(null) else 1.0, null.mean() if len(null) else 0.0


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    high = np.array([r[2] for r in rows], float); low = np.array([r[3] for r in rows], float)
    close = np.array([r[4] for r in rows], float)
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)

    def build_T(c, h, l):
        mid, up, lo, w = bollinger(c)
        return {"rsi2": rsi(c, 2), "bb_mid": mid, "bb_up": up, "bb_lo": lo, "bb_w": w}
    T = build_T(close, high, low)
    split = int(len(close) * SPLIT)

    print("=" * 78)
    print(f"RANGE STRATEGY RESEARCH — gold {tf.upper()} {len(close)} bars | เฉพาะ RANGE regime | gauntlet")
    print("=" * 78)
    for name, fn in CANDS.items():
        trades = run_cand(fn, high, low, close, atr_v, er, adx_v, volpct, T)
        n = len(trades)
        print(f"\n── {name} ── ({n} trades ใน RANGE)")
        if n < BT.MIN_N:
            print(f"  ⚠ N<{BT.MIN_N} — noise, ข้าม"); continue
        for c in (20, 30, 40):
            r = BT.net_R(trades, c)
            print(f"  cost={c}p: expR={r.mean():+.3f} WR={(r>0).mean()*100:4.1f}% sumR={r.sum():+.0f}")
        tr_tr = [t for t in trades if t["i"] < split - 200]; te = [t for t in trades if t["i"] >= split]
        etr = BT.net_R(tr_tr, COST).mean() if len(tr_tr) >= 30 else float("nan")
        ete = BT.net_R(te, COST).mean() if len(te) >= 30 else float("nan")
        print(f"  OOS: train expR={etr:+.3f}(N={len(tr_tr)}) | test expR={ete:+.3f}(N={len(te)})")
        real = float(BT.net_R(trades, COST).mean())
        if real > 0 and ete > 0:
            p, nm = block_null(fn, high, low, close, build_T, real)
            print(f"  NULL: real={real:+.3f} vs null mean={nm:+.3f} → p={p:.3f} "
                  f"{'✅ ผ่าน (edge จริง)' if p < 0.05 else '❌ artifact'}")
        else:
            print(f"  → −EV (full หรือ OOS) → ไม่ผ่าน (ไม่ต้อง null)")
    print("\n" + "=" * 78)
    print("ผ่านครบ (expR>0 ทุก cost + test>0 + null p<0.05) → เสียบ STRATEGIES['RANGE']. ไม่ผ่าน → stand-down ถูกแล้ว.")


if __name__ == "__main__":
    main()
