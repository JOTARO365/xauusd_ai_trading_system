#!/usr/bin/env python
"""scripts/gold_scalp_session.py — หา gold scalp ที่เวิร์ค: session-filter + H1/M15 + confluence (user 08-07).

ทำไมทอง scalp ตัน: cost/ATR สูง (M15 ~10%) + Asian chop drag WR. ลองแก้:
  - session filter: เทรดเฉพาะ London/NY (trend สะอาด, liquidity สูง) — ตัด Asian chop
  - TF: H1 (cost/ATR ~4%) เทียบ M15 (~10%) — cost drag น้อยกว่า
  - entry: confluence (breakout + H1/H4 trend + macro DXY + volume) / momentum + volume
causal · SL-first · adaptive SL · cost-adj · OOS. ⚠️ session-gate เสี่ยง overfit → ดู OOS เข้ม. เก็บ +EV+OOS.
รัน: python scripts/gold_scalp_session.py
"""
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402


def _ema(a, n):
    e = np.zeros_like(a); e[0] = a[0]; k = 2 / (n + 1)
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _slope_map(m15t, ht, hc, n=50):
    e = _ema(hc, n); sl = np.sign(e - np.concatenate([e[:3], e[:-3]]))
    return sl[np.clip(np.searchsorted(ht, m15t, "right") - 1, 0, len(sl) - 1)]


def _st(tr):
    n = len(tr)
    if n < 40:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7)
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), round(t, 2), round(float(np.array(tr[k:]).mean()), 4)


def run(h, l, c, hr, vol, atr, h1t, h4t, mac, cost, pt, mode, rr, sess, sl_atr=1.0, brk=12, vk=1.3, mh=32):
    lo_h, hi_h = sess
    n = len(c); tr = []; i = 210
    vmed = np.zeros(n)
    for k in range(200, n):
        vmed[k] = np.median(vol[k - 200:k]) or 1
    while i < n - 1:
        if not (lo_h <= hr[i] < hi_h):                     # session filter (UTC hour)
            i += 1; continue
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or vmed[i] <= 0 or vol[i] > 2.0 * vmed[i]:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        if mode == "momentum":
            if vol[i] < vk * vmed[i]:
                i += 1; continue
        elif mode == "confluence":
            m = mac[i]; ml = mac[i - 24] if i - 24 >= 0 else np.nan
            if (h1t[i] != d or h4t[i] != d or m != m or ml != ml
                    or (1 if m > ml else -1) != d or vol[i] < vk * vmed[i]):
                i += 1; continue
        elif mode == "tf_only":                            # H1+H4 trend + volume (ไม่ใช้ macro)
            if h1t[i] != d or h4t[i] != d or vol[i] < vk * vmed[i]:
                i += 1; continue
        slp = max(30, sl_atr * av / pt)
        sl = px - d * slp * pt; tp = px + d * slp * rr * pt
        end = min(i + mh, n - 1); r = None; ei = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                r = -1.0 - cost / slp; ei = j; break
            if (h[j] >= tp) if d > 0 else (l[j] <= tp):
                r = rr - cost / slp; ei = j; break
        if r is None:
            r = d * (c[end] - px) / (slp * pt) - cost / slp
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
    bm = _broker_map() or {}
    g = bm.get("XAUUSD", __import__("config").SYMBOL); e = bm.get("EURUSD", "EURUSD")
    cost = (_sc.cost_pips("XAUUSD") if _sc else None) or 30.0
    print("\n=== GOLD SCALP + SESSION FILTER (London/NY) · confluence/momentum/tf · causal · cost-adj · OOS ===")
    print("แก้ cost/chop: เทรดเฉพาะ session สะอาด + H1(cost ต่ำกว่า M15). เก็บ +EV+OOS>0 (ระวัง session overfit)\n")
    win = []
    for tfn, tf in [("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1)]:
        m = mt5.copy_rates_from_pos(g, tf, 0, 60000)
        if m is None or len(m) < 3000:
            print("%s ไม่พอ" % tfn); continue
        h = m["high"].astype(float); l = m["low"].astype(float); c = m["close"].astype(float)
        tm = m["time"].astype(np.int64); vol = m["tick_volume"].astype(float)
        hr = np.array([datetime.fromtimestamp(int(t), timezone.utc).hour for t in tm])
        h1 = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_H1, 0, 20000)
        h4 = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_H4, 0, 10000)
        em = mt5.copy_rates_from_pos(e, tf, 0, 60000)
        h1t = _slope_map(tm, h1["time"].astype(np.int64), h1["close"].astype(float))
        h4t = _slope_map(tm, h4["time"].astype(np.int64), h4["close"].astype(float))
        emap = {int(t): float(x) for t, x in zip(em["time"], em["close"])}
        mac = np.array([emap.get(int(t), np.nan) for t in tm], float)
        atr = R.atr(h, l, c); pt = float(mt5.symbol_info(g).point)
        yrs = (tm[-1] - tm[0]) / (365.25 * 24 * 3600)
        med = float(np.nanmedian(atr[-1000:])) / pt
        print("── GOLD %s (cost/ATR=%.1f%%) ──" % (tfn, cost / med * 100))
        SESS = {"all": (0, 24), "LN-NY 7-21": (7, 21), "NY 13-21": (13, 21), "overlap 13-17": (13, 17)}
        for mode in ("momentum", "confluence", "tf_only"):
            for sname, sess in SESS.items():
                for rr in (1.5, 2.0):
                    s = _st(run(h, l, c, hr, vol, atr, h1t, h4t, mac, cost, pt, mode=mode, rr=rr, sess=sess))
                    if not s:
                        continue
                    n, wr, ex, t, oe = s
                    fl = "✅" if ex > 0 and oe > 0 and n >= 60 else "−"
                    if fl == "✅":
                        win.append((tfn, mode, sname, rr, n, wr, ex, t, oe))
                        print("  %-4s %-10s %-11s rr%.1f n=%4d WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f ✅" % (tfn, mode, sname, rr, n, wr, ex, t, oe))
    print("\n=== +EV gold scalp (session) ===")
    for w in sorted(win, key=lambda z: -z[6])[:15]:
        print("  %-4s %-10s %-11s rr%.1f n=%d WR%.1f%% exp_R%+.4f t%+.2f OOS%+.4f" % w)
    if not win:
        print("  ไม่มี +EV — session filter ไม่ช่วย (ทอง scalp ตันจริง)")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
