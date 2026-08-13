#!/usr/bin/env python
"""scripts/mfe_rr_diag.py — 2 algo intraday fade (mean_reversion, sweep_reversal): MFE + fixed-point-target scan.

สมมติฐาน (user): 2 algo นี้เป็น intraday (เทรดปิดในวัน) → ไปถูกทิศ "ช่วงแรก" (MFE บวก) แต่ TP ตั้งไกลเกิน
(RR สูง) → intraday move มีขอบเขต ~1000-3000 จุด ราคาเลยกลับมาโดนหน้าทุน/SL ก่อนถึง TP.
ทดสอบ: (1) MFE_R ของไม้แพ้สูงมั้ย = ไปถูกทางก่อน (2) scan **fixed-point TP** {1000..3000 จุด} + RR grid,
บังคับ **intraday hold** (ปิดสิ้นวัน UTC ของ entry). SL คงเดิม (zone/wick). exp_R ต่อ target → target ดีสุด.

รัน: python scripts/mfe_rr_diag.py   → docs/reviews/mfe-rr-diag.md
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                       # noqa: E402

SL_GRID = [500, 750, 1000, 1500, 2000]                      # SL เป็น "จุด" (intraday: ไม่ควรห่างจนเทรดข้ามวัน)
TP_GRID = [1000, 1500, 2000, 2500, 3000]                    # TP เป็น "จุด"
REPORT = os.path.join(_ROOT, "docs", "reviews", "mfe-rr-diag.md")


def _day_end_idx(day, i):
    """index สุดท้ายของวัน UTC เดียวกับ i (intraday close)."""
    n = len(day); j = i
    while j + 1 < n and day[j + 1] == day[i]:
        j += 1
    return j


def _excursion_pts(h, l, c, i, sign, px, pt, end):
    """MFE/MAE จริง (จุด) ระหว่าง entry→สิ้นวัน — pure excursion ไม่มี SL. = ระยะ intraday ที่ราคาไปจริง."""
    mfe = 0.0; mae = 0.0
    for j in range(i + 1, end + 1):
        fav = (h[j] - px) if sign > 0 else (px - l[j])
        adv = (px - l[j]) if sign > 0 else (h[j] - px)
        mfe = max(mfe, fav); mae = max(mae, adv)
    return mfe / pt, mae / pt


def _outcome_pts(h, l, c, i, sign, px, pt, sl_pts, tp_pts, cost_pts, end):
    """pnl เป็นจุด (SL/TP fixed จุด). SL-first; ไม่ถึงในวัน → ปิด close(end). − cost."""
    sl = px - sign * sl_pts * pt; tp = px + sign * tp_pts * pt
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
            return -sl_pts - cost_pts
        if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
            return tp_pts - cost_pts
    return sign * (c[end] - px) / pt - cost_pts             # ปิดสิ้นวัน


def _entries_meanrev(h, l, c, win=20, z=1.25, sl_atr=1.5, s_stop=2.5):
    """ตรง bt_meanrev: RANGE + OU gate + zone SL. คืน (i, sign, px, sl_dist)."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); out = []; i = max(R.VOL_LOOKBACK, win) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) != "RANGE":
            i += 1; continue
        w = c[i - win + 1:i + 1]; hl = R.ou_halflife(w)
        if hl > 10:
            i += 1; continue
        m, sd = float(w.mean()), float(w.std())
        if sd <= 0:
            i += 1; continue
        zz = (float(c[i]) - m) / sd
        d = 1 if zz <= -z else -1 if zz >= z else 0
        if not d:
            i += 1; continue
        px = float(c[i]); sl_price = (m - s_stop * sd) if d > 0 else (m + s_stop * sd)
        out.append((i, d, px, max(abs(px - sl_price), sl_atr * av)))
        i += 1
    return out


def _entries_sweep(h, l, c, tm, buf_atr=0.5):
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
    out = []; i = max(R.VOL_LOOKBACK, 30) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) not in ("NEUTRAL", "RANGE") or pdh[i] != pdh[i]:
            i += 1; continue
        px = float(c[i]); d = 0; swept = 0.0
        if l[i] < pdl[i] and px > pdl[i]:
            d = 1; swept = float(l[i])
        elif h[i] > pdh[i] and px < pdh[i]:
            d = -1; swept = float(h[i])
        if not d:
            i += 1; continue
        sl_dist = abs(px - (swept - d * buf_atr * av))
        if sl_dist <= 0:
            i += 1; continue
        out.append((i, d, px, sl_dist))
        i += 1
    return out


def analyze(entries, h, l, c, day, cost, pt):
    if not entries:
        return None
    ends = [_day_end_idx(day, i) for (i, s, px, sld) in entries]
    exc = [_excursion_pts(h, l, c, i, s, px, pt, ends[k]) for k, (i, s, px, sld) in enumerate(entries)]
    mfe_a = np.array([e[0] for e in exc]); mae_a = np.array([e[1] for e in exc])
    # grid SL×TP (จุด) → expectancy จุด/ไม้ + win%
    grid = {}
    for slp in SL_GRID:
        for tpp in TP_GRID:
            rs = np.array([_outcome_pts(h, l, c, i, s, px, pt, slp, tpp, cost, ends[k])
                           for k, (i, s, px, sld) in enumerate(entries)])
            grid[(slp, tpp)] = (round(float(rs.mean()), 1), round(float((rs > 0).mean()) * 100, 1))
    best = max(grid, key=lambda k: grid[k][0])
    return {"n": len(entries),
            "mfe_med": round(float(np.median(mfe_a)), 0), "mfe_p75": round(float(np.percentile(mfe_a, 75)), 0),
            "mae_med": round(float(np.median(mae_a)), 0), "mae_p75": round(float(np.percentile(mae_a, 75)), 0),
            "grid": grid, "best": best, "best_exp": grid[best][0], "best_wr": grid[best][1]}


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

    pairs = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "EURUSD", "USDJPY", "BTCUSD", "WTIUSD"]
    res = {"mean_reversion": [], "sweep_reversal": []}
    for lg in pairs:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
        except Exception:
            info = rh = None
        if not info or rh is None or len(rh) < 800:
            continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"]
        day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
        res["mean_reversion"].append((lg, analyze(_entries_meanrev(h, l, c), h, l, c, day, cost, pt)))
        res["sweep_reversal"].append((lg, analyze(_entries_sweep(h, l, c, tm), h, l, c, day, cost, pt)))
        print(f"  {lg}: done")
    mt5.shutdown()

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(f"# Intraday fade — MFE + SL×TP grid (จุด) ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write("2 algo fade (intraday, ปิดสิ้นวัน UTC): SL+TP ควร fix กี่จุด? (SL/TP ห่างเกิน = เทรดไม่จบในวัน + ราคากลับมาโดนหน้าทุน)\n\n")
        f.write("- **MFE med/p75** = ระยะ (จุด) ที่ราคาไปถูกทาง **สูงสุด**ในวัน (median / 75th pct) — pure excursion ไม่มี SL. บอก TP ที่ realistic.\n")
        f.write("- **MAE med/p75** = ระยะ (จุด) ที่ราคาไปผิดทางสูงสุด — บอก SL floor (SL แคบกว่านี้ = โดนตัดก่อนเด้ง).\n")
        f.write("- **best SL/TP** = คู่ (จุด) ที่ expectancy (จุด/ไม้) สูงสุด จาก grid. หัก spread แล้ว. intraday (ปิดสิ้นวัน).\n\n")
        for algo, rows in res.items():
            rows = [(lg, d) for lg, d in rows if d]
            if not rows:
                continue
            f.write(f"## {algo}\n\n")
            f.write("| คู่ | n | MFE med | MFE p75 | MAE med | MAE p75 | **best SL/TP (จุด)** | exp(จุด/ไม้) | win% |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for lg, d in rows:
                bs, bt = d["best"]
                f.write(f"| {lg} | {d['n']} | {int(d['mfe_med'])} | {int(d['mfe_p75'])} | {int(d['mae_med'])} | "
                        f"{int(d['mae_p75'])} | **{bs}/{bt}** | {d['best_exp']:+.0f} | {d['best_wr']}% |\n")
            # grid heatmap ต่อคู่ flagship (XAU)
            for lg, d in rows:
                if lg not in ("XAUUSD", "BTCUSD"):
                    continue
                f.write(f"\n{lg} — expectancy (จุด/ไม้) ต่อ SL×TP:\n\n")
                f.write("| SL\\TP | " + " | ".join(f"{tp}" for tp in TP_GRID) + " |\n")
                f.write("|---|" + "|".join(["---"] * len(TP_GRID)) + "|\n")
                for slp in SL_GRID:
                    f.write(f"| **{slp}** | " + " | ".join(f"{d['grid'][(slp, tp)][0]:+.0f}" for tp in TP_GRID) + " |\n")
            f.write("\n")
    print(f"\nreport → {REPORT}")
    for algo, rows in res.items():
        for lg, d in rows:
            if d and lg in ("XAUUSD", "BTCUSD", "XAUEUR"):
                bs, bt = d["best"]
                print(f"  {algo:16s} {lg:7s} MFE med/p75 {int(d['mfe_med'])}/{int(d['mfe_p75'])}จุด · "
                      f"MAE med {int(d['mae_med'])}จุด | best SL/TP {bs}/{bt} exp {d['best_exp']:+.0f}จุด win {d['best_wr']}%")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
