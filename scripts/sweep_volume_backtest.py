#!/usr/bin/env python
"""scripts/sweep_volume_backtest.py — sweep_reversal + volume-surge entry (ทาง sweep ที่มีลุ้น) → edge โผล่มั้ย?

fade_stack พิสูจน์: กรอง price เดิม (S/R + confirm-rev) เสก edge ไม่ได้. สมมติฐานใหม่: sweep "แท้" (stop-run + absorption)
= แท่ง sweep มี **volume spike** จริง. sweep บน volume ต่ำ = noise. Filter: tick_volume[i] ≥ vk × median(vol[i-200:i]).
+ bounded intraday exit (SL/TP จุด, ปิดสิ้นวัน). scan vk × SL/TP. + **OOS 70/30** (กัน overfit จาก best-of-grid).

รัน: python scripts/sweep_volume_backtest.py   → docs/reviews/sweep-volume.md
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                       # noqa: E402
import mfe_rr_diag as M                                      # noqa: E402

VK_GRID = [0.0, 1.25, 1.5, 2.0, 2.5, 3.0]                   # 0 = ไม่กรอง volume (baseline)
SL_GRID = [500, 750, 1000, 1500]
TP_GRID = [1000, 1500, 2000, 2500, 3000]
REPORT = os.path.join(_ROOT, "docs", "reviews", "sweep-volume.md")
MIN_N = 40


def _sweep_vol_entries(h, l, c, tm, vol, vk, buf_atr=0.5):
    """sweep entry + filter volume surge (vol[i] ≥ vk×median200). vk=0 → ไม่กรอง. คืน (i,d,px,sld)."""
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
    vmed = np.zeros(n)
    for k in range(200, n):
        vmed[k] = np.median(vol[k - 200:k]) or 1.0
    out = []; i = max(R.VOL_LOOKBACK, 200, 30) + 2
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
        if vk > 0 and (vmed[i] <= 0 or vol[i] < vk * vmed[i]):    # volume ไม่ถึง → ไม่ใช่ sweep แท้ → skip
            i += 1; continue
        sl_dist = abs(px - (swept - d * buf_atr * av))
        if sl_dist <= 0:
            i += 1; continue
        out.append((i, d, px, sl_dist))
        i += 1
    return out


def _exp(entries, h, l, c, day, pt, cost, slp, tpp, lo=0.0, hi=1.0):
    """expectancy (จุด) ของ entries ที่ index อยู่ช่วง [lo,hi) ของข้อมูล (สำหรับ OOS split)."""
    n = len(c); a = int(n * lo); b = int(n * hi)
    sub = [(i, d, px, sld) for (i, d, px, sld) in entries if a <= i < b]
    if not sub:
        return None, 0
    ends = [M._day_end_idx(day, i) for (i, d, px, sld) in sub]
    rs = np.array([M._outcome_pts(h, l, c, i, s, px, pt, slp, tpp, cost, ends[k])
                   for k, (i, s, px, sld) in enumerate(sub)])
    return (round(float(rs.mean()), 1), round(float((rs > 0).mean()) * 100, 1)), len(sub)


def analyze(h, l, c, tm, vol, day, pt, cost):
    """ต่อ vk: best SL/TP บน in-sample(70%) → วัดซ้ำ OOS(30%). คืน dict vk→..."""
    out = {}
    for vk in VK_GRID:
        ent = _sweep_vol_entries(h, l, c, tm, vol, vk)
        best = None
        for slp in SL_GRID:
            for tpp in TP_GRID:
                r, nn = _exp(ent, h, l, c, day, pt, cost, slp, tpp, 0.0, 0.7)   # in-sample
                if r and nn >= MIN_N and (best is None or r[0] > best[1]):
                    best = ((slp, tpp), r[0], r[1], nn)
        if not best:
            out[vk] = None; continue
        (slp, tpp), ise, iwr, inn = best
        oos, onn = _exp(ent, h, l, c, day, pt, cost, slp, tpp, 0.7, 1.0)        # OOS ที่ SL/TP เดียวกัน
        full, fnn = _exp(ent, h, l, c, day, pt, cost, slp, tpp, 0.0, 1.0)
        out[vk] = {"sltp": (slp, tpp), "is_exp": ise, "is_wr": iwr, "is_n": inn,
                   "oos_exp": oos[0] if oos else None, "oos_wr": oos[1] if oos else None, "oos_n": onn,
                   "full_exp": full[0] if full else None, "full_n": fnn, "n_total": len(ent)}
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

    pairs = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY"]
    res = []
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
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float)
        tm = rh["time"]; vol = rh["tick_volume"].astype(float)
        day = np.array([datetime.fromtimestamp(int(t), timezone.utc).toordinal() for t in tm])
        res.append((lg, analyze(h, l, c, tm, vol, day, pt, cost)))
        print(f"  {lg}: done")
    mt5.shutdown()

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(f"# Sweep + volume-surge — edge hunt ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write("sweep แท้ = แท่ง sweep volume ≥ vk×median200. best SL/TP เลือกบน **in-sample 70%** → วัดซ้ำ **OOS 30%** (กัน overfit).\n")
        f.write("edge จริง = **OOS exp > 0** (ไม่ใช่แค่ in-sample). vk=0 = ไม่กรอง volume (baseline).\n\n")
        for lg, d in res:
            f.write(f"## {lg}\n\n")
            f.write("| vk | SL/TP | IS exp/wr/n | **OOS exp/wr/n** | full exp/n | sweep ทั้งหมด |\n")
            f.write("|---|---|---|---|---|---|\n")
            for vk in VK_GRID:
                r = d.get(vk)
                if not r:
                    f.write(f"| {vk} | — | n<{MIN_N} | — | — | — |\n"); continue
                oe = f"{r['oos_exp']:+.0f}/{r['oos_wr']}%/{r['oos_n']}" if r['oos_exp'] is not None else "—"
                f.write(f"| {vk} | {r['sltp'][0]}/{r['sltp'][1]} | {r['is_exp']:+.0f}/{r['is_wr']}%/{r['is_n']} | "
                        f"**{oe}** | {r['full_exp']:+.0f}/{r['full_n']} | {r['n_total']} |\n")
            f.write("\n")
    print(f"\nreport → {REPORT}\n")
    for lg, d in res:
        # ตัวที่ OOS ดีสุด
        cand = [(vk, r) for vk, r in d.items() if r and r["oos_exp"] is not None]
        if cand:
            vk, r = max(cand, key=lambda t: t[1]["oos_exp"])
            print(f"  {lg:7s} best-OOS vk{vk} SL/TP {r['sltp'][0]}/{r['sltp'][1]} | "
                  f"IS {r['is_exp']:+.0f} -> OOS {r['oos_exp']:+.0f}จุด win{r['oos_wr']}% (n{r['oos_n']})")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
