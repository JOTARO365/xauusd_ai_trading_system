#!/usr/bin/env python
"""scripts/m15_scalp_backtest.py — เทส M15 scalping หลาย hypothesis หา +EV ก่อน live.

user ขอ algo scalp M15 (algo ปัจจุบันเป็น swing เข้าช้า/พลาดจุด). แต่ live-money → backtest ก่อนเสมอ.
hypothesis: ORB (opening-range breakout) · momentum-continuation (M15 Donchian) · mean-revert-scalp (z-fade)
· RSI-extreme · VWAP-reversion. แต่ละตัวหลาย variant.

กติกา quant (เหมือน sr_fade/optwall): causal (signal@i แท่งปิด, resolve i+1..), **SL-first** (แตะ SL ก่อน TP ในแท่งเดียว = SL),
หัก cost จริง (cost_pips), non-overlap, OOS 70/30, t-stat, MIN_N=100. ⚠️ ลองหลาย variant = multiple-testing:
ต้อง t>2 + OOS>0 + n≥100 ถึงเชื่อ (เผื่อ deflate). cost เป็นตัวฆ่า scalp (TP เล็ก).

รัน: python scripts/m15_scalp_backtest.py            # ทอง M15
     python scripts/m15_scalp_backtest.py --all      # +XAG/XAUEUR
"""
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

MIN_N = 100
MAX_HOLD = 48          # M15: 48 แท่ง = 12 ชม (scalp ปิดในวัน)


def _stats(tr):
    n = len(tr)
    if not n:
        return {"n": 0}
    a = np.array(tr, float); sd = float(a.std(ddof=1)) if n > 1 else 0.0
    return {"n": n, "wr": round(float((a > 0).mean()) * 100, 1), "exp_R": round(float(a.mean()), 4),
            "sum_R": round(float(a.sum()), 1), "t": round(float(a.mean()) / (sd / math.sqrt(n)), 2) if sd else 0.0}


def _rep(label, tr):
    s = _stats(tr)
    if not s["n"]:
        print(f"{label:28s} n=0"); return
    k = int(len(tr) * 0.7); oos = _stats(tr[k:])
    fl = "PASS" if (s["n"] >= MIN_N and s["exp_R"] > 0 and s["t"] > 2 and oos.get("exp_R", -1) > 0) else "—"
    print(f"{label:28s} n={s['n']:4d} WR {s['wr']:5}% exp_R {s['exp_R']:+.4f} t {s['t']:+.2f} "
          f"sumR {s['sum_R']:+7.1f} | OOS {oos.get('exp_R','—')} [{fl}]")


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = np.zeros_like(c); rd = np.zeros_like(c); ru[:n] = up[:n].mean(); rd[:n] = dn[:n].mean()
    for i in range(n, len(c)):
        ru[i] = (ru[i - 1] * (n - 1) + up[i]) / n; rd[i] = (rd[i - 1] * (n - 1) + dn[i]) / n
    rs = ru / np.where(rd == 0, 1e-9, rd)
    return 100 - 100 / (1 + rs)


def _resolve(h, l, c, i, sign, px, sl_pips, rr, point, cost, max_hold):
    """SL-first resolve จาก i+1. คืน (R, exit_index)."""
    sl = px - sign * sl_pips * point; tp = px + sign * sl_pips * rr * point
    n = len(c); end = min(i + max_hold, n - 1)
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost / sl_pips, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / sl_pips, j
    return sign * (c[end] - px) / (sl_pips * point) - cost / sl_pips, end


# ── hypotheses: แต่ละตัวคืน list ของ R (non-overlap) ────────────────────────────
def h_momentum(h, l, c, tm, cost, point, brk=20, rr=1.5, sl_atr=1.0, trend_filter=True, max_hold=MAX_HOLD):
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        if trend_filter and R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            i += 1; continue
        hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min()); px = float(c[i])
        d = "BUY" if px > hh else "SELL" if px < ll else None
        if not d:
            i += 1; continue
        sign = 1 if d == "BUY" else -1; sl_pips = sl_atr * av / point
        if sl_pips <= 0:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, sign, px, sl_pips, rr, point, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def h_meanrev(h, l, c, tm, cost, point, win=40, z=1.5, rr=1.0, sl_atr=1.2, max_hold=MAX_HOLD):
    atr = R.atr(h, l, c); n = len(c); tr = []; i = max(R.VOL_LOOKBACK, win) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        w = c[i - win + 1:i + 1]; m, sd = float(w.mean()), float(w.std())
        if av <= 0 or sd <= 0:
            i += 1; continue
        px = float(c[i]); zz = (px - m) / sd
        d = "BUY" if zz <= -z else "SELL" if zz >= z else None
        if not d:
            i += 1; continue
        sign = 1 if d == "BUY" else -1; sl_pips = sl_atr * av / point
        r, ei = _resolve(h, l, c, i, sign, px, sl_pips, rr, point, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def h_rsi(h, l, c, tm, cost, point, lo=30, hi=70, rr=1.0, sl_atr=1.2, max_hold=MAX_HOLD):
    atr = R.atr(h, l, c); rsi = _rsi(c); n = len(c); tr = []; i = max(R.VOL_LOOKBACK, 20) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); d = "BUY" if rsi[i] <= lo else "SELL" if rsi[i] >= hi else None
        if not d:
            i += 1; continue
        sign = 1 if d == "BUY" else -1; sl_pips = sl_atr * av / point
        r, ei = _resolve(h, l, c, i, sign, px, sl_pips, rr, point, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def h_vwap(h, l, c, tm, cost, point, k=1.5, rr=1.0, sl_atr=1.2, max_hold=MAX_HOLD):
    """fade ระยะห่างจาก session-VWAP (reset ทุกวัน UTC). ไกล +k×ATR = SELL, ต่ำ −k×ATR = BUY."""
    atr = R.atr(h, l, c); n = len(c); tr = []
    tp3 = (h + l + c) / 3.0
    day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
    cum_pv = 0.0; cum_v = 0.0; cur = day[0]; vwap = np.zeros(n)
    for k2 in range(n):
        if day[k2] != cur:
            cur = day[k2]; cum_pv = 0.0; cum_v = 0.0
        cum_pv += tp3[k2]; cum_v += 1.0; vwap[k2] = cum_pv / cum_v
    i = R.VOL_LOOKBACK + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); dist = (px - vwap[i]) / av
        d = "SELL" if dist >= k else "BUY" if dist <= -k else None
        if not d:
            i += 1; continue
        sign = 1 if d == "BUY" else -1; sl_pips = sl_atr * av / point
        r, ei = _resolve(h, l, c, i, sign, px, sl_pips, rr, point, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def h_orb(h, l, c, tm, cost, point, open_h=7, orb_bars=4, rr=1.5, sl_atr=0.0, max_hold=MAX_HOLD):
    """opening-range breakout: หลัง session-open (UTC open_h) ตั้งกรอบ orb_bars แท่งแรก, เบรก = เข้า.
    SL = อีกฝั่งของกรอบ (sl_atr=0) หรือ sl_atr×ATR. เข้าครั้งเดียว/วัน/ทิศ."""
    atr = R.atr(h, l, c); n = len(c); tr = []
    hh = np.array([datetime.fromtimestamp(int(t), timezone.utc).hour for t in tm])
    day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
    i = R.VOL_LOOKBACK + 2
    done_day = {}
    while i < n - 1:
        # หา index แท่งแรกของ session-open วันนี้
        if hh[i] < open_h:
            i += 1; continue
        dkey = int(day[i])
        if done_day.get(dkey):
            i += 1; continue
        # กรอบ = orb_bars แท่งตั้งแต่ open_h ของวันนี้
        s = i
        while s > 0 and day[s - 1] == dkey and hh[s - 1] >= open_h:
            s -= 1
        if i - s + 1 < orb_bars:                       # ยังตั้งกรอบไม่ครบ
            i += 1; continue
        rng_h = float(h[s:s + orb_bars].max()); rng_l = float(l[s:s + orb_bars].min())
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        px = float(c[i]); d = "BUY" if px > rng_h else "SELL" if px < rng_l else None
        if not d:
            i += 1; continue
        sign = 1 if d == "BUY" else -1
        sl_pips = (sl_atr * av / point) if sl_atr > 0 else (abs(px - (rng_l if sign > 0 else rng_h)) / point)
        if sl_pips <= 0:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, sign, px, sl_pips, rr, point, cost, max_hold)
        tr.append(r); done_day[dkey] = True; i = ei + 1
    return tr


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    print("\n=== M15 scalp backtest · causal · SL-first · cost-adj · OOS70/30 · MIN_N=100 ===")
    print("PASS = n≥100 + exp_R>0 + t>2 + OOS>0   (⚠️ multiple-testing: หลาย variant ต้อง deflate)\n")
    syms = ["XAUUSD", "XAGUSD", "XAUEUR"] if "--all" in sys.argv else ["XAUUSD"]
    bmap = {}
    if "--all" in sys.argv:
        from connectors.pair_collector import _broker_map
        bmap = _broker_map() or {}
    for logical in syms:
        sym = bmap.get(logical, logical) if bmap else __import__("config").SYMBOL
        try:
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 60000)
            info = mt5.symbol_info(sym)
        except Exception:
            r = info = None
        if r is None or len(r) < 2000 or not info:
            print(f"{logical} M15 ข้อมูลไม่พอ"); continue
        h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float); tm = r["time"]
        cost = (_sc.cost_pips(logical) if _sc else None) or 30.0
        pt = float(info.point); atr = R.atr(h, l, c); med_atr = float(np.nanmedian(atr[-1000:])) / pt
        print(f"── {logical}  bars={len(c)}  cost={cost}p  M15 medATR={med_atr:.0f}p  cost/ATR={cost/med_atr*100:.0f}% ──")
        # momentum continuation
        for nm, kw in [("mom brk20 rr1.5 trend", dict(brk=20, rr=1.5)),
                       ("mom brk20 rr2 trend", dict(brk=20, rr=2.0)),
                       ("mom brk20 rr1.5 NOfilter", dict(brk=20, rr=1.5, trend_filter=False)),
                       ("mom brk10 rr2 trend", dict(brk=10, rr=2.0))]:
            _rep("  " + nm, h_momentum(h, l, c, tm, cost, pt, **kw))
        # mean-revert scalp
        for nm, kw in [("mr z1.5 rr1", dict(z=1.5, rr=1.0)),
                       ("mr z2 rr1", dict(z=2.0, rr=1.0)),
                       ("mr z2 rr1.5", dict(z=2.0, rr=1.5))]:
            _rep("  " + nm, h_meanrev(h, l, c, tm, cost, pt, **kw))
        # RSI extreme
        for nm, kw in [("rsi 30/70 rr1", dict(rr=1.0)),
                       ("rsi 25/75 rr1.5", dict(lo=25, hi=75, rr=1.5))]:
            _rep("  " + nm, h_rsi(h, l, c, tm, cost, pt, **kw))
        # VWAP reversion
        for nm, kw in [("vwap k1.5 rr1", dict(k=1.5, rr=1.0)),
                       ("vwap k2 rr1", dict(k=2.0, rr=1.0))]:
            _rep("  " + nm, h_vwap(h, l, c, tm, cost, pt, **kw))
        # ORB
        for nm, kw in [("orb7 4bar rr1.5", dict(open_h=7, orb_bars=4, rr=1.5)),
                       ("orb13(NY) 4bar rr1.5", dict(open_h=13, orb_bars=4, rr=1.5)),
                       ("orb7 4bar rr2", dict(open_h=7, orb_bars=4, rr=2.0))]:
            _rep("  " + nm, h_orb(h, l, c, tm, cost, pt, **kw))
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
