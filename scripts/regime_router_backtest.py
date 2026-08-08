#!/usr/bin/env python
"""scripts/regime_router_backtest.py — regime-router (สภาพตลาด→สลับ algo, ไม่ใช้ LLM). user 08-08.

แต่ละแท่ง: detect regime → route algo ที่เหมาะ:
  TREND          → momentum breakout (Donchian + ATR SL/TP)
  RANGE/NEUTRAL  → mean-reversion z-fade
  RISK-OFF       → stand down (ไม่เข้า)
เทียบกับ single-algo (momentum-only / meanrev-only) ต่อคู่. causal · SL-first · cost-adj · OOS70/30.
รัน: python scripts/regime_router_backtest.py [--all]
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

MIN_N = 80


def _st(tr):
    n = len(tr)
    if n < 20:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7)
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), round(t, 2), round(float(np.array(tr[k:]).mean()), 4)


def _resolve(h, l, c, i, sign, px, slp, rr, pt, cost, mh):
    sl = px - sign * slp * pt; tp = px + sign * slp * rr * pt
    n = len(c); end = min(i + mh, n - 1)
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost / slp, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / slp, j
    return sign * (c[end] - px) / (slp * pt) - cost / slp, end


def run(h, l, c, cost, pt, mode="router", brk=20, mrwin=60, z=1.25, mh=120):
    """mode: router (regime→algo) · mom (momentum ทุกแท่ง) · mr (mean-rev ทุกแท่ง)."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk, mrwin) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        reg = R.detect_regime(er[i], adx[i], vp[i])
        px = float(c[i]); d = 0; rr = 2.0; slp = 1.5 * av / pt
        use_mom = (mode == "mom") or (mode == "router" and reg == "TREND")
        use_mr = (mode == "mr") or (mode == "router" and reg in ("RANGE", "NEUTRAL"))
        if use_mom:
            hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
            d = 1 if px > hh else -1 if px < ll else 0
            rr = 2.0; slp = 1.5 * av / pt
        elif use_mr:
            w = c[i - mrwin + 1:i + 1]; m, sd = float(w.mean()), float(w.std())
            if sd > 0:
                zz = (px - m) / sd
                d = 1 if zz <= -z else -1 if zz >= z else 0
            rr = 1.0; slp = 1.2 * av / pt
        if not d or slp <= 0:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, slp, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    from connectors.pair_collector import _broker_map
    from agents import algo_registry as reg
    bm = _broker_map() or {}
    uni = reg.UNIVERSE if "--all" in sys.argv else ["XAUUSD", "XAGUSD", "BTCUSD", "WTIUSD", "EURUSD", "USDJPY"]
    print("\n=== REGIME-ROUTER (สภาพ→สลับ algo, ไม่ใช้ LLM) vs single-algo · causal · cost-adj · OOS ===")
    print("router: TREND→momentum · RANGE/NEUTRAL→mean-rev · RISK-OFF→พัก\n")
    print("%-8s | %-32s | %-28s | %-28s" % ("คู่", "ROUTER", "momentum-only", "meanrev-only"))
    win = []
    for lg in uni:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 30000)
            info = mt5.symbol_info(sym)
        except Exception:
            r = info = None
        if r is None or len(r) < 800 or not info:
            print("%-8s ข้อมูลไม่พอ" % lg); continue
        h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float)
        cost = (_sc.cost_pips(lg) if _sc else None) or 30.0
        pt = float(info.point)

        def fmt(s):
            if not s:
                return "n<20"
            n, wr, ex, t, oe = s
            fl = "✅" if ex > 0 and oe > 0 and n >= MIN_N else ("+" if ex > 0 else "−")
            return "n%4d exp%+.4f t%+.2f OOS%+.4f%s" % (n, ex, t, oe, fl)
        sr = _st(run(h, l, c, cost, pt, "router"))
        sm = _st(run(h, l, c, cost, pt, "mom"))
        smr = _st(run(h, l, c, cost, pt, "mr"))
        print("%-8s | %-32s | %-28s | %-28s" % (lg, fmt(sr), fmt(sm), fmt(smr)))
        if sr and sr[2] > 0 and sr[4] > 0 and sr[0] >= MIN_N:
            win.append((lg, sr[2], sr[3], sr[4]))
    print("\n=== ROUTER +EV (exp>0 + OOS>0) ===")
    for w in sorted(win, key=lambda z: -z[1]):
        print("  %-8s exp_R%+.4f t%+.2f OOS%+.4f" % w)
    if not win:
        print("  ไม่มี — regime-routing ไม่ช่วย (component algo อ่อนทั้งคู่)")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
