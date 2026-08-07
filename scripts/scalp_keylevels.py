#!/usr/bin/env python
"""scripts/scalp_keylevels.py — หา scalp algo ตามสเปค user 08-07:
เข้าถี่ · จุดสำคัญของราคา · TF เล็ก · SL 300pt คงที่ · RR 1.5-3 · WR≥50% · ชนะสถิติ · เลี่ยงข่าว.

key-level entries (จุดสำคัญ): VWAP-revert · prior-day H/L bounce · round-$ level · micro-Donchian break.
news filter (proxy): ข้ามบาร์ที่ ATR spike > 2× median (ข่าว=vol พุ่ง; historical calendar backtest ตรงไม่ได้).
causal · SL-first · หัก cost · OOS70/30. เก็บเฉพาะ WR≥50% + exp_R>0 + OOS>0.
รัน: python scripts/scalp_keylevels.py
"""
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

SL_POINTS = 300          # สเปค: SL คงที่ 300 จุด
MIN_N = 100


def _st(tr):
    n = len(tr)
    if n < 30:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7); oe = np.array(tr[k:]).mean()
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), t, round(float(oe), 4)


def _news_mask(atr):
    """True = บาร์ปลอดข่าว (ATR ไม่ spike). proxy: ATR ≤ 2× median(rolling 200)."""
    n = len(atr); ok = np.ones(n, bool)
    for i in range(200, n):
        med = np.nanmedian(atr[i - 200:i])
        if med and atr[i] > 2.0 * med:
            ok[i] = False
    return ok


def _resolve(h, l, c, i, sign, px, sl_pts, rr, pt, cost, max_hold):
    slp = sl_pts
    sl = px - sign * slp * pt; tp = px + sign * slp * rr * pt
    n = len(c); end = min(i + max_hold, n - 1)
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost / slp, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / slp, j
    return sign * (c[end] - px) / (slp * pt) - cost / slp, end


def _session_vwap(h, l, c, tm):
    tp3 = (h + l + c) / 3.0
    day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
    n = len(c); vwap = np.zeros(n); cum = 0.0; cnt = 0.0; cur = day[0]
    for i in range(n):
        if day[i] != cur:
            cur = day[i]; cum = 0.0; cnt = 0.0
        cum += tp3[i]; cnt += 1; vwap[i] = cum / cnt
    return vwap


def _pday(h, l, tm):
    day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
    n = len(h); pdh = np.full(n, np.nan); pdl = np.full(n, np.nan)
    cur = day[0]; ch = h[0]; cl_ = l[0]; ph = pl = np.nan
    for i in range(n):
        if day[i] != cur:
            ph, pl = ch, cl_; cur = day[i]; ch = h[i]; cl_ = l[i]
        else:
            ch = max(ch, h[i]); cl_ = min(cl_, l[i])
        pdh[i], pdl[i] = ph, pl
    return pdh, pdl


def run(h, l, c, tm, cost, pt, kind, rr, max_hold=48, tol_pts=150):
    atr = R.atr(h, l, c); news = _news_mask(atr)
    vwap = _session_vwap(h, l, c, tm) if kind == "vwap" else None
    pdh, pdl = _pday(h, l, tm) if kind == "pday" else (None, None)
    n = len(c); tr = []; i = 210
    while i < n - 1:
        if not news[i]:                                    # เลี่ยงข่าว (vol spike)
            i += 1; continue
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        px = float(c[i]); pxp = float(c[i - 1]); d = 0
        if kind == "vwap" and av > 0:                      # revert เข้าหา VWAP เมื่อห่าง (จุดสำคัญ=VWAP)
            dist = (px - vwap[i]) / pt
            if dist > tol_pts:
                d = -1
            elif dist < -tol_pts:
                d = 1
        elif kind == "pday":                               # bounce ที่ prior-day H/L (แนวสำคัญ)
            H, L = pdh[i], pdl[i]
            if H == H and abs(px - L) <= tol_pts * pt and px > L:
                d = 1
            elif H == H and abs(px - H) <= tol_pts * pt and px < H:
                d = -1
        elif kind == "round":                              # bounce ที่ round-$25 (แนว options/psych)
            grid = 25.0; near = round(px / grid) * grid
            if abs(px - near) <= tol_pts * pt:
                d = 1 if px >= near else -1                 # เหนือ=support bounce / ใต้=resistance
        elif kind == "microbrk":                           # micro-Donchian break (จุด breakout)
            hh = float(h[i - 12:i].max()); ll = float(l[i - 12:i].min())
            d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, SL_POINTS, rr, pt, cost, max_hold)
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
    g = (__import__("config").SYMBOL)
    from connectors.pair_collector import _broker_map
    g = (_broker_map() or {}).get("XAUUSD", g)
    cost = (_sc.cost_pips("XAUUSD") if _sc else None) or 30.0
    print("\n=== SCALP KEY-LEVELS (spec: SL=%dpt · RR1.5-3 · WR≥50%% · เลี่ยงข่าว) · causal · cost-adj · OOS ===" % SL_POINTS)
    print("เก็บ = WR≥50%% + exp_R>0 + OOS>0 (สเปคเข้ม). cost=%.0fpt = %.0f%%ของ SL\n" % (cost, cost / SL_POINTS * 100))
    pt = float(mt5.symbol_info(g).point)
    winners = []
    for tfn, tf, mh in [("M15", mt5.TIMEFRAME_M15, 48), ("M5", mt5.TIMEFRAME_M5, 96)]:
        r = mt5.copy_rates_from_pos(g, tf, 0, 60000)
        if r is None or len(r) < 2000:
            print("%s ข้อมูลไม่พอ" % tfn); continue
        h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float); tm = r["time"]
        print("── GOLD %s (bars=%d) ──" % (tfn, len(c)))
        for kind in ("vwap", "pday", "round", "microbrk"):
            for rr in (1.5, 2.0, 3.0):
                s = _st(run(h, l, c, tm, cost, pt, kind, rr, max_hold=mh))
                if not s:
                    print("  %-8s rr%.1f  n<30" % (kind, rr)); continue
                n, wr, ex, t, oe = s
                spec = wr >= 50 and ex > 0 and oe > 0 and n >= MIN_N
                fl = "✅ผ่านสเปค" if spec else ("+EV" if ex > 0 else "−")
                if spec:
                    winners.append((tfn, kind, rr, wr, ex, t, oe))
                print("  %-8s rr%.1f  n=%5d WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (kind, rr, n, wr, ex, t, oe, fl))
    print("\n=== ผ่านสเปค (WR≥50%% + exp_R>0 + OOS>0, n≥%d) ===" % MIN_N)
    if winners:
        for w in sorted(winners, key=lambda z: -z[4]):
            print("  %-4s %-8s rr%.1f WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f" % w)
    else:
        print("  ไม่มีตัวผ่านสเปค — SL แคบ+RR≥1.5+WR≥50%% พร้อมกัน = ไม่มีในตลาดนี้ (ตรงหลักฐาน scalp −EV)")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
