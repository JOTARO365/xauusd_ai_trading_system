#!/usr/bin/env python
"""scripts/zone_reaction_backtest.py — Candidate #2: zone-reaction (recency + strength) long-only.

ไอเดีย (จาก UHAS zone ladder: แต่ละโซนมี "ความแข็ง 0-100" + "แตะล่าสุด N วันก่อน"): ทองเด้งจากโซนรับ
ที่ "แข็ง + สด" ดีกว่าโซนอ่อน/เก่า. เทสว่า recency (bars-since-touch) + strength (touches) เพิ่ม edge ให้
การซื้อที่แนวรับจริงไหม — เทียบ baseline (sr_fade BUY-at-support) กับ +fresh / +strong / +ทั้งคู่.

long-only (LONG_ONLY_ALL บล็อก SELL → fade-at-resistance ทำได้แค่ filter ไม่ใช่ entry). ใช้ S/R source
เดียวกับ production (compute_cluster_map) + regime_lib เดียวกับ sr_fade — ไม่ drift จาก logic จริง.
quant: causal · SL-first · non-overlap · cost/sl_pips · OOS70/30 · MIN_N=100 · t>2.
read-only · offline (data/xau_*.json, ไม่แตะ MT5/live) · 0 token.
รัน: python scripts/zone_reaction_backtest.py [--tf h4|h1]
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


def _load_hlc(tf):
    with open(os.path.join(DATA, f"xau_{tf}.json"), "r", encoding="utf-8") as f:
        d = json.load(f)
    h = np.array([x[2] for x in d], float)
    l = np.array([x[3] for x in d], float)
    c = np.array([x[4] for x in d], float)
    return h, l, c


def _bars_since_touch(low_win, level, tol_abs):
    """จำนวนแท่งนับจากล่าสุดที่ low แตะโซน (ภายใน tol_abs). มากกว่า WIN = ไม่เจอในหน้าต่าง."""
    for k in range(len(low_win) - 1, -1, -1):
        if abs(low_win[k] - level) <= tol_abs:
            return len(low_win) - 1 - k
    return len(low_win)


def run(h, l, c, cost, point, rr=2.0, min_touch=3, tol_atr=0.4, buf_atr=0.5,
        confirm=True, fresh_max=None, strong_min=None):
    """BUY-at-support only. filter: fresh_max = bars-since-touch ≤ K, strong_min = touches ≥ K.
    คืน list ของ R ต่อไม้ (non-overlap). causal, SL-first."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); trades = []
    i = max(R.VOL_LOOKBACK + 40, 210)
    while i < n - 1:
        reg = R.detect_regime(er[i], adx[i], vp[i])
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if reg not in ("NEUTRAL", "RANGE") or av <= 0:
            i += 1; continue
        w0 = max(0, i - (WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            i += 1; continue
        px = float(c[i]); mom = cm.get("momentum"); sup = cm.get("support")
        if not (sup and sup["touches"] >= min_touch and px >= sup["level"]
                and sup["dist_atr"] <= tol_atr and mom != "down"):
            i += 1; continue
        rng = float(h[i] - l[i]) or 1e-9
        if confirm and (c[i] - l[i]) / rng < 0.6:             # แท่งปฏิเสธล่าง (bounce ยืนยัน)
            i += 1; continue
        if strong_min is not None and sup["touches"] < strong_min:
            i += 1; continue
        if fresh_max is not None:
            bst = _bars_since_touch(l[w0:i + 1], sup["level"], tol_atr * av)
            if bst > fresh_max:
                i += 1; continue
        zone = sup["level"]; sl_price = zone - buf_atr * av
        sl_pips = abs(px - sl_price) / point
        if sl_pips <= 0:
            i += 1; continue
        sl = px - sl_pips * point; tp = px + sl_pips * rr * point
        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            if l[j] <= sl:                                    # SL-first (conservative)
                r_out, exit_i = -1.0 - cost / sl_pips, j; break
            if h[j] >= tp:
                r_out, exit_i = rr - cost / sl_pips, j; break
        if r_out is None:
            r_out = (c[end] - px) / (sl_pips * point) - cost / sl_pips
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


def _report(label, tr):
    s = _stats(tr)
    if not s:
        print(f"  {label:28s} n=0"); return
    n, wr, ex, t, sm = s
    k = int(n * 0.7); oos = _stats(tr[k:]); oe = oos[2] if oos else float("nan")
    flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0) else "—"
    print(f"  {label:28s} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} sumR{sm:+7.1f} OOS{oe:+.4f} [{flag}]")


def main():
    tf = "h4"
    if "--tf" in sys.argv:
        tf = sys.argv[sys.argv.index("--tf") + 1].lower()
    h, l, c = _load_hlc(tf)
    point = 0.01; cost = 30.0
    print(f"\n=== ZONE-REACTION backtest (XAU {tf.upper()} · BUY-at-support · recency+strength · "
          f"causal · SL-first · cost-adj · OOS70/30 · MIN_N={MIN_N}) ===")
    print("gate PASS = n≥100 + exp_R>0 + t>2 + OOS exp_R>0 · long-only (SELL บล็อก LONG_ONLY_ALL)")
    print(f"bars={len(c)} · เทสว่า fresh/strong เพิ่ม edge เหนือ baseline ไหม (variants=multiple-testing)\n")
    VARIANTS = [
        ("baseline rr2 confirm", dict(rr=2.0)),
        ("+ strong touch≥6", dict(rr=2.0, strong_min=6)),
        ("+ strong touch≥8", dict(rr=2.0, strong_min=8)),
        ("+ fresh ≤20bar", dict(rr=2.0, fresh_max=20)),
        ("+ fresh ≤10bar", dict(rr=2.0, fresh_max=10)),
        ("+ fresh≤20 & strong≥6", dict(rr=2.0, fresh_max=20, strong_min=6)),
        ("+ fresh≤10 & strong≥8", dict(rr=2.0, fresh_max=10, strong_min=8)),
        ("rr3 fresh≤20 strong≥6", dict(rr=3.0, fresh_max=20, strong_min=6)),
        ("rr1.5 fresh≤20 strong≥6", dict(rr=1.5, fresh_max=20, strong_min=6)),
    ]
    for name, kw in VARIANTS:
        _report(name, run(h, l, c, cost, point, **kw))
    print("\n⚠️ ถ้า fresh/strong ไม่ยก exp_R เหนือ baseline อย่างมีนัย = UHAS recency/strength ไม่เพิ่ม edge จริง.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
