#!/usr/bin/env python
"""scripts/scalp_deep.py — deep research scalp รอบ 2 (user 08-07): เรียนจากข้อผิดพลาดรอบแรก.

ข้อผิดพลาดรอบแรก (scalp_keylevels 0/24): fade/breakout single-condition = ไม่มี directional edge → WR<40%<breakeven.
แก้: แนวที่ WR สูงโดยธรรมชาติ =
  1. trend-pullback : HTF trend (H1 EMA slope) → เข้า M15 จังหวะย่อ*ตามเทรนด์* (เข้ากับโมเมนตัม = WR สูง)
  2. confluence     : trend + macro(DXY) + pullback ต้องตรงกันหมด (คุณภาพสูง เข้าน้อยลง)
  3. adaptive SL    : SL = k×ATR(M15) แทน fixed (fixed 300 แคบ/กว้างผิดจังหวะ vol) — เทียบ fixed 300 ด้วย

fixed SL 300 (สเปค) + adaptive · RR1.5-3 · causal · cost-adj · OOS · news-filter. เก็บ WR≥50%+EV.
รัน: python scripts/scalp_deep.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

MIN_N = 100


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
    k = int(n * 0.7); oe = np.array(tr[k:]).mean()
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), t, round(float(oe), 4)


def _news(atr):
    n = len(atr); ok = np.ones(n, bool)
    for i in range(200, n):
        med = np.nanmedian(atr[i - 200:i])
        if med and atr[i] > 2.0 * med:
            ok[i] = False
    return ok


def _resolve(h, l, c, i, sign, px, slp, rr, pt, cost, max_hold):
    sl = px - sign * slp * pt; tp = px + sign * slp * rr * pt
    n = len(c); end = min(i + max_hold, n - 1)
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost / slp, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / slp, j
    return sign * (c[end] - px) / (slp * pt) - cost / slp, end


def run(h, l, c, macro, cost, pt, mode, rr, sl_mode="fixed", sl_pts=300, sl_atr=1.0,
        ema_fast=20, ema_slow=50, macro_lb=24, max_hold=48):
    atr = R.atr(h, l, c); news = _news(atr)
    ef = _ema(c, ema_fast); es = _ema(c, ema_slow)
    n = len(c); tr = []; i = max(210, ema_slow + 5)
    while i < n - 1:
        if not news[i]:
            i += 1; continue
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); d = 0
        up = ef[i] > es[i] and es[i] > es[i - 3]           # เทรนด์ขึ้น (fast>slow + slow ชัน)
        dn = ef[i] < es[i] and es[i] < es[i - 3]
        if mode in ("pullback", "confluence"):
            # เข้าจังหวะย่อ*ตามเทรนด์*: uptrend + ราคาย่อแตะ EMA fast แล้วเด้ง
            near_f = abs(px - ef[i]) <= 0.5 * av
            bounce_up = c[i] > c[i - 1] and l[i] <= ef[i]
            bounce_dn = c[i] < c[i - 1] and h[i] >= ef[i]
            if up and near_f and bounce_up:
                d = 1
            elif dn and near_f and bounce_dn:
                d = -1
            if mode == "confluence" and d != 0:            # ต้อง macro(DXY) เห็นด้วย
                m = macro[i]; ml = macro[i - macro_lb]
                if m != m or ml != ml or d != (1 if m > ml else -1):
                    d = 0
        elif mode == "trendbrk":
            hh = float(h[i - 12:i].max()); ll = float(l[i - 12:i].min())
            if up and px > hh:
                d = 1
            elif dn and px < ll:
                d = -1
        if not d:
            i += 1; continue
        slp = sl_pts if sl_mode == "fixed" else max(50, sl_atr * av / pt)
        r, ei = _resolve(h, l, c, i, d, px, slp, rr, pt, cost, max_hold)
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
    print("\n=== SCALP DEEP RESEARCH รอบ 2 (trend-pullback + confluence + adaptive SL) · causal · cost-adj · OOS ===")
    print("เรียนจากรอบแรก: single-condition fade=WR ต่ำ → เทรด*ตามเทรนด์*จังหวะย่อ = WR สูง. เก็บ WR≥50%+EV\n")
    winners = []
    for tfn, tf, mh in [("M15", mt5.TIMEFRAME_M15, 48), ("M5", mt5.TIMEFRAME_M5, 96)]:
        rg = mt5.copy_rates_from_pos(g, tf, 0, 60000); re = mt5.copy_rates_from_pos(e, tf, 0, 60000)
        if rg is None or len(rg) < 2000:
            print("%s ไม่พอ" % tfn); continue
        h = rg["high"].astype(float); l = rg["low"].astype(float); c = rg["close"].astype(float); tm = rg["time"]
        emap = {int(t): float(x) for t, x in zip(re["time"], re["close"])} if re is not None else {}
        macro = np.array([emap.get(int(t), np.nan) for t in tm], float)
        pt = float(mt5.symbol_info(g).point)
        print("── GOLD %s ──" % tfn)
        grid = [("pullback fixSL300", dict(mode="pullback", sl_mode="fixed", sl_pts=300)),
                ("pullback adaptSL1.0", dict(mode="pullback", sl_mode="atr", sl_atr=1.0)),
                ("confluence fixSL300", dict(mode="confluence", sl_mode="fixed", sl_pts=300)),
                ("confluence adaptSL1.0", dict(mode="confluence", sl_mode="atr", sl_atr=1.0)),
                ("trendbrk fixSL300", dict(mode="trendbrk", sl_mode="fixed", sl_pts=300))]
        for nm, kw in grid:
            for rr in (1.5, 2.0):
                s = _st(run(h, l, c, macro, cost, pt, rr=rr, max_hold=mh, **kw))
                if not s:
                    print("  %-22s rr%.1f n<30" % (nm, rr)); continue
                n, wr, ex, t, oe = s
                spec = wr >= 50 and ex > 0 and oe > 0 and n >= MIN_N
                fl = "✅ผ่านสเปค" if spec else ("+EV" if ex > 0 and oe > 0 else "−")
                if spec:
                    winners.append((tfn, nm, rr, wr, ex, t, oe))
                print("  %-22s rr%.1f n=%5d WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (nm, rr, n, wr, ex, t, oe, fl))
    print("\n=== ผ่านสเปค WR≥50%%+EV ===")
    if winners:
        for w in sorted(winners, key=lambda z: -z[4]):
            print("  %-4s %-22s rr%.1f WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f" % w)
    else:
        print("  ยังไม่ผ่านสเปค WR≥50% — ดู +EV ที่ WR สูงสุด (best achievable) ด้านบน")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
