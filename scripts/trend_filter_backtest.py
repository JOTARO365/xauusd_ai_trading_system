#!/usr/bin/env python
"""scripts/trend_filter_backtest.py — #4 validate: D1-trend filter ลดขาดทุน gold algo ไหม (user 08-22).

สาเหตุขาดทุนจริง (trades.json): บอท short ทองสวนเทรนด์ขาขึ้น. fix เสนอ = block counter-trend entry.
เทสว่า block counter-trend ยก exp_R ของ live gold algo (regime momentum_breakout) แบบ **robust ข้าม window**
ไม่ใช่แค่ขาขึ้น 3 สัปดาห์. baseline = run_algo เดิม (parity live). trend = causal long-EMA + slope บน H1.

ablation: baseline · with-trend only · counter-trend only (ควรเป็นตัวเจ๊ง) · filter(block-counter, keep with+neutral).
quant: intrabar fill (regime_backtest.simulate_trade) · net cost30 · full xau_h1 (2014-2026 หลาย regime) ·
per-quartile stability · OOS70/30. read-only · offline · 0 order.
รัน: python scripts/trend_filter_backtest.py
"""
import json
import math
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import regime_lib as R                                        # noqa: E402
import regime_backtest as BT                                  # noqa: E402

COST = 30.0


def _load():
    d = json.load(open(os.path.join(_BASE, "data", "xau_h1.json")))
    h = np.array([x[2] for x in d], float); l = np.array([x[3] for x in d], float)
    c = np.array([x[4] for x in d], float)
    return h, l, c


def _ema(x, n):
    a = 2.0 / (n + 1.0); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _trend(c, n=480, slope_lb=48):
    """causal D1-trend proxy บน H1: EMA(480≈20วัน) + slope. UP=close>ema & ema rising · DOWN=ตรงข้าม · else NEUTRAL."""
    e = _ema(c, n); n_ = len(c); tr = np.zeros(n_, dtype=int)
    for i in range(slope_lb, n_):
        rising = e[i] > e[i - slope_lb]
        if c[i] > e[i] and rising:
            tr[i] = 1
        elif c[i] < e[i] and not rising:
            tr[i] = -1
    return tr


def _stat(r):
    n = len(r)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = r.std(ddof=1); t = r.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((r > 0).mean()) * 100, 1), float(r.mean()), t


def _report(name, trades, nbars):
    if not trades:
        print(f"  {name:26s} n=0"); return
    r = BT.net_R(trades, COST)
    n, wr, ex, t = _stat(r)
    k = int(n * 0.7); oos = _stat(r[k:])[2] if n - k > 1 else float("nan")
    # per-quartile ตาม entry-bar index
    q = [[], [], [], []]
    for tr_, rr in zip(trades, r):
        qi = min(3, int(tr_["i"] / nbars * 4)); q[qi].append(rr)
    qs = []
    for qq in q:
        qs.append(f"{np.mean(qq):+.2f}({len(qq)})" if len(qq) >= 2 else "-(%d)" % len(qq))
    npos = sum(1 for qq in q if len(qq) >= 2 and np.mean(qq) > 0)
    print(f"  {name:26s} n{n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} OOS{oos:+.4f} sumR{r.sum():+7.1f} "
          f"| Q {qs[0]} {qs[1]} {qs[2]} {qs[3]} [{'stable' if npos>=3 else '%d/4'%npos}]")


def main():
    h, l, c = _load()
    nbars = len(c)
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    tr = _trend(c)
    print(f"=== #4 TREND-FILTER validate (XAU H1 gold algo momentum_breakout · intrabar · cost{COST:.0f} · "
          f"full history) ===")
    print(f"bars={nbars} · baseline=live algo (parity) · filter=block counter-trend (keep with+neutral)")
    print("validate: counter-trend เจ๊ง + filter ยก exp_R robust ทุก quartile ไหม (ไม่ใช่แค่ recent)\n")
    base = BT.run_algo("momentum_breakout", h, l, c, atr, er, adx, vp)
    with_tr = [t for t in base if (t["dir"] == "BUY" and tr[t["i"]] == 1) or (t["dir"] == "SELL" and tr[t["i"]] == -1)]
    counter = [t for t in base if (t["dir"] == "BUY" and tr[t["i"]] == -1) or (t["dir"] == "SELL" and tr[t["i"]] == 1)]
    neutral = [t for t in base if tr[t["i"]] == 0]
    filt = with_tr + neutral                                  # block เฉพาะ counter-trend ชัด
    _report("baseline (all)", base, nbars)
    _report("with-trend only", with_tr, nbars)
    _report("COUNTER-trend only", counter, nbars)
    _report("neutral only", neutral, nbars)
    _report("FILTER (block counter)", filt, nbars)
    non_neutral = with_tr + counter                          # block เฉพาะ NEUTRAL regime (ตัวเจ๊ง robust)
    _report("FILTER2 (block NEUTRAL)", non_neutral, nbars)
    print("\nถ้า COUNTER ติดลบชัด + FILTER exp_R>baseline stable ทุก quartile = #4 validated (ลดขาดทุนจริง)")
    print("ถ้า COUNTER ไม่ต่าง/บวก = trend filter ไม่ช่วย (แค่ recent-uptrend artifact) → ไม่ wire")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
