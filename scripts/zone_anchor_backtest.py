#!/usr/bin/env python
"""scripts/zone_anchor_backtest.py — #1 validate: zone-anchored LIMIT entry ดีกว่า market-entry ไหม (user 08-22).

user เน้น: algo ต้องเปิดจากแนว demand/supply ที่คำนวณ (ไม่ chase breakout). เทส:
signal เดิม (momentum_breakout dir + block-NEUTRAL จาก #4) แต่แทน market@close ด้วย **LIMIT ที่ causal zone**
(BUY→nearest support / SELL→nearest resistance, swing-pivot causal) → fill เมื่อราคาย่อกลับใน K bars.
benefit hypothesis: fill ราคาดีขึ้น (buy ที่ support ไม่ใช่ยอด breakout) → R ดีขึ้น. risk: adverse selection (fill
เฉพาะตอนย่อ, พลาด runaway) — Fable เจอกับ scalp limit มาแล้ว. วัดจริง.

quant: causal zone (sr_entry_gate swing) · intrabar fill · net cost30 · full xau_h1 · per-quartile · OOS.
read-only · offline · 0 order. รัน: python scripts/zone_anchor_backtest.py
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
from agents import sr_entry_gate as SRG                       # noqa: E402
from scripts.trend_filter_backtest import _trend             # noqa: E402

COST = 30.0
FILL_WIN = 24            # H1 bars ให้ราคาย่อกลับ zone (1 วัน)
RR = 2.0
BUF_ATR = 0.5


def _load():
    d = json.load(open(os.path.join(_BASE, "data", "xau_h1.json")))
    return (np.array([x[2] for x in d], float), np.array([x[3] for x in d], float),
            np.array([x[4] for x in d], float))


def _nearest_zone(h, l, i, px, d, atr):
    """causal: nearest support (d=BUY) ใต้ px / resistance (d=SELL) เหนือ px จาก swing cluster. คืน level หรือ None."""
    lookback, pivot, _, min_touches, cluster_atr = SRG.DEFAULTS
    res, sup = SRG._swing_levels(h, l, i, 60, pivot)
    tol = cluster_atr * atr
    if d == "BUY":
        cl = SRG._cluster(sup, tol)
        below = [(lv, tc) for lv, tc in cl if lv < px and tc >= min_touches]
        return max(below, key=lambda x: x[0])[0] if below else None
    else:
        cl = SRG._cluster(res, tol)
        above = [(lv, tc) for lv, tc in cl if lv > px and tc >= min_touches]
        return min(above, key=lambda x: x[0])[0] if above else None


def _sim_from(entry_i, entry_px, d, sl_px, tp_px, h, l, c, max_hold=500):
    sign = 1.0 if d == "BUY" else -1.0
    risk = abs(entry_px - sl_px)
    if risk <= 0:
        return None
    end = min(entry_i + max_hold, len(c) - 1)
    for j in range(entry_i + 1, end + 1):
        hit_sl = l[j] <= sl_px if d == "BUY" else h[j] >= sl_px
        hit_tp = h[j] >= tp_px if d == "BUY" else l[j] <= tp_px
        if hit_sl and hit_tp:
            return -1.0
        if hit_sl:
            return -1.0
        if hit_tp:
            return sign * (tp_px - entry_px) / risk
    return sign * (c[end] - entry_px) / risk


def run_zone_anchor(base_trades, h, l, c, atr, tr):
    """เข้าเฉพาะ non-neutral signal, LIMIT ที่ zone, fill ถ้าย่อกลับใน FILL_WIN. คืน (trades, n_signal, n_filled)."""
    out = []; n_sig = 0; n_fill = 0
    for t in base_trades:
        i = t["i"]; d = t["dir"]
        if tr[i] == 0:                                        # block NEUTRAL (#4 validated)
            continue
        n_sig += 1
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            continue
        zone = _nearest_zone(h, l, i, float(c[i]), d, av)
        if zone is None:
            continue
        # fill: ราคาย่อกลับแตะ zone ใน FILL_WIN bars
        filled_i = None
        for j in range(i + 1, min(i + 1 + FILL_WIN, len(c))):
            if (d == "BUY" and l[j] <= zone) or (d == "SELL" and h[j] >= zone):
                filled_i = j; break
        if filled_i is None:
            continue                                          # ไม่ย่อกลับ = ไม่เข้า (adverse selection)
        n_fill += 1
        sl_px = zone - BUF_ATR * av if d == "BUY" else zone + BUF_ATR * av
        tp_px = zone + RR * BUF_ATR * av if d == "BUY" else zone - RR * BUF_ATR * av
        r = _sim_from(filled_i, zone, d, sl_px, tp_px, h, l, c)
        if r is not None:
            sl_pips = abs(zone - sl_px) / R.POINT
            out.append({"i": i, "dir": d, "R_gross": r, "sl_pips": max(1, sl_pips)})
    return out, n_sig, n_fill


def _stat(r):
    n = len(r)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = r.std(ddof=1); t = r.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((r > 0).mean()) * 100, 1), float(r.mean()), t


def _report(name, trades, nbars):
    if not trades:
        print(f"  {name:30s} n=0"); return
    r = BT.net_R(trades, COST)
    n, wr, ex, t = _stat(r)
    k = int(n * 0.7); oos = _stat(r[k:])[2] if n - k > 1 else float("nan")
    q = [[], [], [], []]
    for tr_, rr in zip(trades, r):
        q[min(3, int(tr_["i"] / nbars * 4))].append(rr)
    npos = sum(1 for qq in q if len(qq) >= 2 and np.mean(qq) > 0)
    print(f"  {name:30s} n{n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} OOS{oos:+.4f} sumR{r.sum():+7.1f} "
          f"[{'stable' if npos>=3 else '%d/4'%npos}]")


def main():
    h, l, c = _load(); nbars = len(c)
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    tr = _trend(c)
    print(f"=== #1 ZONE-ANCHOR entry validate (XAU H1 · LIMIT@causal zone + block-NEUTRAL · cost{COST:.0f}) ===")
    print(f"bars={nbars} · เทียบ market-entry(#4 filtered) vs zone-anchor LIMIT (fill ถ้าย่อกลับใน {FILL_WIN}h)\n")
    base = BT.run_algo("momentum_breakout", h, l, c, atr, er, adx, vp)
    # market-entry baseline (block-neutral)
    mkt = [t for t in base if tr[t["i"]] != 0]
    _report("market-entry (block-neutral)", mkt, nbars)
    za, n_sig, n_fill = run_zone_anchor(base, h, l, c, atr, tr)
    print(f"  [zone-anchor: {n_sig} signal → {n_fill} filled ({100*n_fill/max(1,n_sig):.0f}% ย่อกลับ zone)]")
    _report("ZONE-ANCHOR LIMIT", za, nbars)
    print("\nถ้า zone-anchor exp_R > market-entry + stable = #1 ช่วยจริง (fill ดี). ถ้าแย่กว่า = adverse selection กิน")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
