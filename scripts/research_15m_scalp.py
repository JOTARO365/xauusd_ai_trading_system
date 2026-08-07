#!/usr/bin/env python
"""scripts/research_15m_scalp.py — หา 15m scalp เก็บกำไรสั้น (quick TP · hold สั้น). user 08-07.

ต่างจาก confluence_15m (RR2 hold ยาว) — อันนี้ "เก็บสั้น": TP เล็ก (RR 0.5-1.5) + max_hold สั้น (1-4h).
เก็บสั้น = WR ต้องสูงพอชนะ breakeven (RR0.5→67% · 0.7→59% · 1.0→50% · 1.5→40%).
entry: (A) confluence (breakout+H1+H4+macro+volume — filter ที่ทำให้ 15m +EV) · (B) mean-rev quick (fade z + volume).
causal · SL-first · adaptive/fixed SL · หัก cost · OOS · เลี่ยงข่าว. เก็บ +EV (exp_R>0+OOS>0).
รัน: python scripts/research_15m_scalp.py
"""
import math
import os
import sys

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


def run(h, l, c, vol, atr, h1t, h4t, mac, cost, pt, mode, rr, sl_mode="fixed", sl_pts=300, sl_atr=1.0,
        brk=12, zwin=20, z=1.5, vk=1.3, mh=16):
    n = len(c); tr = []; i = 210
    vmed = np.zeros(n)
    for k in range(200, n):
        vmed[k] = np.median(vol[k - 200:k]) or 1
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or vmed[i] <= 0 or vol[i] > 2.0 * vmed[i]:
            i += 1; continue
        px = float(c[i]); d = 0
        if mode == "confluence":
            hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
            d = 1 if px > hh else -1 if px < ll else 0
            if d:
                m = mac[i]; ml = mac[i - 24] if i - 24 >= 0 else np.nan
                if (h1t[i] != d or h4t[i] != d or m != m or ml != ml
                        or (1 if m > ml else -1) != d or vol[i] < vk * vmed[i]):
                    d = 0
        elif mode == "meanrev":                            # fade z-extreme + volume (bounce เร็ว = เก็บสั้น)
            w = c[i - zwin + 1:i + 1]; mm, sd = float(w.mean()), float(w.std())
            if sd > 0:
                zz = (px - mm) / sd
                if zz <= -z and vol[i] >= vk * vmed[i]:
                    d = 1
                elif zz >= z and vol[i] >= vk * vmed[i]:
                    d = -1
        if not d:
            i += 1; continue
        slp = sl_pts if sl_mode == "fixed" else max(50, sl_atr * av / pt)
        sl = px - d * slp * pt; tp = px + d * slp * rr * pt
        end = min(i + mh, n - 1); r = None; ei = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                r = -1.0 - cost / slp; ei = j; break
            if (h[j] >= tp) if d > 0 else (l[j] <= tp):
                r = rr - cost / slp; ei = j; break
        if r is None:                                      # time-exit สั้น (เก็บสั้น: ไม่ถือยาว)
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
    m = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_M15, 0, 60000)
    if m is None or len(m) < 3000:
        print("M15 ไม่พอ"); return
    h = m["high"].astype(float); l = m["low"].astype(float); c = m["close"].astype(float)
    tm = m["time"].astype(np.int64); vol = m["tick_volume"].astype(float)
    h1 = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_H1, 0, 20000)
    h4 = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_H4, 0, 10000)
    em = mt5.copy_rates_from_pos(e, mt5.TIMEFRAME_M15, 0, 60000)
    h1t = _slope_map(tm, h1["time"].astype(np.int64), h1["close"].astype(float))
    h4t = _slope_map(tm, h4["time"].astype(np.int64), h4["close"].astype(float))
    emap = {int(t): float(x) for t, x in zip(em["time"], em["close"])}
    mac = np.array([emap.get(int(t), np.nan) for t in tm], float)
    atr = R.atr(h, l, c); pt = float(mt5.symbol_info(g).point)
    yrs = (tm[-1] - tm[0]) / (365.25 * 24 * 3600)
    print("\n=== 15m SCALP เก็บสั้น (quick TP · hold สั้น) · causal · cost-adj · OOS ===")
    print("เก็บ +EV. breakeven WR: RR0.5=67%% · 0.7=59%% · 1.0=50%% · 1.5=40%%\n")
    print("── GOLD 15m (bars=%d ~%.1fปี cost=%.0fp) ──" % (len(c), yrs, cost))
    win = []
    for mode in ("confluence", "meanrev"):
        for slm, slv in (("fixed", 300), ("atr", 1.0)):
            for rr in (0.5, 0.7, 1.0, 1.5):
                kw = dict(mode=mode, rr=rr, sl_mode=slm, mh=16)
                kw["sl_pts" if slm == "fixed" else "sl_atr"] = slv
                s = _st(run(h, l, c, vol, atr, h1t, h4t, mac, cost, pt, **kw))
                tag = "%s %s%s rr%.1f" % (mode, slm, slv, rr)
                if not s:
                    print("  %-26s n<40" % tag); continue
                n, wr, ex, t, oe = s
                be = 100.0 / (1 + rr)
                fl = "✅+EV" if ex > 0 and oe > 0 and n >= 60 else "−"
                if fl != "−":
                    win.append((tag, n, wr, ex, t, oe))
                print("  %-26s n=%5d fire%4.0f/ปี WR%5.1f%%(be%2.0f) exp_R%+.4f t%+.2f OOS%+.4f %s" % (tag, n, n / yrs, wr, be, ex, t, oe, fl))
    print("\n=== +EV เก็บสั้น ===")
    for w in sorted(win, key=lambda z: -z[3]):
        print("  %-26s n=%d WR%.1f%% exp_R%+.4f t%+.2f OOS%+.4f" % w)
    if not win:
        print("  ไม่มี +EV — quick-TP scalp ไม่ผ่าน (WR ไม่ชนะ breakeven)")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
