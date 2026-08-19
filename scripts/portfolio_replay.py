#!/usr/bin/env python
"""scripts/portfolio_replay.py — replay ระบบทั้ง roster บน history → equity curve รวม (user 08-08).

ต่างจาก backtest_all (per-algo แยก exp_R): อันนี้ **รวมทุก algo × ทุกคู่เป็น portfolio เดียว** — merge trade
ตามเวลา → sim fixed-fractional (risk %/ไม้, compounding) → equity/return/maxDD/Sharpe รวม = "ระบบปัจจุบัน
ทำเงินเท่าไรบนประวัติ". เทียบ 2 portfolio: ALL combos vs +EV-only (ตัด −EV).

algo: momentum(H1 TREND) · macro(H4 breakout+DXY) · tsmom(D1 ensemble+confirm). causal · SL-first · cost-adj.
รัน: python scripts/portfolio_replay.py [--risk 0.5]
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402


_MANAGED = False                                          # --managed → BE+trailing แทน SL/TP ตายตัว
_BE_R = 1.2                                               # profit ≥ 1.2R → ย้าย SL ไป BE
_BE_BUF = 0.15                                            # BE buffer = 0.15×SL (lock บวกนิด)
_TRAIL_R = 1.5                                            # หลัง BE + ≥1.5R → เริ่ม trail
_TRAIL_ATR = 0.5                                          # trail = 0.5×ATR ใต้/เหนือราคา


def _res(h, l, c, i, sign, px, slp, rr, pt, cost, mh, atr=None):
    """SL-first fixed SL/TP. ถ้า _MANAGED + atr → BE+trailing (เหมือน live)."""
    sl = px - sign * slp * pt; tp = px + sign * slp * rr * pt
    n = len(c); end = min(i + mh, n - 1); be = False
    for j in range(i + 1, end + 1):
        if _MANAGED and atr is not None:
            prog = sign * (c[j] - px) / (slp * pt)         # R progress (close)
            av = float(atr[j]) if atr[j] == atr[j] else 0.0
            if not be and prog >= _BE_R:                   # → BE (risk ~0)
                sl = px + sign * _BE_BUF * slp * pt; be = True
            if be and prog >= _TRAIL_R and av > 0:         # trailing
                nsl = c[j] - sign * _TRAIL_ATR * av
                sl = max(sl, nsl) if sign > 0 else min(sl, nsl)
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):     # SL hit (fixed/BE/trailed)
            return sign * (sl - px) / (slp * pt) - cost / slp, j
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost / slp, j
    return sign * (c[end] - px) / (slp * pt) - cost / slp, end


def r_momentum(h, l, c, tm, cost, pt, brk=20, rr=2.0, mh=120):
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); out = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        rr_, ei = _res(h, l, c, i, d, px, 1.5 * av / pt, rr, pt, cost, mh, atr=atr)
        out.append((int(tm[i]), rr_)); i = ei + 1
    return out


def r_macro(h, l, c, tm, macro, cost, pt, brk=20, mlb=24, rr=2.0, mh=120):
    atr = R.atr(h, l, c); n = len(c); out = []; i = max(R.VOL_LOOKBACK, brk, mlb) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d or macro[i] != macro[i] or macro[i - mlb] != macro[i - mlb] or d != (1 if macro[i] > macro[i - mlb] else -1):
            i += 1; continue
        rr_, ei = _res(h, l, c, i, d, px, 1.5 * av / pt, rr, pt, cost, mh, atr=atr)
        out.append((int(tm[i]), rr_)); i = ei + 1
    return out


def r_tsmom(dc, dtm, cost_price, lbs=(21, 63, 126), confirm=21):
    out = []; pos = 0; entry = 0.0; ent_t = 0; start = max(max(lbs), confirm) + 2
    for i in range(start, len(dc)):
        v = sum(int(np.sign(dc[i] - dc[i - L])) for L in lbs if i - L >= 0)
        d = 1 if v > 0 else -1 if v < 0 else 0
        if d and confirm and i - confirm >= 0:
            s = np.sign(dc[i] - dc[i - confirm])
            if (s > 0 and d < 0) or (s < 0 and d > 0):
                d = 0
        if d == 0:
            d = pos
        if d != pos:
            if pos != 0:
                out.append((ent_t, (pos * (dc[i] - entry) - cost_price) / dc[-1] * 20))  # ~R (norm)
            pos = d; entry = dc[i]; ent_t = int(dtm[i])
    return out


def _ema(a, n):
    e = np.zeros_like(a); e[0] = a[0]; k = 2 / (n + 1)
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _slope_map(m15t, ht, hc, n=50):
    e = _ema(hc, n); sl = np.sign(e - np.concatenate([e[:3], e[:-3]]))
    return sl[np.clip(np.searchsorted(ht, m15t, "right") - 1, 0, len(sl) - 1)]


def r_conf15m(mt5, sym, e_broker, cost, pt, session=None, brk=12, rr=2.0, sl_atr=1.0, vk=1.5, mh=48):
    """confluence_15m: M15 breakout + H1+H4+macro + volume surge (+session filter ถ้า gold). คืน [(ts,R)]."""
    from datetime import datetime, timezone
    m = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 30000)
    h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 15000)
    h4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 10000)
    em = mt5.copy_rates_from_pos(e_broker, mt5.TIMEFRAME_M15, 0, 30000)
    if m is None or len(m) < 3000 or h1 is None or h4 is None or em is None:
        return []
    h, l, c, tm = m["high"].astype(float), m["low"].astype(float), m["close"].astype(float), m["time"].astype(np.int64)
    vol = m["tick_volume"].astype(float)
    h1t = _slope_map(tm, h1["time"].astype(np.int64), h1["close"].astype(float))
    h4t = _slope_map(tm, h4["time"].astype(np.int64), h4["close"].astype(float))
    emap = {int(t): float(x) for t, x in zip(em["time"], em["close"])}
    mac = np.array([emap.get(int(t), np.nan) for t in tm], float)
    atr = R.atr(h, l, c); n = len(c); out = []; i = 210
    vmed = np.zeros(n)
    for k in range(200, n):
        vmed[k] = np.median(vol[k - 200:k]) or 1
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or vmed[i] <= 0 or vol[i] > 2.0 * vmed[i]:
            i += 1; continue
        if session:
            hr = datetime.fromtimestamp(int(tm[i]), timezone.utc).hour
            if not (session[0] <= hr < session[1]):
                i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        mm = mac[i]; ml = mac[i - 24] if i - 24 >= 0 else np.nan
        if (h1t[i] != d or h4t[i] != d or mm != mm or ml != ml or (1 if mm > ml else -1) != d or vol[i] < vk * vmed[i]):
            i += 1; continue
        r_, ei = _res(h, l, c, i, d, px, max(50, sl_atr * av / pt), rr, pt, cost, mh, atr=atr)
        out.append((int(tm[i]), r_)); i = ei + 1
    return out


def r_pairs(mt5, xau, xag, cost_y, cost_x, win=120, z_in=2.0, z_out=0.5, z_stop=3.5):
    """XAU-XAG stat-arb spread z-fade (rolling β causal). คืน [(entry_ts, R)]."""
    ra = mt5.copy_rates_from_pos(xau, mt5.TIMEFRAME_H1, 0, 40000)
    rb = mt5.copy_rates_from_pos(xag, mt5.TIMEFRAME_H1, 0, 40000)
    if ra is None or rb is None:
        return []
    mb = {int(t): float(c) for t, c in zip(rb["time"], rb["close"])}
    ys = []; xs = []; ts = []
    for t, c in zip(ra["time"], ra["close"]):
        if int(t) in mb:
            ys.append(float(c)); xs.append(mb[int(t)]); ts.append(int(t))
    if len(ys) < win + 50:
        return []
    y = np.array(ys); x = np.array(xs); out = []; pos = 0; entry_s = 0.0; entry_sd = 1.0; beta_at = 1.0; ent_t = 0
    for i in range(win, len(y)):
        beta = np.polyfit(x[i - win:i], y[i - win:i], 1)[0]
        sw = y[i - win:i] - beta * x[i - win:i]; m, sd = sw.mean(), sw.std()
        if sd <= 0:
            continue
        z = (y[i] - beta * x[i] - m) / sd
        if pos == 0:
            if abs(z) > z_in:
                pos = -1 if z > 0 else 1; entry_s = y[i] - beta * x[i]; entry_sd = sd; beta_at = beta; ent_t = ts[i]
        else:
            if (abs(z) <= z_out) or ((z >= z_stop) if pos == -1 else (z <= -z_stop)):
                sl_dist = (z_stop - z_in) * entry_sd
                cost = cost_y + beta_at * cost_x
                pnl = pos * ((y[i] - beta_at * x[i]) - entry_s) - cost
                out.append((ent_t, pnl / sl_dist if sl_dist else 0.0)); pos = 0
    return out


def _metrics(trades, e0=10000.0, risk=0.005):
    """trades = [(ts, R)] sorted. fixed-fractional compounding. คืน dict."""
    if not trades:
        return None
    eq = e0; curve = [e0]; peak = e0; maxdd = 0.0; rs = []
    for ts, r in trades:
        pnl = r * risk * eq
        eq += pnl; curve.append(eq); rs.append(r)
        peak = max(peak, eq); dd = (peak - eq) / peak
        maxdd = max(maxdd, dd)
    a = np.array(rs); sd = a.std(ddof=1) if len(a) > 1 else 0.0
    yrs = (trades[-1][0] - trades[0][0]) / (365.25 * 24 * 3600) or 1
    ret = (eq / e0 - 1) * 100
    cagr = ((eq / e0) ** (1 / yrs) - 1) * 100 if yrs > 0 and eq > 0 else 0
    return {"n": len(trades), "ret_pct": round(ret, 1), "cagr_pct": round(cagr, 1),
            "maxdd_pct": round(maxdd * 100, 1), "final_eq": round(eq, 0),
            "wr": round(float((a > 0).mean()) * 100, 1), "exp_R": round(float(a.mean()), 4),
            "sharpe_tr": round(float(a.mean() / sd), 3) if sd else 0.0, "yrs": round(yrs, 1)}


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    from agents import algo_registry as reg
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    global _MANAGED
    _MANAGED = "--managed" in sys.argv
    global _TRAIL_ATR, _TRAIL_R
    if "--trail_atr" in sys.argv: _TRAIL_ATR = float(sys.argv[sys.argv.index("--trail_atr")+1])
    if "--trail_r" in sys.argv: _TRAIL_R = float(sys.argv[sys.argv.index("--trail_r")+1])
    risk = 0.005
    if "--risk" in sys.argv:
        try:
            risk = float(sys.argv[sys.argv.index("--risk") + 1]) / 100
        except Exception:
            pass
    bm = _broker_map() or {}
    # verdict +EV จาก backtest_results
    import json
    try:
        bt = json.load(open(os.path.join(_ROOT, "data", "backtest_results.json"), encoding="utf-8"))["results"]
        ev = {(r["algo"], r["pair"]): r["group"] for r in bt}
    except Exception:
        ev = {}
    print("\n=== PORTFOLIO REPLAY · %s · risk %.2f%%/ไม้ ===" % ("MANAGED (BE+trailing)" if _MANAGED else "fixed SL/TP", risk * 100))
    all_tr = []; ev_tr = []; contrib = {}
    e_url = bm.get("EURUSD", "EURUSD"); mt5.symbol_select(e_url, True)
    reH4 = mt5.copy_rates_from_pos(e_url, mt5.TIMEFRAME_H4, 0, 15000)
    reH1 = mt5.copy_rates_from_pos(e_url, mt5.TIMEFRAME_H1, 0, 15000)
    emH4 = {int(t): float(c) for t, c in zip(reH4["time"], reH4["close"])} if reH4 is not None else {}
    for lg in reg.UNIVERSE:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            rH1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 15000)
            rH4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 15000)
            rD1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        except Exception:
            info = None
        if not info or rH1 is None or len(rH1) < 800:
            continue
        pt = float(info.point); cost = (_sc.cost_pips(lg) if _sc else None) or 30.0
        combos = []
        # momentum H1
        h, l, c, tm = rH1["high"].astype(float), rH1["low"].astype(float), rH1["close"].astype(float), rH1["time"]
        combos.append(("regime_momentum", r_momentum(h, l, c, tm, cost, pt)))
        # macro H4
        if rH4 is not None and len(rH4) > 500:
            h4, l4, c4, t4 = rH4["high"].astype(float), rH4["low"].astype(float), rH4["close"].astype(float), rH4["time"]
            mac = np.array([emH4.get(int(t), np.nan) for t in t4], float)
            combos.append(("macro_momentum", r_macro(h4, l4, c4, t4, mac, cost, pt)))
        # tsmom D1
        if rD1 is not None and len(rD1) >= 300:
            dc, dtm = rD1["close"].astype(float), rD1["time"]
            combos.append(("tsmom_d1", r_tsmom(dc, dtm, cost * pt)))
        for algo, trs in combos:
            for tr in trs:
                all_tr.append(tr)
                contrib.setdefault(algo, []).append(tr[1])
                if ev.get((algo, lg)) == "+EV":
                    ev_tr.append(tr)
    # confluence_15m (XAU NY-session + BTC 24/7) — +EV
    def _cost(lg):
        return (_sc.cost_pips(lg) if _sc else None) or 30.0
    for lg, sess in [("XAUUSD", (13, 21)), ("BTCUSD", None)]:
        brk = bm.get(lg, lg); mt5.symbol_select(brk, True)
        info = mt5.symbol_info(brk)
        if not info:
            continue
        trs = r_conf15m(mt5, brk, bm.get("EURUSD", "EURUSD"), _cost(lg), float(info.point), session=sess)
        for tr in trs:
            all_tr.append(tr); ev_tr.append(tr); contrib.setdefault("confluence_15m", []).append(tr[1])
    # xau_xag_pairs — +EV market-neutral
    xau = bm.get("XAUUSD", "XAUUSD"); xag = bm.get("XAGUSD", "XAGUSD")
    ia = mt5.symbol_info(xau); ib = mt5.symbol_info(xag)
    if ia and ib:
        trs = r_pairs(mt5, xau, xag, _cost("XAUUSD") * float(ia.point), _cost("XAGUSD") * float(ib.point))
        for tr in trs:                                      # pairs = 2-leg, sizing ต่างจาก single-trade → contrib โชว์เฉยๆ ไม่รวม portfolio
            contrib.setdefault("xau_xag_pairs", []).append(tr[1])
    all_tr.sort(key=lambda x: x[0]); ev_tr.sort(key=lambda x: x[0])
    print("\n%-14s %s" % ("PORTFOLIO", "n / ret% / CAGR% / maxDD% / Sharpe(tr) / WR% / finalEq (E0=10k)"))
    for name, trs in [("ALL combos", all_tr), ("+EV only", ev_tr)]:
        m = _metrics(trs, risk=risk)
        if m:
            print("%-14s n=%d ret=%+.0f%% CAGR=%+.1f%% maxDD=%.1f%% Sharpe=%.3f WR=%.1f%% eq=%.0f (%.1fปี)" % (
                name, m["n"], m["ret_pct"], m["cagr_pct"], m["maxdd_pct"], m["sharpe_tr"], m["wr"], m["final_eq"], m["yrs"]))
    print("\n=== contribution ต่อ algo (exp_R เฉลี่ย · n) ===")
    for a, rs in sorted(contrib.items(), key=lambda x: -np.mean(x[1])):
        arr = np.array(rs)
        print("  %-18s n=%4d exp_R=%+.4f sumR=%+.1f" % (a, len(arr), arr.mean(), arr.sum()))
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
