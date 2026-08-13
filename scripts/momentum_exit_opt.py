#!/usr/bin/env python
"""scripts/momentum_exit_opt.py — momentum breakout: exit ดีกว่า RR2 fixed มั้ย? (trend กำไรจาก fat tail).

momentum/trend มี edge จริง (ตรงข้าม fade). สมมติฐาน: RR2 fixed TP **cap runner** — trend วิ่งไกลกว่า 2R บ่อย
→ ปล่อยให้วิ่ง (RR สูงขึ้น / trailing) อาจดัน exp_R/t ขึ้น. วัด MFE_R (winner วิ่งไกลแค่ไหน) + scan exit แบบ **OOS 70/30**.

exit ที่เทียบ: fixed RR {1.5..5} · chandelier trail (หลัง +trig R, SL = extreme − mult×ATR).
algo: regime_momentum · regime_momentum_fvg (H1) · macro_momentum (H4). คู่ที่ momentum มี edge (gold-complex/BTC/WTI).
รัน: python scripts/momentum_exit_opt.py   → docs/reviews/momentum-exit.md
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                       # noqa: E402
import mfe_rr_diag as M                                      # noqa: E402  (_entries_momentum)

RR_GRID = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
TRAIL = [(1.0, 2.5), (1.0, 3.0), (1.5, 3.0), (1.0, 4.0)]     # (trigger_R, atr_mult)
MAX_HOLD = 240                                               # H1 = ~10 วัน (ปล่อย trend วิ่ง). H4 ปรับใน main
REPORT = os.path.join(_ROOT, "docs", "reviews", "momentum-exit.md")
MIN_N = 60


def _atr_series(h, l, c):
    return R.atr(h, l, c)


def _entries_momentum(h, l, c, brk=20, sl_atr=1.5, fvg=False, fvg_lb=6):
    """breakout entry ตรง bt_momentum/_fvg (TREND-gate). คืน (i, sign, px, sl_dist)."""
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
        if fvg:
            ok = False
            for j in range(max(2, i - fvg_lb), i + 1):
                if d > 0 and l[j] > h[j - 2]:
                    ok = True; break
                if d < 0 and h[j] < l[j - 2]:
                    ok = True; break
            if not ok:
                i += 1; continue
        out.append((i, d, px, sl_atr * av))
        i += 1
    return out


def _entries_macro(h, l, c, mac, msign, brk=20, mlb=24, sl_atr=1.5):
    """macro_momentum จริง: breakout + DXY/driver structural confirm (ตรง bt_macro). คืน (i, sign, px, sl_dist)."""
    atr = R.atr(h, l, c); n = len(c); out = []; i = max(R.VOL_LOOKBACK, brk, mlb) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d or mac[i] != mac[i] or mac[i - mlb] != mac[i - mlb]:
            i += 1; continue
        if d != (1 if msign * (mac[i] - mac[i - mlb]) > 0 else -1):     # driver ต้อง confirm ทิศ
            i += 1; continue
        out.append((i, d, px, sl_atr * av))
        i += 1
    return out


def _mfe_R(h, l, c, i, sign, px, sl_dist, mh):
    n = len(c); end = min(i + mh, n - 1); sl = px - sign * sl_dist; mfe = 0.0
    for j in range(i + 1, end + 1):
        fav = (h[j] - px) if sign > 0 else (px - l[j])
        mfe = max(mfe, fav)
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            break
    return mfe / sl_dist


def _fixed(h, l, c, i, sign, px, sl_dist, rr, cost_R, mh):
    n = len(c); end = min(i + mh, n - 1); sl = px - sign * sl_dist; tp = px + sign * rr * sl_dist
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -1.0 - cost_R
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return rr - cost_R
    return sign * (c[end] - px) / sl_dist - cost_R


def _trail(h, l, c, atr, i, sign, px, sl_dist, trig, mult, cost_R, mh):
    """chandelier: SL เริ่ม px−sign·sl_dist. หลังกำไร ≥trig·R → SL = extreme − sign·mult·ATR (ขยับตามทางเดียว)."""
    n = len(c); end = min(i + mh, n - 1); sl = px - sign * sl_dist
    ext = px; armed = False
    for j in range(i + 1, end + 1):
        ext = max(ext, h[j]) if sign > 0 else min(ext, l[j])
        prof = sign * (ext - px) / sl_dist
        if prof >= trig:
            armed = True
        if armed:
            av = float(atr[j]) if atr[j] == atr[j] else 0.0
            ns = ext - sign * mult * av
            sl = max(sl, ns) if sign > 0 else min(sl, ns)
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return sign * (sl - px) / sl_dist - cost_R
    return sign * (c[end] - px) / sl_dist - cost_R


def _macro_series(mt5, bm, lg, tm_h4):
    """driver (DXY/EURUSD/USDJPY) H4 close align กับ tm_h4 → (mac array, msign). ตรง backtest_all.macro_series."""
    macro_lg, sign = R.macro_for(lg)
    e = bm.get(macro_lg, macro_lg); mt5.symbol_select(e, True)
    r = mt5.copy_rates_from_pos(e, mt5.TIMEFRAME_H4, 0, len(tm_h4) + 500)
    if r is None:
        return None, sign
    emap = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
    return np.array([emap.get(int(t), np.nan) for t in tm_h4], float), sign


def _agg(vals):
    a = np.array(vals, float); n = len(a)
    if n < 20:
        return None
    sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / np.sqrt(n)) if sd else 0.0
    return {"exp": round(float(a.mean()), 3), "t": round(float(t), 2),
            "wr": round(float((a > 0).mean()) * 100, 1), "n": n}


def _split(entries, lo, hi, ntot):
    a = int(ntot * lo); b = int(ntot * hi)
    return [(i, s, px, sld) for (i, s, px, sld) in entries if a <= i < b]


def analyze(algo, entries, h, l, c, atr, cost, pt, mh):
    if len(entries) < MIN_N:
        return None
    n = len(c); cost_R = lambda sld: cost * pt / sld        # noqa: E731
    mfe = [_mfe_R(h, l, c, i, s, px, sld, mh) for (i, s, px, sld) in entries]
    mfe = np.array(mfe)
    out = {"n": len(entries), "mfe_med": round(float(np.median(mfe)), 2),
           "mfe_p75": round(float(np.percentile(mfe, 75)), 2),
           "pct_ge_2R": round(float((mfe >= 2.0).mean()) * 100, 1),
           "pct_ge_3R": round(float((mfe >= 3.0).mean()) * 100, 1), "variants": {}}

    def score(fn, tag):
        is_e = _split(entries, 0.0, 0.7, n); oos_e = _split(entries, 0.7, 1.0, n)
        si = _agg([fn(i, s, px, sld) for (i, s, px, sld) in is_e])
        so = _agg([fn(i, s, px, sld) for (i, s, px, sld) in oos_e])
        out["variants"][tag] = {"is": si, "oos": so}

    score(lambda i, s, px, sld: _fixed(h, l, c, i, s, px, sld, 2.0, cost_R(sld), mh), "RR2(base)")
    for rr in RR_GRID:
        if rr == 2.0:
            continue
        score(lambda i, s, px, sld, rr=rr: _fixed(h, l, c, i, s, px, sld, rr, cost_R(sld), mh), f"RR{rr}")
    for trig, mult in TRAIL:
        score(lambda i, s, px, sld, tg=trig, mu=mult: _trail(h, l, c, atr, i, s, px, sld, tg, mu, cost_R(sld), mh),
              f"trail{trig}/{mult}")
    # best by OOS exp (ที่ OOS n พอ)
    cand = [(tag, v) for tag, v in out["variants"].items() if v["oos"] and v["oos"]["n"] >= 20]
    out["best"] = max(cand, key=lambda t: t[1]["oos"]["exp"])[0] if cand else None
    return out


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    bm = _broker_map() or {}
    cost_of = lambda lg: (_sc.cost_pips(lg) if _sc else None) or 30.0    # noqa: E731

    pairs = ["XAUUSD", "XAGUSD", "XAUEUR", "BTCUSD", "WTIUSD"]           # momentum edge lives ที่นี่
    rows = []
    for lg in pairs:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
            rh4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 30000)
        except Exception:
            info = rh = rh4 = None
        if not info or rh is None or len(rh) < 800:
            continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float)
        atr = _atr_series(h, l, c)
        rows.append((lg, "regime_momentum", analyze("regime_momentum",
                     _entries_momentum(h, l, c, 20, 1.5), h, l, c, atr, cost, pt, MAX_HOLD)))
        rows.append((lg, "regime_momentum_fvg", analyze("regime_momentum_fvg",
                     _entries_momentum(h, l, c, 20, 1.5, fvg=True), h, l, c, atr, cost, pt, MAX_HOLD)))
        if rh4 is not None and len(rh4) > 500:
            h4 = rh4["high"].astype(float); l4 = rh4["low"].astype(float); c4 = rh4["close"].astype(float)
            atr4 = _atr_series(h4, l4, c4)
            mac, msign = _macro_series(mt5, bm, lg, rh4["time"])          # DXY/driver จริง (parity macro_momentum)
            if mac is not None:
                rows.append((lg, "macro_momentum(H4)", analyze("macro_momentum",
                             _entries_macro(h4, l4, c4, mac, msign), h4, l4, c4, atr4, cost, pt, 120)))
        print(f"  {lg}: done")
    mt5.shutdown()

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(f"# Momentum exit optimization — RR / trailing ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write("winner วิ่งไกลกว่า RR2 มั้ย (MFE) + exit ไหน OOS ดีสุด. best เลือกจาก **OOS exp_R** (IS 70/OOS 30).\n\n")
        for lg, algo, d in rows:
            if not d:
                continue
            f.write(f"## {algo} — {lg}\n\n")
            f.write(f"- MFE_R med **{d['mfe_med']}** · p75 **{d['mfe_p75']}** · %≥2R **{d['pct_ge_2R']}%** · %≥3R **{d['pct_ge_3R']}%** (n {d['n']})\n\n")
            f.write("| exit | IS exp/t/n | **OOS exp/t/n** |\n|---|---|---|\n")
            for tag, v in d["variants"].items():
                si = v["is"]; so = v["oos"]
                sf = f"{si['exp']:+.3f}/{si['t']:+.2f}/{si['n']}" if si else "—"
                of = f"{so['exp']:+.3f}/{so['t']:+.2f}/{so['n']}" if so else "—"
                mark = " ⭐" if tag == d["best"] else ""
                f.write(f"| {tag}{mark} | {sf} | {of} |\n")
            f.write("\n")
    print(f"\nreport → {REPORT}\n")
    for lg, algo, d in rows:
        if d and d["best"]:
            b = d["variants"][d["best"]]; base = d["variants"].get("RR2(base)")
            bo = base["oos"]["exp"] if base and base["oos"] else None
            print(f"  {algo:20s} {lg:7s} MFE med {d['mfe_med']} %≥2R {d['pct_ge_2R']}% | "
                  f"base RR2 OOS {bo} -> best {d['best']} OOS {b['oos']['exp']:+.3f} (t {b['oos']['t']})")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
