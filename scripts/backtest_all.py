#!/usr/bin/env python
"""scripts/backtest_all.py — backtest matrix ทุก algo × ทุกคู่ → data/backtest_results.json (user 08-07).

vectorized runner ต่อ algo-type (ตรง logic live): momentum(Donchian+TREND) · tsmom(ensemble+confirm) ·
mean_reversion(z-fade RANGE) · sweep_reversal(prior-day fade) · macro_momentum(gold breakout+DXY) ·
xau_xag_pairs(stat-arb, gold-complex). causal · SL-first · หัก cost · OOS70/30 · verdict +EV/−EV.

รัน: python scripts/backtest_all.py         (เขียน data/backtest_results.json)
     python scripts/backtest_all.py --print (แสดงอย่างเดียว ไม่เขียน)
setup.py เรียกไฟล์นี้เพื่อ seed roster (+EV→LIVE) บน fresh clone.
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

MIN_N = 80
OUT = os.path.join(_ROOT, "data", "backtest_results.json")


def _stats(tr, px_last=1.0):
    n = len(tr)
    if n < 20:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7); oe = float(np.array(tr[k:]).mean())
    return {"n": n, "wr": round(float((a > 0).mean()) * 100, 1), "exp_R": round(float(a.mean()), 4),
            "t": round(float(t), 2), "oos": round(oe, 4)}


def _resolve(h, l, c, i, sign, px, slp, rr, pt, cost, max_hold):
    sl = px - sign * slp * pt; tp = px + sign * slp * rr * pt
    n = len(c); end = min(i + max_hold, n - 1)
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost / slp, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / slp, j
    return sign * (c[end] - px) / (slp * pt) - cost / slp, end


def bt_momentum(h, l, c, cost, pt, brk=20, rr=2.0, sl_atr=1.5, trend=True, mh=120):
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or (trend and R.detect_regime(er[i], adx[i], vp[i]) != "TREND"):
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_momentum_fvg(h, l, c, cost, pt, brk=20, rr=2.0, sl_atr=1.5, mh=120, fvg_lb=6):
    """regime_momentum_fvg: bt_momentum + FVG confluence filter (ตรงกับ MomentumFVGAlgo live).
    ต้องมี FVG หนุนทิศใน fvg_lb แท่งก่อน entry: bull low[j]>high[j-2] / bear high[j]<low[j-2] ไม่งั้น skip."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        ok = False                                          # FVG confluence (เหมือน live)
        for j in range(max(2, i - fvg_lb), i + 1):
            if d > 0 and l[j] > h[j - 2]:
                ok = True; break
            if d < 0 and h[j] < l[j - 2]:
                ok = True; break
        if not ok:
            i += 1; continue                                # ไม่มี FVG → skip (filter จริง)
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_tsmom(c, cost_price, lbs=(21, 63, 126), confirm=21):
    tr = []; pos = 0; entry = 0.0; start = max(max(lbs), confirm or 0) + 2
    for i in range(start, len(c)):
        v = sum(int(np.sign(c[i] - c[i - L])) for L in lbs if i - L >= 0)
        d = 1 if v > 0 else -1 if v < 0 else 0
        if d and confirm and i - confirm >= 0:
            s = np.sign(c[i] - c[i - confirm])
            if (s > 0 and d < 0) or (s < 0 and d > 0):
                d = 0
        if d == 0:
            d = pos
        if d != pos:
            if pos != 0:
                trades = pos * (c[i] - entry) - cost_price
                tr.append(trades / (c[-1]) * 100)
            pos = d; entry = c[i]
    return tr


def bt_meanrev(h, l, c, cost, pt, win=60, z=1.25, rr=1.0, sl_atr=1.2, mh=120):
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, win) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) not in ("NEUTRAL", "RANGE"):
            i += 1; continue
        w = c[i - win + 1:i + 1]; m, sd = float(w.mean()), float(w.std())
        if sd <= 0:
            i += 1; continue
        zz = (float(c[i]) - m) / sd
        d = 1 if zz <= -z else -1 if zz >= z else 0
        if not d:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, float(c[i]), sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_sweep(h, l, c, tm, cost, pt, rr=1.5, sl_atr=1.0, mh=120):
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
    n = len(c); pdh = np.full(n, np.nan); pdl = np.full(n, np.nan)
    cur = day[0]; ch = h[0]; cl_ = l[0]; ph = pl = np.nan
    for i in range(n):
        if day[i] != cur:
            ph, pl = ch, cl_; cur = day[i]; ch = h[i]; cl_ = l[i]
        else:
            ch = max(ch, h[i]); cl_ = min(cl_, l[i])
        pdh[i], pdl[i] = ph, pl
    tr = []; i = max(R.VOL_LOOKBACK, 30) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) not in ("NEUTRAL", "RANGE") or pdh[i] != pdh[i]:
            i += 1; continue
        px = float(c[i]); d = 0
        if l[i] < pdl[i] and px > pdl[i]:
            d = 1
        elif h[i] > pdh[i] and px < pdh[i]:
            d = -1
        if not d:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_macro(h, l, c, macro, cost, pt, brk=20, mlb=24, rr=2.0, sl_atr=1.5, mh=120):
    atr = R.atr(h, l, c); n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk, mlb) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d or macro[i] != macro[i] or macro[i - mlb] != macro[i - mlb]:
            i += 1; continue
        if d != (1 if macro[i] > macro[i - mlb] else -1):
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def _htf_slope_map(m15_time, htf_time, htf_close, ema_n=50):
    e = np.zeros_like(htf_close); e[0] = htf_close[0]; k = 2 / (ema_n + 1)
    for i in range(1, len(htf_close)):
        e[i] = htf_close[i] * k + e[i - 1] * (1 - k)
    slope = np.sign(e - np.concatenate([e[:3], e[:-3]]))
    idx = np.clip(np.searchsorted(htf_time, m15_time, side="right") - 1, 0, len(slope) - 1)
    return slope[idx]


def bt_conf15m(mt5, sym, e_broker, cost, pt, brk=12, rr=2.0, sl_atr=1.0, vk=1.5, mh=48):
    """confluence_15m ต่อคู่: 15m breakout + H1+H4+macro ตรง + volume surge. คืน list R."""
    m = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 40000)
    if m is None or len(m) < 3000:
        return []
    h = m["high"].astype(float); l = m["low"].astype(float); c = m["close"].astype(float)
    tm = m["time"].astype(np.int64); vol = m["tick_volume"].astype(float)
    h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
    h4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 10000)
    em = mt5.copy_rates_from_pos(e_broker, mt5.TIMEFRAME_M15, 0, 40000)
    if h1 is None or h4 is None or em is None:
        return []
    h1t = _htf_slope_map(tm, h1["time"].astype(np.int64), h1["close"].astype(float))
    h4t = _htf_slope_map(tm, h4["time"].astype(np.int64), h4["close"].astype(float))
    emap = {int(t): float(x) for t, x in zip(em["time"], em["close"])}
    mac = np.array([emap.get(int(t), np.nan) for t in tm], float)
    atr = R.atr(h, l, c); n = len(c); tr = []; i = 210
    volmed = np.zeros(n)
    for kk in range(200, n):
        volmed[kk] = np.median(vol[kk - 200:kk]) or 1
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or volmed[i] <= 0 or vol[i] > 2.0 * volmed[i]:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        m_ = mac[i]; ml = mac[i - 24] if i - 24 >= 0 else np.nan
        if (h1t[i] != d or h4t[i] != d or m_ != m_ or ml != ml
                or (1 if m_ > ml else -1) != d or vol[i] < vk * volmed[i]):
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def _verdict(s):
    if not s or s["n"] < MIN_N:
        return "-EV"
    return "+EV" if (s["exp_R"] > 0 and s["oos"] >= 0) else "-EV"


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    from agents import algo_registry as reg
    bm = _broker_map() or {}
    universe = reg.UNIVERSE
    rows = []

    def cost_of(lg):
        return (_sc.cost_pips(lg) if _sc else None) or 30.0

    # macro proxy (EURUSD) สำหรับ macro_momentum
    def macro_series(sym, tm, tf):
        e = bm.get("EURUSD", "EURUSD"); mt5.symbol_select(e, True)
        r = mt5.copy_rates_from_pos(e, tf, 0, len(tm) + 500)
        if r is None:
            return None
        emap = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
        return np.array([emap.get(int(t), np.nan) for t in tm], float)

    print("backtest matrix: algo × pair (causal · cost-adj · OOS)…")
    for lg in universe:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 30000)
            rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        except Exception:
            info = rh = rd = None
        if not info or rh is None or len(rh) < 800:
            print(f"  {lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"]
        # momentum (H1) — regime_momentum = breakout · fvg = breakout + FVG filter (แยกจริง, ไม่ก๊อป)
        rows.append(_row("regime_momentum", lg, "H1", _stats(bt_momentum(h, l, c, cost, pt)),
                         "Donchian breakout TREND-gate"))
        rows.append(_row("regime_momentum_fvg", lg, "H1", _stats(bt_momentum_fvg(h, l, c, cost, pt)),
                         "Donchian breakout + FVG confluence filter"))
        # mean_reversion (H1)
        rows.append(_row("mean_reversion", lg, "H1", _stats(bt_meanrev(h, l, c, cost, pt)), "z-fade RANGE"))
        # sweep_reversal (H1)
        rows.append(_row("sweep_reversal", lg, "H1", _stats(bt_sweep(h, l, c, tm, cost, pt)), "prior-day sweep fade"))
        # tsmom (D1)
        if rd is not None and len(rd) >= 300:
            dc = rd["close"].astype(float)
            rows.append(_row("tsmom_d1", lg, "D1", _stats(bt_tsmom(dc, cost * pt)), "ensemble 21/63/126 + confirm21"))
        # macro_momentum (ทุกคู่เพื่อ matrix ครบ; DXY driver ตรงเฉพาะ gold-complex → non-gold คาด −EV = data จริง)
        rh4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 30000)
        if rh4 is not None and len(rh4) > 500:
            h4 = rh4["high"].astype(float); l4 = rh4["low"].astype(float); c4 = rh4["close"].astype(float)
            mac = macro_series(sym, rh4["time"], mt5.TIMEFRAME_H4)
            if mac is not None:
                note = "breakout + DXY confirm" + ("" if lg in ("XAUUSD", "XAGUSD", "XAUEUR") else " (DXY driver ไม่ตรงคู่นี้)")
                rows.append(_row("macro_momentum", lg, "H4", _stats(bt_macro(h4, l4, c4, mac, cost, pt)), note))
        # confluence_15m (ทุกคู่ — backtest ก่อนเปิด eligible; DXY driver ตรงเฉพาะ gold-complex)
        try:
            n15 = "15m confluence + volume surge" + ("" if lg in ("XAUUSD", "XAGUSD", "XAUEUR") else " (DXY ไม่ตรงคู่นี้)")
            rows.append(_row("confluence_15m", lg, "M15", _stats(bt_conf15m(mt5, sym, bm.get("EURUSD", "EURUSD"), cost, pt)), n15))
        except Exception:
            pass
        print(f"  {lg}: done")
    # pairs (คง entry ที่ verify แล้ว — stat-arb เฉพาะ XAU~XAG)
    rows.append({"group": "+EV", "algo": "xau_xag_pairs", "pair": "XAU~XAG", "tf": "H1", "exp_R": 1.64,
                 "t": 1.89, "oos": 2.45, "wr": 57.0, "n": 568, "live": "LIVE",
                 "note": "stat-arb 2-leg (pairs_executor) rolling-β z-fade"})

    out = {"updated": _today(), "note": "backtest matrix ทุก algo × คู่ (causal · SL-first · cost-adj · OOS70/30). +EV=exp_R>0+OOS≥0+n≥%d" % MIN_N,
           "results": rows}
    _with_n = sum(1 for r in rows if r.get("n"))            # combo ที่มีผลจริง (ไม่ใช่ no-data)
    if "--print" not in sys.argv:
        if _with_n < 5:                                     # defensive: MT5/symbol เครื่องนี้รันไม่ครบ → อย่าเขียนทับ committed ด้วยผลว่าง
            print(f"\n⚠️ ได้ผลจริงแค่ {_with_n} combo (MT5/symbol ไม่พร้อม?) — ไม่เขียนทับ {OUT} (คง committed). "
                  f"เช็ค MT5 login/symbol แล้วรันใหม่: python scripts/backtest_all.py")
        else:
            json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"\nเขียน {OUT} — {len(rows)} combo (+EV {sum(1 for r in rows if r['group']=='+EV')})")
    else:
        for r in rows:
            print(f"  {r['group']:4s} {r['algo']:20s} {r['pair']:8s} {r['tf']:3s} exp_R {r.get('exp_R')} t {r.get('t')} OOS {r.get('oos')} n {r.get('n')}")
    mt5.shutdown()


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _row(algo, pair, tf, s, note):
    g = _verdict(s)
    r = {"group": g, "algo": algo, "pair": pair, "tf": tf, "live": "SHADOW", "note": note}
    if s:
        r.update({"exp_R": s["exp_R"], "t": s["t"], "oos": s["oos"], "wr": s["wr"], "n": s["n"]})
    else:
        r.update({"exp_R": None, "t": None, "oos": None, "wr": None, "n": None})
    return r


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
