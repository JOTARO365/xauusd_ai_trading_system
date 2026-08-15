#!/usr/bin/env python
"""scripts/pullback_buy_backtest.py — dip-buyer (trend-pullback บน H1, SL แคบ) → validate ก่อน live.

ปัญหา (2026-08-14): cdc = dip-buyer ตัวเดียวที่ live แต่ SL 2N = 15.5% risk/ไม้ (gold ATR_D1 $96) → guard block.
เข้า dip อย่าง 4310 ไม่ได้. ต้อง dip-buyer **SL แคบ** ที่ risk ~1-2% เข้าได้จริง.

concept (long-only, เข้า METALS_LONG_ONLY):
  - HTF filter: D1 ขาขึ้น (close_D1 > EMA_D1(n)) — ซื้อดิพเฉพาะในเทรนด์ขึ้น ไม่รับมีดตลาดหมี
  - pullback+reclaim: ราคาย่อหลุด EMA20-H1 แล้ว **ปิดกลับเหนือ EMA20** (จุดกลับของดิพ = trigger, causal)
  - SL แคบ: ใต้ก้นดิพ (swing-low k แท่ง) − buffer, cap ที่ SL_CAP×ATR_H1 (กัน SL โต) = risk เล็ก
  - TP: RR × SL (scan). exit SL-first · cost-adj · OOS 70/30.

รัน: python scripts/pullback_buy_backtest.py   → docs/reviews/pullback-buy.md
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                       # noqa: E402
from agents import sr_entry_gate as SR                        # noqa: E402  (swing/cluster S/R strength)

SR_LOOKBACK = 60             # หา swing pivot กี่แท่ง (support ladder)
SR_PIVOT = 3
SR_CLUSTER_ATR = 0.3        # merge แนวห่าง ≤ นี้×ATR
SR_MIN_TOUCHES = 2          # support ต้องโดนแตะ ≥ นี้ (แข็ง) ถึงเข้า
SR_DIST_ATR = 0.5           # ก้นดิพต้องอยู่ ≤ นี้×ATR จาก support แข็ง

EMA_FAST = 20                # H1 pullback EMA
D1_EMA = 20                  # D1 trend filter
SWING_LB = 8                 # ก้นดิพ = min low k แท่ง
SL_BUF_ATR = 0.25            # buffer ใต้ swing low
SL_CAP_ATR = 2.0             # cap SL ที่ นี้×ATR_H1 (กัน SL โต = risk คุมได้)
RR_GRID = [1.5, 2.0, 2.5, 3.0]
MAX_HOLD = 72                # H1 ~3 วัน
REPORT = os.path.join(_ROOT, "docs", "reviews", "pullback-buy.md")
MIN_N = 60


def _ema(x, n):
    e = np.zeros_like(x, float); e[0] = x[0]; k = 2.0 / (n + 1)
    for i in range(1, len(x)):
        e[i] = x[i] * k + e[i - 1] * (1 - k)
    return e


def _d1_up_map(h1_time, d1_time, d1_close):
    """คืน bool array ต่อ H1 bar: D1 ขาขึ้น (close_D1 > EMA_D1) ณ D1 แท่งที่ปิดก่อน H1 bar (causal, -2 กัน look-ahead)."""
    de = _ema(d1_close, D1_EMA)
    up = (d1_close > de).astype(int)
    idx = np.clip(np.searchsorted(d1_time, h1_time, side="right") - 2, 0, len(up) - 1)
    return up[idx].astype(bool)


def _sr_support_ok(h, l, i, swing_low, av):
    """True = ก้นดิพลงมาที่ 'แนวรับแข็ง' จริง (swing-low cluster touch≥SR_MIN_TOUCHES ใกล้ ≤SR_DIST_ATR×ATR)."""
    _, sup = SR._swing_levels(h, l, i, SR_LOOKBACK, SR_PIVOT)
    if not sup:
        return False
    tol = SR_CLUSTER_ATR * av
    for lv, ct in SR._cluster(sup, tol):
        if ct >= SR_MIN_TOUCHES and abs(lv - swing_low) <= SR_DIST_ATR * av:
            return True
    return False


def _entries(h, l, c, tm, d1_up, pt, sr_filter=False):
    """long-only pullback+reclaim. sr_filter=True → เข้าเฉพาะดิพที่แนวรับแข็ง. คืน (i, px, sl_dist)."""
    ema = _ema(c, EMA_FAST); atr = R.atr(h, l, c)
    n = len(c); out = []; i = max(EMA_FAST, SWING_LB, SR_LOOKBACK, R.VOL_LOOKBACK) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or not d1_up[i]:
            i += 1; continue
        # reclaim: แท่งก่อนปิด ≤ EMA (ดิพ) · แท่งนี้ปิด > EMA (กลับขึ้น)
        if not (c[i] > ema[i] and c[i - 1] <= ema[i - 1]):
            i += 1; continue
        px = float(c[i])
        swing_low = float(l[i - SWING_LB:i + 1].min())
        if sr_filter and not _sr_support_ok(h, l, i, swing_low, av):    # analyst-style: เฉพาะแนวรับแข็ง
            i += 1; continue
        sl_dist = (px - swing_low) + SL_BUF_ATR * av
        sl_dist = min(sl_dist, SL_CAP_ATR * av)             # cap = risk คุมได้
        if sl_dist <= 0:
            i += 1; continue
        out.append((i, px, sl_dist))
        i += 1
    return out


def _resolve(h, l, c, i, px, sl_dist, rr, cost_price, mh):
    n = len(c); end = min(i + mh, n - 1)
    sl = px - sl_dist; tp = px + rr * sl_dist
    for j in range(i + 1, end + 1):
        if l[j] <= sl:
            return -1.0 - cost_price / sl_dist
        if h[j] >= tp:
            return rr - cost_price / sl_dist
    return (c[end] - px) / sl_dist - cost_price / sl_dist


def _agg(rs):
    a = np.array(rs, float); n = len(a)
    if n < 20:
        return None
    sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / np.sqrt(n)) if sd else 0.0
    return {"exp": round(float(a.mean()), 3), "t": round(float(t), 2),
            "wr": round(float((a > 0).mean()) * 100, 1), "n": n}


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

    pairs = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "BTCUSD", "WTIUSD"]
    rows = []
    for lg in pairs:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
            rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        except Exception:
            info = rh = rd = None
        if not info or rh is None or len(rh) < 2000 or rd is None or len(rd) < 100:
            print(f"  {lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float)
        tm = rh["time"].astype(np.int64)
        d1_up = _d1_up_map(tm, rd["time"].astype(np.int64), rd["close"].astype(float))
        n = len(c)

        def scan(ents):
            if len(ents) < 20:
                return None
            variants = {}
            for rr in RR_GRID:
                isr = [_resolve(h, l, c, i, px, sld, rr, cost * pt, MAX_HOLD)
                       for (i, px, sld) in ents if i < int(n * 0.7)]
                oor = [_resolve(h, l, c, i, px, sld, rr, cost * pt, MAX_HOLD)
                       for (i, px, sld) in ents if i >= int(n * 0.7)]
                variants[rr] = {"is": _agg(isr), "oos": _agg(oor)}
            cand = [(rr, v) for rr, v in variants.items() if v["is"] and v["is"]["n"] >= 20]
            best = max(cand, key=lambda t: t[1]["is"]["exp"])[0] if cand else RR_GRID[1]
            return {"n": len(ents), "best_rr": best, "variants": variants,
                    "sl_med": float(np.median([s for _, _, s in ents]))}

        plain = scan(_entries(h, l, c, tm, d1_up, pt, sr_filter=False))
        srf = scan(_entries(h, l, c, tm, d1_up, pt, sr_filter=True))
        rows.append((lg, plain, srf))

        def fmt(r):
            if not r:
                return "n<20"
            b = r["variants"][r["best_rr"]]; o = b["oos"]
            return f"n={r['n']} RR{r['best_rr']} OOS {o['exp'] if o else '—'}/{o['t'] if o else '—'}" if o else f"n={r['n']} —"
        print(f"  {lg:7s} | plain {fmt(plain):32s} | +S/R {fmt(srf)}")
    mt5.shutdown()

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(f"# Pullback-buy (dip-buyer, tight SL) — validation ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write("long-only · D1 ขาขึ้น + ราคา reclaim EMA20-H1 หลังย่อ · SL = ก้นดิพ (cap %.1f×ATR_H1) · OOS 70/30.\n" % SL_CAP_ATR)
        f.write("edge จริง = **OOS exp>0 + t≥2 + n≥%d**. SL med = ดูว่า risk เล็กจริงมั้ย (เทียบ cdc 2N=$192).\n\n" % MIN_N)
        f.write("**เทียบ plain (pullback ล้วน) vs +S/R (เข้าเฉพาะดิพที่แนวรับแข็ง touch≥%d = analyst-style):**\n\n" % SR_MIN_TOUCHES)

        def cell(r):
            if not r:
                return "n<20", "—", "—"
            b = r["variants"][r["best_rr"]]
            isf = f"{b['is']['exp']:+.3f}/{b['is']['t']:+.2f}/{b['is']['n']}" if b['is'] else "—"
            oof = f"{b['oos']['exp']:+.3f}/{b['oos']['t']:+.2f}/{b['oos']['n']}" if b['oos'] else "—"
            return f"n{r['n']} RR{r['best_rr']} SL{r['sl_med']:.1f}", isf, oof
        f.write("| คู่ | | n/RR/SL | IS exp/t/n | **OOS exp/t/n** |\n|---|---|---|---|---|\n")
        for lg, plain, srf in rows:
            for tag, r in (("plain", plain), ("**+S/R**", srf)):
                a, i_, o = cell(r)
                f.write(f"| {lg} | {tag} | {a} | {i_} | **{o}** |\n")
    print(f"\nreport → {REPORT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
