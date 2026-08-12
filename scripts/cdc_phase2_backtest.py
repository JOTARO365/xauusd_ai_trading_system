"""scripts/cdc_phase2_backtest.py — Phase 2: entry filter (Fib/RSI pullback) + Turtle pyramid sim.

โฉลก wave-2/4 entry = เข้าตอน "ย่อ" ในเทรนด์ (Fib 0.382-0.618 / RSI<thr) ไม่ไล่ราคา.
Part A: เทียบ cdc long baseline vs +filter (event-driven entry: bull + ย่อ → เข้า, flip → ออก) — R-multiple.
Part B: Turtle pyramid — เติม 1 unit ทุก +½N จนถึง 4 units → total-R (แสดง "big order" ขยายกำไรตัวชนะ).
รัน: python scripts/cdc_phase2_backtest.py
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import backtest_all as B                                    # noqa: E402
import regime_lib as R                                      # noqa: E402


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = np.full(len(c), np.nan); rd = np.full(len(c), np.nan)
    if len(c) > n:
        ru[n] = up[1:n + 1].mean(); rd[n] = dn[1:n + 1].mean()
        for i in range(n + 1, len(c)):
            ru[i] = (ru[i - 1] * (n - 1) + up[i]) / n
            rd[i] = (rd[i - 1] * (n - 1) + dn[i]) / n
    rs = ru / np.where(rd == 0, np.nan, rd)
    return 100.0 - 100.0 / (1.0 + rs)


def bt_cdc_f(h, l, c, cost_price, sl_atr=2.0, mode="long", filt=None, pb_lb=20, pb_min=0.005, rsi_max=45):
    """event-driven entry: bull + filter ผ่าน → เข้า; zone flip → ออก. filt: None/'rsi'/'pullback'/'both'.
    คืน (list R, list entry_index) — entry_index ใช้ต่อ pyramid sim."""
    fast, slow = R.cdc_zone(c)
    atr = R.atr(h, l, c); rsi = _rsi(c)
    n = len(c); tr = []; ei = []; pos = 0; entry = 0.0; risk = 0.0
    for i in range(30, n):
        if pos != 0 and risk > 0 and pos * (c[i] - entry) <= -risk:
            tr.append(-1.0 - cost_price / risk); pos = 0
        bull = fast[i] > slow[i]
        if pos == 0:
            want = 1 if bull else (-1 if mode == "both" else 0)
            if want == 0:
                continue
            ok = True
            if filt in ("rsi", "both"):
                rv = rsi[i]
                ok = ok and (rv == rv) and (rv < rsi_max if want > 0 else rv > 100 - rsi_max)
            if filt in ("pullback", "both"):
                if want > 0:
                    hh = float(h[max(0, i - pb_lb):i].max()) if i > 0 else c[i]
                    ok = ok and (c[i] <= hh * (1 - pb_min))       # ย่อจาก high ล่าสุด ≥ pb_min
                else:
                    ll = float(l[max(0, i - pb_lb):i].min()) if i > 0 else c[i]
                    ok = ok and (c[i] >= ll * (1 + pb_min))
            if not ok:
                continue
            pos = want; entry = c[i]; ei.append(i)
            av = float(atr[i]) if atr[i] == atr[i] else 0.0
            risk = sl_atr * av if av > 0 else 0.0
        else:
            bull_now = fast[i] > slow[i]
            flip = (pos > 0 and not bull_now) or (pos < 0 and bull_now)
            if flip:
                tr.append((pos * (c[i] - entry) - cost_price) / risk if risk > 0 else 0.0)
                pos = 0
    return tr, ei


def pyramid_totalR(h, l, c, cost_price, sl_atr=2.0, add_half_n=0.5, max_units=4):
    """Turtle pyramid บน cdc long: เข้า 1 unit ตอน bull-flip, เติม 1 unit ทุก +½N, ถึง 4 units, ออกหมดตอน flip.
    คืน list total-R ต่อ campaign (R รวมทุก unit / risk เริ่ม) — เทียบ single-unit."""
    fast, slow = R.cdc_zone(c); atr = R.atr(h, l, c)
    n = len(c); out = []; pos = 0
    units = []           # (entry_px,) ต่อ unit
    n0 = 0.0; risk0 = 0.0
    for i in range(30, n):
        bull = fast[i] > slow[i]
        if pos == 0:
            if bull:
                av = float(atr[i]) if atr[i] == atr[i] else 0.0
                if av <= 0:
                    continue
                pos = 1; units = [float(c[i])]; n0 = av; risk0 = sl_atr * av
        else:
            # เติม unit ทุก +½N จาก entry unit ล่าสุด
            if len(units) < max_units and (c[i] - units[-1]) >= add_half_n * n0:
                units.append(float(c[i]))
            if not bull:                                     # flip → ปิดหมด
                exitpx = float(c[i])
                pnl = sum((exitpx - u) for u in units) - cost_price * len(units)
                out.append(pnl / risk0 if risk0 > 0 else 0.0)
                pos = 0; units = []
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
    cost_of = lambda lg: (_sc.cost_pips(lg) if _sc else None) or 30.0   # noqa: E731

    print("=== Part A: entry filter (cdc long, D1) ===")
    hdr = f"{'คู่':8s} {'variant':16s} {'exp_R':>7s} {'t':>6s} {'OOS':>7s} {'WR':>5s} {'n':>4s}"
    print(hdr); print("-" * len(hdr))
    for lg in ["XAUUSD", "XAUEUR", "BTCUSD"]:
        sym = bm.get(lg, lg); mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym); rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        if not info or rd is None or len(rd) < 300:
            print(f"{lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg) * pt
        h = rd["high"].astype(float); l = rd["low"].astype(float); c = rd["close"].astype(float)
        for name, kw in [("baseline", {}), ("rsi45", {"filt": "rsi", "rsi_max": 45}),
                         ("rsi40", {"filt": "rsi", "rsi_max": 40}), ("pullback", {"filt": "pullback"}),
                         ("rsi45+pull", {"filt": "both", "rsi_max": 45})]:
            trs, _ = bt_cdc_f(h, l, c, cost, **kw)
            s = B._stats(trs)
            if s:
                print(f"{lg:8s} {name:16s} {s['exp_R']:+7.3f} {s['t']:+6.2f} {s['oos']:+7.3f} {s['wr']:5.1f} {s['n']:4d}")
            else:
                print(f"{lg:8s} {name:16s}   n<20")
        print()

    print("=== Part B: Turtle pyramid vs single-unit (total-R/campaign) ===")
    print(f"{'คู่':8s} {'mode':12s} {'sum_R':>8s} {'mean_R':>7s} {'n_camp':>6s}")
    print("-" * 44)
    for lg in ["XAUUSD", "XAUEUR", "BTCUSD"]:
        sym = bm.get(lg, lg); mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym); rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        if not info or rd is None:
            continue
        pt = float(info.point); cost = cost_of(lg) * pt
        h = rd["high"].astype(float); l = rd["low"].astype(float); c = rd["close"].astype(float)
        single, _ = bt_cdc_f(h, l, c, cost)                  # single-unit campaigns (R ต่อ campaign)
        pyr = pyramid_totalR(h, l, c, cost)
        for name, arr in [("single (1u)", single), ("pyramid (≤4u)", pyr)]:
            a = np.array(arr, float)
            if len(a):
                print(f"{lg:8s} {name:12s} {a.sum():+8.2f} {a.mean():+7.3f} {len(a):6d}")
        print()
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
