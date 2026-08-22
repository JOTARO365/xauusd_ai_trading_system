#!/usr/bin/env python
"""scripts/fv_zone_macd_backtest.py — Fair-value zone reversion + MACD-ATR exhaustion (user idea 08-22).

ไอเดีย (user): range mean-reversion. mid = กึ่งกลางระหว่าง demand(support) กับ supply(resistance).
  - ราคา < mid + อยู่ในโซน demand + MACD signal "oversold" (scaled ATR) → BUY
  - ราคา > mid + อยู่ในโซน supply + MACD signal "overbought" (scaled ATR) → SELL
mid แค่เลือกฝั่งล่า (ล่าง=buy demand / บน=sell supply). MACD/ATR = timing exhaustion กัน catch-knife.

⚠️ zone_reaction เคยตาย (recency/strength ไม่เพิ่ม edge). ตัวนี้ต่างตรง +mid-bias +MACD-ATR-exhaustion.
คำถามหลัก: filter 2 ตัวนี้ยก exp_R เหนือ baseline (no-MACD) แบบมีนัยไหม — ถ้าไม่ = ของเดิมทาสีใหม่.

quant: causal (MACD/percentile/zone ใช้แค่ bar<i) · SL-first · non-overlap · cost/sl_pips · OOS70/30 ·
MIN_N=100 · t>2 · full-history (กัน window-bias) · both dir · variants=multiple-testing (นับไว้).
read-only · offline (data/xau_*.json) · 0 token · ไม่แตะ MT5/live.
รัน: python scripts/fv_zone_macd_backtest.py [--tf h4|h1]
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                        # noqa: E402
from agents.cluster_map import compute_cluster_map            # noqa: E402

DATA = os.path.join(_ROOT, "data")
MAX_HOLD = 240
MIN_N = 100
WIN = 600                                                     # ตรงกับ production _BARS_COUNT
PCT_WIN = 200                                                 # หน้าต่าง rolling percentile ของ osc


def _load_hlc(tf):
    with open(os.path.join(DATA, f"xau_{tf}.json"), "r", encoding="utf-8") as f:
        d = json.load(f)
    h = np.array([x[2] for x in d], float)
    l = np.array([x[3] for x in d], float)
    c = np.array([x[4] for x in d], float)
    return h, l, c


def _ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _macd_signal(c, fast=12, slow=26, sig=9):
    """คืน signal line (EMA9 ของ MACD line). causal โดยธรรมชาติ (EMA ใช้อดีต)."""
    macd_line = _ema(c, fast) - _ema(c, slow)
    return _ema(macd_line, sig)


def _pctl_causal(osc, i, win=PCT_WIN):
    """percentile ของ osc[i] เทียบหน้าต่าง [i-win, i-1] (causal, ไม่รวม i เอง? รวม i ได้—ค่าปัจจุบัน).
    คืน 0..1. ต่ำ=oversold, สูง=overbought."""
    lo = max(0, i - win + 1)
    w = osc[lo:i + 1]
    v = osc[i]
    if len(w) < 20 or not np.isfinite(v):
        return None
    return float((w <= v).mean())


def run(h, l, c, cost, point, direction="both", rr=None, use_macd=True,
        os_pct=0.20, tol_atr=0.5, buf_atr=0.5):
    """fair-value zone reversion. direction: buy|sell|both.
    rr=None → TP=mid (revert fair-value); rr=float → TP=fixed R.
    use_macd=False → ปิด filter MACD (baseline เทียบว่า MACD เพิ่ม edge ไหม).
    os_pct = เกณฑ์ oversold/overbought percentile (buy≤os_pct, sell≥1-os_pct)."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    sig = _macd_signal(c)
    n = len(c); trades = []
    i = max(R.VOL_LOOKBACK + 40, PCT_WIN + 10, 210)
    while i < n - 1:
        reg = R.detect_regime(er[i], adx[i], vp[i])
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if reg not in ("NEUTRAL", "RANGE") or av <= 0:
            i += 1; continue
        w0 = max(0, i - (WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            i += 1; continue
        sup = cm.get("support"); res = cm.get("resistance")
        if not (sup and res):                                 # ต้องมีทั้ง 2 ฝั่งถึงหา mid ได้
            i += 1; continue
        mid = (sup["level"] + res["level"]) / 2.0
        px = float(c[i]); mom = cm.get("momentum")
        osc = sig / av                                        # MACD signal scaled by ATR (bar นี้)
        pc = _pctl_causal(osc, i) if use_macd else 0.0

        side = 0
        if direction in ("buy", "both") and px < mid and sup["dist_atr"] <= tol_atr and mom != "down":
            if (not use_macd) or (pc is not None and pc <= os_pct):
                side = +1
        if side == 0 and direction in ("sell", "both") and px > mid and res["dist_atr"] <= tol_atr and mom != "up":
            if (not use_macd) or (pc is not None and pc >= 1 - os_pct):
                side = -1
        if side == 0:
            i += 1; continue

        if side > 0:
            zone = sup["level"]; sl_price = zone - buf_atr * av
        else:
            zone = res["level"]; sl_price = zone + buf_atr * av
        sl_pips = abs(px - sl_price) / point
        if sl_pips <= 0:
            i += 1; continue

        if rr is None:                                        # TP = mid (revert to fair value)
            tp_dist = abs(mid - px)
            rr_eff = tp_dist / (sl_pips * point)
            if rr_eff <= 0:
                i += 1; continue
        else:
            rr_eff = rr
        sl = px - side * sl_pips * point
        tp = px + side * sl_pips * rr_eff * point

        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            hit_sl = (l[j] <= sl) if side > 0 else (h[j] >= sl)
            hit_tp = (h[j] >= tp) if side > 0 else (l[j] <= tp)
            if hit_sl:                                        # SL-first (conservative)
                r_out, exit_i = -1.0 - cost / sl_pips, j; break
            if hit_tp:
                r_out, exit_i = rr_eff - cost / sl_pips, j; break
        if r_out is None:
            r_out = side * (c[end] - px) / (sl_pips * point) - cost / sl_pips
        trades.append(r_out)
        i = exit_i + 1
    return trades


def _stats(tr):
    n = len(tr)
    if n == 0:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t, round(float(a.sum()), 1)


def _report(label, tr, costx2=None):
    s = _stats(tr)
    if not s:
        print(f"  {label:34s} n=0"); return
    n, wr, ex, t, sm = s
    k = int(n * 0.7); oos = _stats(tr[k:]); oe = oos[2] if oos else float("nan")
    c2 = ""
    if costx2 is not None:
        s2 = _stats(costx2); c2 = f" cost2{s2[2]:+.4f}" if s2 else ""
    flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0) else "—"
    print(f"  {label:34s} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} sumR{sm:+7.1f} OOS{oe:+.4f}{c2} [{flag}]")


def main():
    tf = "h4"
    if "--tf" in sys.argv:
        tf = sys.argv[sys.argv.index("--tf") + 1].lower()
    h, l, c = _load_hlc(tf)
    point = 0.01; cost = 30.0
    print(f"\n=== FAIR-VALUE ZONE + MACD-ATR reversion (XAU {tf.upper()} · causal · SL-first · "
          f"cost-adj · OOS70/30 · MIN_N={MIN_N}) ===")
    print("gate PASS = n≥100 + exp_R>0 + t>2 + OOS exp_R>0 · cost2 = ทน cost×2 ไหม")
    print(f"bars={len(c)} · คำถาม: MACD-ATR-exhaustion + mid-bias เพิ่ม edge เหนือ no-MACD baseline ไหม?")
    print("variants หลายตัว = multiple-testing → PASS ตัวเดียวโดดๆ ระวัง overfit\n")
    VARIANTS = [
        ("both TP=mid no-MACD (baseline)", dict(direction="both", rr=None, use_macd=False)),
        ("both TP=mid +MACD os20", dict(direction="both", rr=None, use_macd=True, os_pct=0.20)),
        ("both TP=mid +MACD os10", dict(direction="both", rr=None, use_macd=True, os_pct=0.10)),
        ("buy  TP=mid +MACD os20", dict(direction="buy", rr=None, use_macd=True, os_pct=0.20)),
        ("sell TP=mid +MACD os20", dict(direction="sell", rr=None, use_macd=True, os_pct=0.20)),
        ("both rr2 no-MACD (baseline)", dict(direction="both", rr=2.0, use_macd=False)),
        ("both rr2 +MACD os20", dict(direction="both", rr=2.0, use_macd=True, os_pct=0.20)),
        ("both rr1.5 +MACD os20", dict(direction="both", rr=1.5, use_macd=True, os_pct=0.20)),
        ("buy  rr2 +MACD os20", dict(direction="buy", rr=2.0, use_macd=True, os_pct=0.20)),
        ("sell rr2 +MACD os20", dict(direction="sell", rr=2.0, use_macd=True, os_pct=0.20)),
    ]
    for name, kw in VARIANTS:
        tr = run(h, l, c, cost, point, **kw)
        tr2 = run(h, l, c, cost * 2, point, **kw)
        _report(name, tr, costx2=tr2)
    print("\n⚠️ ถ้า +MACD ไม่ยก exp_R เหนือ no-MACD baseline อย่างมีนัย = exhaustion filter ไม่เพิ่ม edge.")
    print("⚠️ ถ้าไม่มีตัวไหน PASS (t>2 + OOS>0 + ทน cost×2) = idea ไม่มี edge จริงบน history นี้ — ไม่ live.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
