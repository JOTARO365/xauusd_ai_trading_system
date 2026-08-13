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


def _pc(algo, lg, param, default):
    """per-pair config override (algo_pair_config) → backtest สะท้อน config live จริง (parity)."""
    try:
        from agents import algo_pair_config as _apc
        v = _apc.get(algo, lg, param, None)
        if v is None:
            return default
        return type(default)(v) if default is not None else v
    except Exception:
        return default


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


def _season_bt(sym, d, tm, i):
    """seasonal gate (parity กับ live): True=block. XAU + SEASONALITY_GATE เท่านั้น."""
    if tm is None or not sym:
        return False
    try:
        import config as _c
        if not getattr(_c, "SEASONALITY_GATE", False):
            return False
        from agents import seasonality as _sz
        mo = datetime.fromtimestamp(int(tm[i]), timezone.utc).month
        return _sz.blocks(sym, "BUY" if d > 0 else "SELL", mo)
    except Exception:
        return False


def bt_momentum(h, l, c, cost, pt, brk=20, rr=2.0, sl_atr=1.5, trend=True, mh=120, tm=None, sym=None, gate=None):
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or (trend and R.detect_regime(er[i], adx[i], vp[i]) != "TREND"):
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d or _season_bt(sym, d, tm, i):
            i += 1; continue
        if gate and gate(h, l, i, px, d, av):
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_momentum_fvg(h, l, c, cost, pt, brk=20, rr=2.0, sl_atr=1.5, mh=120, fvg_lb=6, tm=None, sym=None, gate=None):
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
        if not d or _season_bt(sym, d, tm, i):
            i += 1; continue
        ok = False                                          # FVG confluence (เหมือน live)
        for j in range(max(2, i - fvg_lb), i + 1):
            if d > 0 and l[j] > h[j - 2]:
                ok = True; break
            if d < 0 and h[j] < l[j - 2]:
                ok = True; break
        if not ok:
            i += 1; continue                                # ไม่มี FVG → skip (filter จริง)
        if gate and gate(h, l, i, px, d, av):
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_cdc(h, l, c, cost_price, sl_atr=2.0, mode="long", pb_min=None, pb_lb=None, gate=None):
    """CDC Action Zone (อ.โฉลก) — trend-follow exit-on-flip + pullback entry (โฉลก wave-2/4: เข้าตอนย่อ),
    R-norm 2N (Turtle). mirror agents.CDCZoneAlgo + shadow _resolve_cdc_flip = parity. pb จาก config (parity live)."""
    try:
        import config as _c
        if pb_min is None:
            pb_min = float(getattr(_c, "CDC_PULLBACK_MIN", 0.005) or 0.0)
        if pb_lb is None:
            pb_lb = int(getattr(_c, "CDC_PULLBACK_LB", 20) or 20)
    except Exception:
        pb_min = pb_min or 0.005; pb_lb = pb_lb or 20
    fast, slow = R.cdc_zone(c); atr = R.atr(h, l, c)
    n = len(c); tr = []; pos = 0; entry = 0.0; risk = 0.0
    for i in range(30, n):
        if pos != 0 and risk > 0 and pos * (c[i] - entry) <= -risk:   # disaster SL 2N
            tr.append(-1.0 - cost_price / risk); pos = 0
        bull = fast[i] > slow[i]
        if pos == 0:                                          # event-driven entry (bull + ย่อพอ)
            want = 1 if bull else (-1 if mode == "both" else 0)
            if want == 0:
                continue
            if pb_min > 0 and i >= pb_lb:
                if want > 0 and c[i] > float(h[i - pb_lb:i].max()) * (1 - pb_min):
                    continue
                if want < 0 and c[i] < float(l[i - pb_lb:i].min()) * (1 + pb_min):
                    continue
            if gate and gate(h, l, i, float(c[i]), want, 0.0):
                continue
            pos = want; entry = c[i]
            av = float(atr[i]) if atr[i] == atr[i] else 0.0
            risk = sl_atr * av if av > 0 else 0.0
        elif (pos > 0 and not bull) or (pos < 0 and bull):    # zone flip → ออก
            tr.append((pos * (c[i] - entry) - cost_price) / risk if risk > 0 else 0.0)
            pos = 0
    return tr


def bt_tsmom(h, l, c, cost_price, lbs=(21, 63, 126), confirm=21, sl_atr=3.0, gate=None):
    """R-multiple (norm 3×ATR-D1 = disaster SL ของ live) + disaster stop → เทียบ algo อื่นได้.
    (เดิมคืน %ของราคาสุดท้าย = magnitude เทียบไม่ได้; live มี SL_ATR=3.0 ที่ backtest เดิมไม่มี)."""
    atr = R.atr(h, l, c)
    tr = []; pos = 0; entry = 0.0; risk = 0.0
    start = max(max(lbs), confirm or 0, R.VOL_LOOKBACK) + 2
    for i in range(start, len(c)):
        if pos != 0 and risk > 0:                              # disaster SL (close-based) ก่อนเช็ค flip
            adverse = pos * (c[i] - entry)
            if adverse <= -risk:
                tr.append(-1.0 - cost_price / risk); pos = 0
        v = sum(int(np.sign(c[i] - c[i - L])) for L in lbs if i - L >= 0)
        d = 1 if v > 0 else -1 if v < 0 else 0
        if d and confirm and i - confirm >= 0:                 # confirm = entry filter
            s = np.sign(c[i] - c[i - confirm])
            if (s > 0 and d < 0) or (s < 0 and d > 0):
                d = 0
        if d == 0:
            d = pos
        if gate and d != pos and d != 0:                       # candle-confirm ก่อน flip → ไม่ยืนยัน = เลื่อน (คง pos เดิม)
            av = float(atr[i]) if atr[i] == atr[i] else 0.0
            if gate(h, l, i, float(c[i]), d, av):
                d = pos
        if d != pos:
            if pos != 0 and risk > 0:
                tr.append((pos * (c[i] - entry) - cost_price) / risk)   # R = pnl/risk_unit
            pos = d; entry = c[i]
            av = float(atr[i]) if atr[i] == atr[i] else 0.0
            risk = sl_atr * av if av > 0 else 0.0
    return tr


def bt_meanrev(h, l, c, cost, pt, win=20, z=1.25, s_stop=2.5, hl_max=10, sl_atr=1.5, tk=3, gate=None):
    """ตรง algo_mean_reversion live: win20 · RANGE-only · OU half-life gate · zone SL (m∓2.5σ, floor ATR)
    · TP=กลับ mean · time-stop 3×half-life (audit fix 08-09; เดิม win60/NEUTRAL+RANGE/fixed SL/rr1 = คนละ algo)."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); tr = []; i = max(R.VOL_LOOKBACK, win) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) != "RANGE":      # RANGE-only (ตรง live)
            i += 1; continue
        w = c[i - win + 1:i + 1]
        hl = R.ou_halflife(w)
        if hl > hl_max:                                                       # OU gate: reversion เร็วพอ
            i += 1; continue
        m, sd = float(w.mean()), float(w.std())
        if sd <= 0:
            i += 1; continue
        zz = (float(c[i]) - m) / sd
        d = 1 if zz <= -z else -1 if zz >= z else 0
        if not d:
            i += 1; continue
        px = float(c[i])
        if gate and gate(h, l, i, px, d, av):
            i += 1; continue
        sl_price = (m - s_stop * sd) if d > 0 else (m + s_stop * sd)         # zone SL เลย band
        sl_dist = max(abs(px - sl_price), sl_atr * av)                       # floor ด้วย ATR
        tp_dist = max(abs(px - m), sl_atr * av)                              # TP = กลับ mean
        mh = max(1, round(tk * hl))                                          # time-stop 3×half-life
        end = min(i + mh, n - 1); R_out = None; ei = end
        for j in range(i + 1, end + 1):
            if d > 0:
                if l[j] <= px - sl_dist:   R_out = -1.0 - cost * pt / sl_dist; ei = j; break
                if h[j] >= px + tp_dist:   R_out = tp_dist / sl_dist - cost * pt / sl_dist; ei = j; break
            else:
                if h[j] >= px + sl_dist:   R_out = -1.0 - cost * pt / sl_dist; ei = j; break
                if l[j] <= px - tp_dist:   R_out = tp_dist / sl_dist - cost * pt / sl_dist; ei = j; break
        if R_out is None:
            R_out = d * (c[end] - px) / sl_dist - cost * pt / sl_dist
        tr.append(R_out); i = ei + 1
    return tr


def bt_sweep(h, l, c, tm, cost, pt, rr=1.5, buf_atr=0.5, mh=120, gate=None):
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
        px = float(c[i]); d = 0; swept = 0.0
        if l[i] < pdl[i] and px > pdl[i]:
            d = 1; swept = float(l[i])                    # BUY: sweep prior-day low
        elif h[i] > pdh[i] and px < pdh[i]:
            d = -1; swept = float(h[i])                   # SELL: sweep prior-day high
        if not d:
            i += 1; continue
        if gate and gate(h, l, i, px, d, av):
            i += 1; continue
        # SL เลยปลาย sweep wick + buf×ATR (ตรง SweepReversalAlgo live; เดิม fixed 1.0×ATR = ผิด)
        sl_price = swept - d * buf_atr * av
        sl_pips = abs(px - sl_price) / pt
        if sl_pips <= 0:
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_pips, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_macro(h, l, c, macro, cost, pt, brk=20, mlb=24, rr=2.0, sl_atr=1.5, mh=120, msign=1, tm=None, sym=None, gate=None):
    atr = R.atr(h, l, c); n = len(c); tr = []; i = max(R.VOL_LOOKBACK, brk, mlb) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d or macro[i] != macro[i] or macro[i - mlb] != macro[i - mlb]:
            i += 1; continue
        if d != (1 if msign * (macro[i] - macro[i - mlb]) > 0 else -1):   # USD-factor ต่อคู่ (structural sign)
            i += 1; continue
        if _season_bt(sym, d, tm, i):
            i += 1; continue
        if gate and gate(h, l, i, px, d, av):
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def _htf_slope_map(m15_time, htf_time, htf_close, ema_n=50):
    e = np.zeros_like(htf_close); e[0] = htf_close[0]; k = 2 / (ema_n + 1)
    for i in range(1, len(htf_close)):
        e[i] = htf_close[i] * k + e[i - 1] * (1 - k)
    slope = np.sign(e - np.concatenate([e[:3], e[:-3]]))
    # -2: แท่ง HTF ที่ "ปิดแล้ว" ก่อน m15 bar (−1=แท่งที่ยัง forming → look-ahead). ตรง live es[-2]
    idx = np.clip(np.searchsorted(htf_time, m15_time, side="right") - 2, 0, len(slope) - 1)
    return slope[idx]


def bt_conf15m(mt5, sym, e_broker, cost, pt, brk=12, rr=2.0, sl_atr=1.0, vk=1.5, mh=48, session=None, season_sym=None, gate=None):
    """confluence_15m ต่อคู่: 15m breakout + H1+H4+macro ตรง + volume surge. คืน list R.
    session: override 'lo-hi' UTC (None → config default สำหรับ XAU)."""
    m = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 40000)
    if m is None or len(m) < 3000:
        return []
    h = m["high"].astype(float); l = m["low"].astype(float); c = m["close"].astype(float)
    tm = m["time"].astype(np.int64); vol = m["tick_volume"].astype(float)
    h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
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
    # live gate: gold เทรดเฉพาะ CONF15M_SESSION (default 13-21 UTC, XAU only) — เหมือน ConfluenceVol15m
    _sess = None
    _sraw = session if session is not None else None
    if str(sym).upper().startswith("XAU"):
        try:
            import config as _cfg
            _sr = _sraw if _sraw else str(getattr(_cfg, "CONF15M_SESSION", "13-21"))
            _a, _b = str(_sr).split("-")
            _sess = (int(_a), int(_b))
        except Exception:
            _sess = (13, 21)
    elif _sraw and "-" in str(_sraw):                          # sweep session บนคู่ non-XAU ได้ด้วย
        try:
            _a, _b = str(_sraw).split("-"); _sess = (int(_a), int(_b))
        except Exception:
            _sess = None
    hours = np.array([datetime.fromtimestamp(int(t), timezone.utc).hour for t in tm]) if _sess else None
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or volmed[i] <= 0 or vol[i] > 2.0 * volmed[i]:
            i += 1; continue
        if _sess and not (_sess[0] <= hours[i] < _sess[1]):   # นอก session ทอง → skip (เหมือน live)
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        if _season_bt(season_sym, d, tm, i):
            i += 1; continue
        m_ = mac[i]; ml = mac[i - 24] if i - 24 >= 0 else np.nan
        if (h1t[i] != d or h4t[i] != d or m_ != m_ or ml != ml
                or (1 if m_ > ml else -1) != d or vol[i] < vk * volmed[i]):
            i += 1; continue
        if gate and gate(h, l, i, px, d, av):
            i += 1; continue
        r, ei = _resolve(h, l, c, i, d, px, sl_atr * av / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def bt_pairs(mt5, xau_sym, xag_sym, cost_price, win=120, z_in=2.0, z_out=0.5, z_stop=3.5):
    """causal stat-arb XAU-XAG: rolling-β z-fade (เหมือน pairs_executor). R = pnl_spread/risk − cost. คืน list R."""
    a = mt5.copy_rates_from_pos(xau_sym, mt5.TIMEFRAME_H1, 0, 50000)
    b = mt5.copy_rates_from_pos(xag_sym, mt5.TIMEFRAME_H1, 0, 50000)
    if a is None or b is None:
        return []
    mb = {int(t): float(c) for t, c in zip(b["time"], b["close"])}
    y = []; x = []
    for t, c in zip(a["time"], a["close"]):
        if int(t) in mb:
            y.append(float(c)); x.append(mb[int(t)])
    if len(y) < win + 200:
        return []
    y = np.array(y); x = np.array(x); n = len(y)
    tr = []; pos = 0; entry_sp = 0.0; risk = 0.0; cost2 = cost_price * 2   # 2 ขา
    for i in range(win, n):
        beta = np.polyfit(x[i - win:i], y[i - win:i], 1)[0]
        sp = y[i - win:i] - beta * x[i - win:i]
        m, sd = float(sp.mean()), float(sp.std())
        if sd <= 0:
            continue
        cur = float(y[i] - beta * x[i]); z = (cur - m) / sd
        if pos == 0:
            if abs(z) >= z_in:
                pos = 1 if z < 0 else -1                       # z<0 long-spread · z>0 short-spread
                entry_sp = cur; risk = (z_stop - z_in) * sd
        else:
            if abs(z) <= z_out or abs(z) >= z_stop:
                if risk > 0:
                    tr.append((pos * (cur - entry_sp) - cost2) / risk)
                pos = 0
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
    def macro_series(lg, tm, tf):
        macro_lg, sign = R.macro_for(lg)                   # structural driver ต่อคู่ (XAUJPY→USDJPY, XAUEUR→EURUSD−)
        e = bm.get(macro_lg, macro_lg); mt5.symbol_select(e, True)
        r = mt5.copy_rates_from_pos(e, tf, 0, len(tm) + 500)
        if r is None:
            return None, sign
        emap = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
        return np.array([emap.get(int(t), np.nan) for t in tm], float), sign

    print("backtest matrix: algo × pair (causal · cost-adj · OOS)…")
    for lg in universe:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
            rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        except Exception:
            info = rh = rd = None
        if not info or rh is None or len(rh) < 800:
            print(f"  {lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"]
        # momentum (H1) — regime_momentum = breakout · fvg = breakout + FVG filter (แยกจริง, ไม่ก๊อป)
        rows.append(_row("regime_momentum", lg, "H1", _stats(bt_momentum(
            h, l, c, cost, pt, brk=_pc("regime_momentum", lg, "BRK", 20),
            sl_atr=_pc("regime_momentum", lg, "SL_ATR", 1.5), rr=_pc("regime_momentum", lg, "RR", 2.0),
            tm=tm, sym=lg)), "Donchian breakout TREND-gate"))
        rows.append(_row("regime_momentum_fvg", lg, "H1", _stats(bt_momentum_fvg(h, l, c, cost, pt, tm=tm, sym=lg)),
                         "Donchian breakout + FVG confluence filter"))
        # mean_reversion (H1)
        rows.append(_row("mean_reversion", lg, "H1", _stats(bt_meanrev(h, l, c, cost, pt)), "z-fade RANGE"))
        # sweep_reversal (H1)
        rows.append(_row("sweep_reversal", lg, "H1", _stats(bt_sweep(
            h, l, c, tm, cost, pt, rr=_pc("sweep_reversal", lg, "RR", 1.5),
            buf_atr=_pc("sweep_reversal", lg, "BUF_ATR", 0.5))), "prior-day sweep fade"))
        # tsmom (D1)
        if rd is not None and len(rd) >= 300:
            dc = rd["close"].astype(float); dh = rd["high"].astype(float); dl = rd["low"].astype(float)
            rows.append(_row("tsmom_d1", lg, "D1", _stats(bt_tsmom(dh, dl, dc, cost * pt)),
                             "ensemble 21/63/126 + confirm21 · R-norm 3×ATR + disaster SL"))
            rows.append(_row("cdc_zone", lg, "D1", _stats(bt_cdc(dh, dl, dc, cost * pt)),
                             "CDC Action Zone (โฉลก) long-only · exit-on-flip · Turtle 2N SL · ถือยาว"))
        # macro_momentum (ทุกคู่เพื่อ matrix ครบ; DXY driver ตรงเฉพาะ gold-complex → non-gold คาด −EV = data จริง)
        rh4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 30000)
        if rh4 is not None and len(rh4) > 500:
            h4 = rh4["high"].astype(float); l4 = rh4["low"].astype(float); c4 = rh4["close"].astype(float)
            mac, msign = macro_series(lg, rh4["time"], mt5.TIMEFRAME_H4)
            if mac is not None:
                _mlg, _ = R.macro_for(lg)
                note = "breakout + %s confirm (structural, sign %+d)" % (_mlg, msign)
                rows.append(_row("macro_momentum", lg, "H4", _stats(bt_macro(
                    h4, l4, c4, mac, cost, pt, brk=_pc("macro_momentum", lg, "BRK", 20),
                    mlb=_pc("macro_momentum", lg, "MLB", 24), sl_atr=_pc("macro_momentum", lg, "SL_ATR", 1.5),
                    rr=_pc("macro_momentum", lg, "RR", 2.0), msign=msign, tm=rh4["time"], sym=lg)), note))
        # confluence_15m (ทุกคู่ — backtest ก่อนเปิด eligible; DXY driver ตรงเฉพาะ gold-complex)
        try:
            n15 = "15m confluence + volume surge" + ("" if lg in ("XAUUSD", "XAGUSD", "XAUEUR") else " (DXY ไม่ตรงคู่นี้)")
            rows.append(_row("confluence_15m", lg, "M15", _stats(bt_conf15m(
                mt5, sym, bm.get("EURUSD", "EURUSD"), cost, pt, brk=_pc("confluence_15m", lg, "BRK", 12),
                rr=_pc("confluence_15m", lg, "RR", 2.0), sl_atr=_pc("confluence_15m", lg, "SL_ATR", 1.0),
                vk=_pc("confluence_15m", lg, "VK", 1.5), session=_pc("confluence_15m", lg, "session", None),
                season_sym=lg)), n15))
        except Exception:
            pass
        print(f"  {lg}: done")
    # pairs — causal rolling-β z-fade จริง (ไม่ hardcode แล้ว; audit 08-09: เลขเดิม static + auto-LIVE = อันตราย)
    try:
        _xau = bm.get("XAUUSD", "XAUUSD"); _xag = bm.get("XAGUSD", "XAGUSD")
        mt5.symbol_select(_xau, True); mt5.symbol_select(_xag, True)
        _ptr = bt_pairs(mt5, _xau, _xag, cost_of("XAUUSD"))
        _ps = _stats(_ptr)
        if _ps:
            rows.append(_row("xau_xag_pairs", "XAU~XAG", "H1", _ps,
                             "stat-arb 2-leg rolling-β z-fade (causal) · ⚠️ cointegration-scan: ไม่ผ่าน split-half"))
    except Exception:
        pass

    # coverage guard: ทุก algo ใน ALGO_REGISTRY ต้องอยู่ใน matrix (ไม่ hardcode/หายเงียบเมื่อเพิ่ม algo ใหม่)
    _covered = {r["algo"] for r in rows}
    for _aid in reg.ALGO_REGISTRY:
        if _aid not in _covered:
            print(f"  ⚠️ {_aid}: ยังไม่มีใน backtest matrix — เพิ่ม bt_ ใน backtest_all.main()")
            rows.append(_row(_aid, "—", getattr(reg.get(_aid), "timeframe", "?"), None,
                             "⚠️ ยังไม่มี backtest — เพิ่ม bt_ ใน scripts/backtest_all.py"))

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
