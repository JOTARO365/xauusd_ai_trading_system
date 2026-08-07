#!/usr/bin/env python
"""scripts/research_quant.py — research ทฤษฎี quant ใหม่ แก้ 2 ปัญหา (user 08-07):
(1) ไม่เข้า ณ จุดสำคัญ → key-level breakout (prior-day/week H/L)
(2) เข้าสวน sentiment → macro-aligned (DXY/EURUSD = sentiment เชิงโครงสร้าง, backtest ได้; LLM sentiment ไม่มี history)

ทฤษฎีที่เทส:
  A. macro-beta       : เทรดทองตามทิศ DXY-proxy (EURUSD up=gold BUY) ล้วน — cross-asset lead
  B. macro-mom        : Donchian breakout + EURUSD ยืนยันทิศ (ไม่สวน macro)
  C. pday-break       : break prior-day H/L (จุดสำคัญ) ±macro filter
  D. pweek-break      : break prior-week H/L ±macro filter
  E. squeeze-break    : BB-width ต่ำ (บีบ) → breakout (เข้าจังหวะ expansion)

causal · SL-first · หัก cost · OOS70/30 · t-stat · MIN_N. เก็บ +EV. EURUSD align ตาม timestamp ทอง.
รัน: python scripts/research_quant.py
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


def _rep(label, tr):
    s = _st(tr)
    if not s:
        print("  %-26s n<20" % label); return None
    n, wr, ex, sm, t, oe = s
    fl = "✅" if ex > 0 and oe > 0 and n >= MIN_N else ("+EV" if ex > 0 and oe >= 0 and n >= MIN_N else "−")
    print("  %-26s n=%4d WR%5.1f%% exp_R%+.4f t%+.2f sumR%+7.1f OOS%+.4f %s" % (label, n, wr, ex, t, sm, oe, fl))
    return (label, ex, t, oe, fl) if fl != "−" else None


def _resolve(h, l, c, i, sign, px, slp, rr, pt, cost, max_hold):
    sl = px - sign * slp * pt; tp = px + sign * slp * rr * pt
    n = len(c); end = min(i + max_hold, n - 1)
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost / slp, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / slp, j
    return sign * (c[end] - px) / (slp * pt) - cost / slp, end


def _daily_levels(hi, lo, tm):
    """prior-day H/L ต่อ index (คืน array pdh,pdl ที่ index i = H/L ของวันก่อนหน้า i)."""
    from datetime import datetime, timezone
    day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
    n = len(hi); pdh = np.full(n, np.nan); pdl = np.full(n, np.nan)
    cur = day[0]; ch = hi[0]; cl_ = lo[0]; prev_h = prev_l = np.nan
    for i in range(n):
        if day[i] != cur:
            prev_h, prev_l = ch, cl_; cur = day[i]; ch = hi[i]; cl_ = lo[i]
        else:
            ch = max(ch, hi[i]); cl_ = min(cl_, lo[i])
        pdh[i], pdl[i] = prev_h, prev_l
    return pdh, pdl


def _week_levels(hi, lo, tm):
    from datetime import datetime, timezone
    wk = np.array([datetime.fromtimestamp(int(t), timezone.utc).isocalendar()[:2] for t in tm])
    n = len(hi); pwh = np.full(n, np.nan); pwl = np.full(n, np.nan)
    cur = tuple(wk[0]); ch = hi[0]; cl_ = lo[0]; prev_h = prev_l = np.nan
    for i in range(n):
        if tuple(wk[i]) != cur:
            prev_h, prev_l = ch, cl_; cur = tuple(wk[i]); ch = hi[i]; cl_ = lo[i]
        else:
            ch = max(ch, hi[i]); cl_ = min(cl_, lo[i])
        pwh[i], pwl[i] = prev_h, prev_l
    return pwh, pwl


def run_macro_beta(h, l, c, macro, cost, pt, lb=24, rr=1.5, sl_atr=1.5, max_hold=120):
    """เทรดทองตามทิศ macro-proxy momentum (EURUSD up lb บาร์ = gold BUY). enter เมื่อทิศเปลี่ยน."""
    atr = R.atr(h, l, c); n = len(c); tr = []; i = max(R.VOL_LOOKBACK, lb) + 2; last = 0
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        m = macro[i]; mlag = macro[i - lb]
        if av <= 0 or m != m or mlag != mlag:
            i += 1; continue
        d = 1 if m > mlag else -1 if m < mlag else 0
        if d == 0 or d == last:
            i += 1; continue
        last = d; px = float(c[i]); slp = sl_atr * av / pt
        r, ei = _resolve(h, l, c, i, d, px, slp, rr, pt, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def run_macro_mom(h, l, c, macro, cost, pt, brk=20, mlb=24, rr=2.0, sl_atr=1.5, max_hold=120, trend=True):
    """Donchian breakout + macro ยืนยันทิศ (BUY ต้อง macro ขึ้น). trend=TREND-gate."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk, mlb) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or (trend and R.detect_regime(er[i], adx[i], vp[i]) != "TREND"):
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        m = macro[i]; mlag = macro[i - mlb]
        if m != m or mlag != mlag:
            i += 1; continue
        md = 1 if m > mlag else -1                          # macro direction
        if d != md:                                         # breakout สวน macro → ข้าม (ไม่สวน sentiment โครงสร้าง)
            i += 1; continue
        slp = sl_atr * av / pt
        r, ei = _resolve(h, l, c, i, d, px, slp, rr, pt, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def run_level_break(h, l, c, lvlH, lvlL, macro, cost, pt, mlb=24, rr=2.0, sl_atr=1.5, max_hold=120, macro_filter=False):
    """break prior-day/week H (BUY) / L (SELL) = จุดสำคัญ. macro_filter → ต้องไม่สวน macro."""
    atr = R.atr(h, l, c); n = len(c); tr = []; i = max(R.VOL_LOOKBACK, mlb) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        H, L = lvlH[i], lvlL[i]
        if av <= 0 or H != H or L != L:
            i += 1; continue
        px = float(c[i]); pxp = float(c[i - 1])
        d = 1 if (pxp <= H < px) else -1 if (pxp >= L > px) else 0   # เพิ่งทะลุระดับ (cross)
        if not d:
            i += 1; continue
        if macro_filter:
            m = macro[i]; mlag = macro[i - mlb]
            if m == m and mlag == mlag and d != (1 if m > mlag else -1):
                i += 1; continue
        slp = sl_atr * av / pt
        r, ei = _resolve(h, l, c, i, d, px, slp, rr, pt, cost, max_hold)
        tr.append(r); i = ei + 1
    return tr


def run_squeeze(h, l, c, cost, pt, win=20, wpct=0.25, rr=2.0, sl_atr=1.5, max_hold=120):
    """BB-width percentile ต่ำ (บีบ) → breakout ทิศที่ราคาออกจากกรอบ (เข้าจังหวะ expansion = จุดสำคัญ)."""
    atr = R.atr(h, l, c); n = len(c); tr = []
    ma = np.full(n, np.nan); width = np.full(n, np.nan)
    for i in range(win, n):
        w = c[i - win + 1:i + 1]; m = w.mean(); sd = w.std()
        ma[i] = m; width[i] = (2 * sd) / m if m else np.nan
    i = max(R.VOL_LOOKBACK, win) + 60
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        wl = width[i - 60:i + 1]
        if av <= 0 or width[i] != width[i] or np.isnan(wl).all():
            i += 1; continue
        thr = np.nanpercentile(wl, wpct * 100)
        if width[i] > thr:                                  # ไม่บีบ → ข้าม
            i += 1; continue
        px = float(c[i]); upper = ma[i] * (1 + width[i] / 2); lower = ma[i] * (1 - width[i] / 2)
        d = 1 if px > upper else -1 if px < lower else 0
        if not d:
            i += 1; continue
        slp = sl_atr * av / pt
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
    bmap = _broker_map() or {}
    gold = bmap.get("XAUUSD", __import__("config").SYMBOL)
    eur = bmap.get("EURUSD", "EURUSD")
    print("\n=== RESEARCH: quant theories ใหม่ (macro-aligned + key-level + squeeze) · causal · cost-adj · OOS70/30 ===")
    print("แก้: (1) เข้า ณ จุดสำคัญ (level breakout) (2) ไม่สวน macro/sentiment (DXY-proxy=EURUSD filter). เก็บ +EV\n")
    keep = []
    for tfn, tf in [("H4", mt5.TIMEFRAME_H4), ("H1", mt5.TIMEFRAME_H1)]:
        mt5.symbol_select(gold, True); mt5.symbol_select(eur, True)
        rg = mt5.copy_rates_from_pos(gold, tf, 0, 60000)
        re = mt5.copy_rates_from_pos(eur, tf, 0, 60000)
        if rg is None or re is None or len(rg) < 1000:
            print("%s ข้อมูลไม่พอ" % tfn); continue
        h = rg["high"].astype(float); l = rg["low"].astype(float); c = rg["close"].astype(float); tm = rg["time"]
        # align EURUSD close ตาม timestamp ทอง
        emap = {int(t): float(x) for t, x in zip(re["time"], re["close"])}
        macro = np.array([emap.get(int(t), np.nan) for t in tm], float)
        cov = np.mean(~np.isnan(macro)) * 100
        pt = float(mt5.symbol_info(gold).point); cost = (_sc.cost_pips("XAUUSD") if _sc else None) or 30.0
        pdh, pdl = _daily_levels(h, l, tm); pwh, pwl = _week_levels(h, l, tm)
        print("── GOLD %s (cost=%.0fp · EURUSD align %.0f%%) ──" % (tfn, cost, cov))
        keep += [x for x in [
            _rep("A macro-beta lb24 rr1.5", run_macro_beta(h, l, c, macro, cost, pt)),
            _rep("B macro-mom brk20 rr2", run_macro_mom(h, l, c, macro, cost, pt)),
            _rep("B macro-mom noTREND", run_macro_mom(h, l, c, macro, cost, pt, trend=False)),
            _rep("C pday-break rr2", run_level_break(h, l, c, pdh, pdl, macro, cost, pt)),
            _rep("C pday-break +macro", run_level_break(h, l, c, pdh, pdl, macro, cost, pt, macro_filter=True)),
            _rep("D pweek-break rr2", run_level_break(h, l, c, pwh, pwl, macro, cost, pt)),
            _rep("D pweek-break +macro", run_level_break(h, l, c, pwh, pwl, macro, cost, pt, macro_filter=True)),
            _rep("E squeeze-break rr2", run_squeeze(h, l, c, cost, pt)),
        ] if x]
        keep = [(tfn + " " + k[0], *k[1:]) for k in [] ] + keep  # (label already unique enough)
    print("\n=== +EV (exp_R>0 + OOS≥0, n≥%d) ===" % MIN_N)
    for k in sorted([x for x in keep if x], key=lambda z: -z[1]):
        print("  %-26s exp_R%+.4f t%+.2f OOS%+.4f %s" % k)
    if not any(keep):
        print("  ไม่มี +EV — ทฤษฎีใหม่ไม่ช่วย (stand down)")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
