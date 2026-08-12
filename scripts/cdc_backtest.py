"""scripts/cdc_backtest.py — validate CDC Action Zone (อ.โฉลก) เทียบ tsmom_d1 บนทอง+คู่หลัก (Phase 1).

CDC Action Zone: ohlc4 -> EMA2 -> Fast EMA12 / Slow EMA26. bull = Fast>Slow.
เข้า long ตอน bull-flip, ออกตอน bear-flip (zone แดง) = trend-follow ถือยาว (let winners run).
R-normalized ด้วย disaster stop 2N (Turtle) = เทียบ exp_R กับ tsmom (3N) ได้ตรง (return/หน่วยเสี่ยง).

modes: long = long-only (ทองเทรนด์ขึ้น, SELL leg เดิม −EV) · both = symmetric · long+W1 = long เมื่อ W1 ก็ bull.
รัน: python scripts/cdc_backtest.py
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import backtest_all as B                                    # noqa: E402  (bt_tsmom, _stats, _pc)
import regime_lib as R                                      # noqa: E402


def _ema(x, n):
    a = 2.0 / (n + 1.0)
    e = np.empty_like(x, dtype=float); e[0] = x[0]
    for i in range(1, len(x)):
        e[i] = x[i] * a + e[i - 1] * (1.0 - a)
    return e


def cdc_zone(o, h, l, c, src="close"):
    """คืน (fast, slow) ของ CDC Action Zone. bull = fast>slow.
    src='close' (default) = ใช้ close (bars ของ algo ไม่มี open → parity live↔backtest);
    src='ohlc4' = สูตรเดิม อ.โฉลก (EMA2 smooth อยู่แล้ว ต่างกันน้อยมาก)."""
    base = c if src == "close" else (o + h + l + c) / 4.0
    ap = _ema(base, 2)
    return _ema(ap, 12), _ema(ap, 26)


def _wk_bull_map(d1_time, wk_time, wk_o, wk_h, wk_l, wk_c):
    """weekly bull (Fast>Slow) map ลง D1 bar — ใช้แท่ง W1 ที่ปิดก่อน D1 bar (ไม่ look-ahead)."""
    wf, ws = cdc_zone(wk_o, wk_h, wk_l, wk_c)
    wb = (wf > ws).astype(int)
    idx = np.clip(np.searchsorted(wk_time, d1_time, side="right") - 1, 0, len(wb) - 1)
    return wb[idx].astype(bool)


def bt_cdc(o, h, l, c, cost_price, sl_atr=2.0, mode="long", wk_bull=None):
    """R-multiple list. exit-on-flip + disaster stop 2N. mirror bt_tsmom (เทียบตรง)."""
    fast, slow = cdc_zone(o, h, l, c)
    atr = R.atr(h, l, c)
    tr = []; pos = 0; entry = 0.0; risk = 0.0
    start = 30
    for i in range(start, len(c)):
        if pos != 0 and risk > 0:                          # disaster stop (close-based) ก่อนเช็ค flip
            if pos * (c[i] - entry) <= -risk:
                tr.append(-1.0 - cost_price / risk); pos = 0
        bull = fast[i] > slow[i]
        want = 1 if bull else (-1 if mode == "both" else 0)
        if wk_bull is not None:                            # W1 filter
            if want > 0 and not wk_bull[i]:
                want = 0
            if want < 0 and wk_bull[i]:
                want = 0
        if want != pos:
            if pos != 0 and risk > 0:
                tr.append((pos * (c[i] - entry) - cost_price) / risk)
            pos = want; entry = c[i]
            av = float(atr[i]) if atr[i] == atr[i] else 0.0
            risk = sl_atr * av if av > 0 else 0.0
    return tr


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

    pairs = ["XAUUSD", "XAUEUR", "BTCUSD", "WTIUSD", "XAGUSD"]
    print("CDC Action Zone (อ.โฉลก) vs tsmom_d1 — D1, cost-adj, OOS70/30, R-norm\n")
    hdr = f"{'คู่':8s} {'variant':14s} {'exp_R':>7s} {'t':>6s} {'OOS':>7s} {'WR':>5s} {'n':>5s}  verdict"
    print(hdr); print("-" * len(hdr))
    for lg in pairs:
        sym = bm.get(lg, lg)
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        rw = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_W1, 0, 1500)
        if not info or rd is None or len(rd) < 300:
            print(f"{lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg)
        o = rd["open"].astype(float); h = rd["high"].astype(float)
        l = rd["low"].astype(float); c = rd["close"].astype(float); tm = rd["time"].astype(np.int64)
        wkb = None
        if rw is not None and len(rw) > 40:
            wkb = _wk_bull_map(tm, rw["time"].astype(np.int64), rw["open"].astype(float),
                               rw["high"].astype(float), rw["low"].astype(float), rw["close"].astype(float))
        variants = [
            ("cdc long", bt_cdc(o, h, l, c, cost * pt, mode="long")),
            ("cdc both", bt_cdc(o, h, l, c, cost * pt, mode="both")),
            ("cdc long+W1", bt_cdc(o, h, l, c, cost * pt, mode="long", wk_bull=wkb) if wkb is not None else None),
            ("tsmom (base)", B.bt_tsmom(h, l, c, cost * pt)),
        ]
        for name, tr in variants:
            if tr is None:
                continue
            s = B._stats(tr)
            if not s:
                print(f"{lg:8s} {name:14s}   n<20"); continue
            v = "+EV" if (s["exp_R"] > 0 and s["oos"] >= 0 and s["n"] >= B.MIN_N) else "-EV"
            rob = " ROBUST" if (v == "+EV" and abs(s["t"]) >= 2.0) else ""
            print(f"{lg:8s} {name:14s} {s['exp_R']:+7.3f} {s['t']:+6.2f} {s['oos']:+7.3f} "
                  f"{s['wr']:5.1f} {s['n']:5d}  {v}{rob}")
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
