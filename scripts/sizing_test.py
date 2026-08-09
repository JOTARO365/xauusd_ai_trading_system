"""scripts/sizing_test.py — A2: volatility-target / fixed-fractional sizing (user 08-09, quant-sat ch13).

ปัญหา: live = fixed lot (0.02) + structural SL กว้าง → $ risk แกว่งตาม SL (ไม้ SL กว้าง=เสี่ยงเยอะ)
→ DD สูง (survival_sim 46-83%). fixed-fractional (risk %คงที่/ไม้) = size ∝ 1/SL → risk คงที่ → DD ต่ำลง.

เทส: gold momentum trades จริง (bt_momentum config) เก็บ (R, sl_dist) → compound equity 3 แบบ sizing
เทียบ Sharpe / maxDD / final. read-only. 0 token. standalone: python scripts/sizing_test.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

THB_PER_USD_PER_LOT = 3305.7
MIN_LOT, MAX_LOT = 0.01, 0.30
CONTRACT = 100.0


def _gen_trades():
    """gold momentum (bt_momentum config: brk20, ATR SL 1.5, RR2, trend-gate, non-overlap).
    คืน list ของ (ts_index, R, sl_dist_price)."""
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    import scripts.regime_lib as R
    mt5.initialize()
    bm = _broker_map() or {}
    sym = bm.get("XAUUSD", "XAUUSD"); mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
    si = mt5.symbol_info(sym); pt = si.point
    try:
        from agents import shadow_cost as sc; cost = float(sc.cost_price(sym))
    except Exception:
        cost = si.spread * pt
    mt5.shutdown()
    h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float)
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); brk = 20; rr = 2.0; sl_atr = 1.5; mh = 120
    out = []; i = max(R.VOL_LOOKBACK, brk) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        sl_dist = sl_atr * av                       # SL distance (price units)
        sl = px - d * sl_dist; tp = px + d * sl_dist * rr
        end = min(i + mh, n - 1); R_out = None; ei = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                R_out = -1.0 - cost / sl_dist; ei = j; break
            if (h[j] >= tp) if d > 0 else (l[j] <= tp):
                R_out = rr - cost / sl_dist; ei = j; break
        if R_out is None:
            R_out = d * (c[end] - px) / sl_dist - cost / sl_dist
        out.append((i, R_out, sl_dist)); i = ei + 1
    return out


def _sim(trades, mode, e0, risk_pct=0.01, fixed_lot=0.02):
    """compound equity. mode: 'fixed_lot' | 'fixed_frac' | 'vol_target'(=fixed_frac บน ATR-SL เดียวกัน)."""
    eq = e0; curve = [e0]; peak = e0; maxdd = 0.0; rets = []
    for _, Rr, sl_dist in trades:
        risk_thb_1lot = sl_dist * THB_PER_USD_PER_LOT     # ขาดทุน(บาท)/1.0 lot ถ้าโดน SL
        if mode == "fixed_lot":
            lot = fixed_lot
        else:                                             # fixed-fractional / vol-target: risk %คงที่
            lot = (risk_pct * eq) / risk_thb_1lot if risk_thb_1lot > 0 else MIN_LOT
        lot = min(max(round(lot / 0.01) * 0.01, MIN_LOT), MAX_LOT)
        pnl = Rr * lot * risk_thb_1lot                    # R × risk(บาท ต่อ lot นั้น)
        prev = eq; eq += pnl; curve.append(eq)
        rets.append(pnl / prev if prev > 0 else 0.0)
        peak = max(peak, eq); dd = (peak - eq) / peak if peak > 0 else 0
        maxdd = max(maxdd, dd)
        if eq <= 0:
            eq = 0.0; break
    a = np.array(rets, float); sd = a.std(ddof=1) if len(a) > 1 else 0
    sharpe = float(a.mean() / sd) * math.sqrt(len(a)) if sd > 0 else 0.0   # per-trade Sharpe ann/ไม่ปรับ (เทียบกันได้)
    return {"final": round(eq), "maxdd": round(maxdd * 100, 1), "sharpe": round(sharpe, 2),
            "ret_pct": round((eq / e0 - 1) * 100, 1)}


def run(e0=44000.0):
    tr = _gen_trades()
    print("=" * 72)
    print("A2 SIZING TEST · gold momentum (bt_momentum config) · n=%d · start %.0f฿" % (len(tr), e0))
    print("=" * 72)
    print("%-22s %10s %8s %8s %8s" % ("sizing", "final฿", "ret%", "maxDD%", "Sharpe*"))
    for mode, lbl in [("fixed_lot", "fixed lot 0.02 (live)"),
                      ("fixed_frac", "fixed-fractional 1%"),
                      ("vol_target", "vol-target (=FF/ATR)")]:
        s = _sim(tr, mode, e0)
        print("%-22s %10d %8.1f %8.1f %8.2f" % (lbl, s["final"], s["ret_pct"], s["maxdd"], s["sharpe"]))
    print("=" * 72)
    print("Sharpe* = per-trade Sharpe × √n (เทียบกันได้ ไม่ใช่ annualised). SL=1.5×ATR ทุก mode.")
    print("fixed-fractional/vol-target: risk %คงที่/ไม้ → คาด maxDD ต่ำกว่า fixed-lot, Sharpe สูงกว่า.")
    # เทสทุนเล็กด้วย (min-lot floor เด่น)
    print("\nทุนเล็ก 3000฿:")
    for mode, lbl in [("fixed_lot", "fixed lot 0.02"), ("fixed_frac", "fixed-fractional 1%")]:
        s = _sim(tr, mode, 3000.0)
        print("  %-20s final=%d maxDD=%.1f%% Sharpe=%.2f" % (lbl, s["final"], s["maxdd"], s["sharpe"]))


if __name__ == "__main__":
    run()
