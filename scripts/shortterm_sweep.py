#!/usr/bin/env python
"""scripts/shortterm_sweep.py — ปรับทุก algo เป็น short-term แล้ว backtest หา +EV (user 08-07).

sweep: strategy {momentum-breakout(TREND-gate) · tsmom-intraday(multi-horizon+confirm)}
     × timeframe {H4, H1} × pair. causal · SL-first · หัก cost จริง · non-overlap · OOS 70/30 · t-stat · MIN_N.
เก็บเฉพาะ +EV (exp_R>0 + OOS≥0). cost กัดแรงที่ TF สั้น = ตัวตัดสิน.

รัน: python scripts/shortterm_sweep.py
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
    k = int(n * 0.7); oo = np.array(tr[k:], float)
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), round(float(a.sum()), 1), t, round(float(oo.mean()), 4)


def momentum(h, l, c, cost, pt, brk=20, rr=2.0, sl_atr=1.5, max_hold=120):
    """TREND-gated Donchian breakout (= regime_momentum concept) บน TF ที่ให้."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            i += 1; continue
        hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min()); px = float(c[i])
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        slp = sl_atr * av / pt; tpp = slp * rr
        sl = px - d * slp * pt; tp = px + d * tpp * pt; end = min(i + max_hold, n - 1); r = None; ei = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                r = -1.0 - cost / slp; ei = j; break
            if (h[j] >= tp) if d > 0 else (l[j] <= tp):
                r = tpp / slp - cost / slp; ei = j; break
        if r is None:
            r = d * (c[end] - px) / (slp * pt) - cost / slp
        tr.append(r); i = ei + 1
    return tr


def tsmom(c, cost_price, lbs, confirm, px_last):
    """intraday time-series momentum (multi-horizon + short-term confirm) flip-based. คืน R เป็น %ของราคา."""
    trades = []; pos = 0; entry = 0.0; start = max(max(lbs), confirm or 0) + 2
    for i in range(start, len(c)):
        v = sum(int(np.sign(c[i] - c[i - L])) for L in lbs if i - L >= 0)
        d = 1 if v > 0 else -1 if v < 0 else 0
        if d != 0 and confirm and i - confirm >= 0:
            s = np.sign(c[i] - c[i - confirm])
            if (s > 0 and d < 0) or (s < 0 and d > 0):
                d = 0                                    # short-term สวน → ไม่ flip (hold)
        if d == 0:
            d = pos
        if d != pos:
            if pos != 0:
                trades.append((pos * (c[i] - entry) - cost_price) / px_last * 100)
            pos = d; entry = c[i]
    return trades


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    from connectors.pair_collector import _broker_map
    bmap = _broker_map() or {}
    pairs = ["XAUUSD", "XAGUSD", "BTCUSD", "WTIUSD", "EURUSD"]
    TFS = {"H4": mt5.TIMEFRAME_H4, "H1": mt5.TIMEFRAME_H1}
    # tsmom lookback ต่อ TF (≈ 1/3/7 วัน): H4 6/บาร์วัน, H1 24/บาร์วัน
    TS_LB = {"H4": [(6, 18, 42), (12, 36, 84)], "H1": [(24, 72, 168), (48, 120, 240)]}
    TS_CONFIRM = {"H4": 6, "H1": 24}
    print("\n=== SHORT-TERM SWEEP · causal · SL-first · cost-adj · OOS70/30 · MIN_N=%d ===" % MIN_N)
    print("เก็บ = exp_R>0 + OOS≥0 (+EV). ✅=OOS>0 ด้วย\n")
    winners = []
    for lg in pairs:
        brk = bmap.get(lg, lg)
        try:
            mt5.symbol_select(brk, True)
            info = mt5.symbol_info(brk)
        except Exception:
            info = None
        if not info:
            print("%s ไม่เจอ" % lg); continue
        pt = float(info.point); cost = (_sc.cost_pips(lg) if _sc else None) or 30.0
        print("── %s (cost=%.1fp) ──" % (lg, cost))
        for tfn, tf in TFS.items():
            r = mt5.copy_rates_from_pos(brk, tf, 0, 60000)
            if r is None or len(r) < 1000:
                print("  %s ข้อมูลไม่พอ" % tfn); continue
            h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float)
            # momentum breakout
            s = _st(momentum(h, l, c, cost, pt))
            if s:
                n, wr, ex, sm, t, oe = s
                fl = "✅" if ex > 0 and oe > 0 else ("+EV" if ex > 0 and oe >= 0 else "−")
                if fl != "−" and n >= MIN_N:
                    winners.append((lg, tfn, "momentum", ex, t, oe))
                print("  %-4s momentum          n=%4d WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (tfn, n, wr, ex, t, oe, fl))
            # tsmom intraday variants
            for lbs in TS_LB[tfn]:
                s = _st(tsmom(c, cost * pt, lbs, TS_CONFIRM[tfn], float(c[-1])))
                if not s:
                    continue
                n, wr, ex, sm, t, oe = s
                fl = "✅" if ex > 0 and oe > 0 else ("+EV" if ex > 0 and oe >= 0 else "−")
                if fl != "−" and n >= MIN_N:
                    winners.append((lg, tfn, "tsmom%s+cf%d" % (lbs, TS_CONFIRM[tfn]), ex, t, oe))
                print("  %-4s tsmom%-14s n=%4d WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (tfn, str(lbs), n, wr, ex, t, oe, fl))
    print("\n=== +EV WINNERS (exp_R>0 + OOS≥0, n≥%d) ===" % MIN_N)
    if winners:
        for w in sorted(winners, key=lambda x: -x[3]):
            print("  %-8s %-3s %-22s exp_R%+.4f t%+.2f OOS%+.4f" % w)
    else:
        print("  ไม่มีตัวไหน +EV — short-term ไม่มี edge (คงเดิม/stand down)")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
