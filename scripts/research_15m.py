#!/usr/bin/env python
"""scripts/research_15m.py — research รอบสุดท้าย 15m: แนวใหม่ที่ยังไม่เทส (user 08-07 ทำเลย).

เรียนจาก 54 variant ก่อน (fade/breakout/pullback single/double-condition = −EV, WR~40%).
ลองแนวที่ selective สุด (คุณภาพ > ความถี่):
  A. confluence-strict : 15m breakout + H1 trend + H4 trend + macro(DXY) ต้องตรง**ทั้งหมด** (rare, high-quality)
  B. vol-surge         : 15m breakout + tick-volume surge (>k×median) = order-flow proxy (มี demand จริง)
  C. confluence + vol  : A + B

causal · SL-first · adaptive SL(k×ATR) · หัก cost · OOS · เลี่ยงข่าว(vol spike). เก็บ +EV.
รัน: python scripts/research_15m.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402


def _ema(a, n):
    k = 2 / (n + 1); e = np.zeros_like(a); e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _st(tr):
    n = len(tr)
    if n < 30:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7)
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), round(t, 2), round(float(np.array(tr[k:]).mean()), 4)


def _htf_trend_map(m15_time, htf_time, htf_close, ema_n=50):
    """ทิศเทรนด์ HTF (EMA slope sign) map ไปที่ทุกแท่ง m15 (causal: ใช้ HTF บาร์ที่ปิดก่อน t)."""
    es = _ema(htf_close, ema_n)
    slope = np.sign(es - np.concatenate([es[:3], es[:-3]]))   # es[i]-es[i-3]
    idx = np.searchsorted(htf_time, m15_time, side="right") - 1
    idx = np.clip(idx, 0, len(slope) - 1)
    return slope[idx]


def run(h, l, c, vol, cost, pt, h1t, h4t, mac, mode, rr=2.0, sl_atr=1.0, brk=12, vk=1.5, max_hold=48):
    atr = R.atr(h, l, c); n = len(c); tr = []; i = max(210, brk + 2)
    volmed = np.zeros(n)
    for k in range(200, n):
        volmed[k] = np.median(vol[k - 200:k]) or 1
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or volmed[i] <= 0:
            i += 1; continue
        if vol[i] > 2.0 * volmed[i]:                       # เลี่ยงข่าว (vol spike สุด)
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0         # 15m breakout
        if not d:
            i += 1; continue
        ok = True
        if mode in ("confluence", "conf_vol"):             # H1 + H4 + macro ต้องตรงทิศ
            if h1t[i] != d or h4t[i] != d:
                ok = False
            m = mac[i]; ml = mac[i - 24] if i - 24 >= 0 else np.nan
            if ok and (m != m or ml != ml or (1 if m > ml else -1) != d):
                ok = False
        if mode in ("volsurge", "conf_vol") and ok:        # order-flow: ต้องมี volume surge หนุน breakout
            if vol[i] < vk * volmed[i]:
                ok = False
        if not ok:
            i += 1; continue
        slp = max(50, sl_atr * av / pt)
        sl = px - d * slp * pt; tp = px + d * slp * rr * pt
        end = min(i + max_hold, n - 1); r = None; ei = end
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
    print("\n=== RESEARCH 15m รอบสุดท้าย (multi-TF confluence + order-flow volume) · causal · cost-adj · OOS ===")
    print("selective สุด: 15m breakout + H1 + H4 + macro ตรงหมด / volume surge. เก็บ +EV\n")
    m = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_M15, 0, 60000)
    if m is None or len(m) < 3000:
        print("M15 ไม่พอ"); mt5.shutdown(); return
    h = m["high"].astype(float); l = m["low"].astype(float); c = m["close"].astype(float)
    tm = m["time"].astype(np.int64); vol = m["tick_volume"].astype(float)
    h1 = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_H1, 0, 20000)
    h4 = mt5.copy_rates_from_pos(g, mt5.TIMEFRAME_H4, 0, 10000)
    em = mt5.copy_rates_from_pos(e, mt5.TIMEFRAME_M15, 0, 60000)
    h1t = _htf_trend_map(tm, h1["time"].astype(np.int64), h1["close"].astype(float))
    h4t = _htf_trend_map(tm, h4["time"].astype(np.int64), h4["close"].astype(float))
    emap = {int(t): float(x) for t, x in zip(em["time"], em["close"])}
    mac = np.array([emap.get(int(t), np.nan) for t in tm], float)
    pt = float(mt5.symbol_info(g).point)
    yrs = (tm[-1] - tm[0]) / (365.25 * 24 * 3600)
    print("── GOLD 15m (bars=%d ~%.1fปี cost=%.0fp) ──" % (len(c), yrs, cost))
    grid = [("confluence rr1.5", dict(mode="confluence", rr=1.5)),
            ("confluence rr2", dict(mode="confluence", rr=2.0)),
            ("volsurge rr1.5", dict(mode="volsurge", rr=1.5, vk=1.5)),
            ("volsurge rr2 vk2", dict(mode="volsurge", rr=2.0, vk=2.0)),
            ("conf_vol rr1.5", dict(mode="conf_vol", rr=1.5)),
            ("conf_vol rr2", dict(mode="conf_vol", rr=2.0))]
    any_pass = False
    for nm, kw in grid:
        s = _st(run(h, l, c, vol, cost, pt, h1t, h4t, mac, **kw))
        if not s:
            print("  %-20s n<30" % nm); continue
        n, wr, ex, t, oe = s
        fl = "✅+EV" if ex > 0 and oe > 0 and n >= 60 else "−"
        if fl != "−":
            any_pass = True
        print("  %-20s n=%5d fire=%4.0f/ปี WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (nm, n, n / yrs, wr, ex, t, oe, fl))
    print("\n" + ("มี +EV — ดูด้านบน (✅)" if any_pass else "ไม่มี +EV — 15m ไม่มี edge แม้ multi-TF confluence + order-flow (final)"))
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
