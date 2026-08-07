#!/usr/bin/env python
"""scripts/sr_fade_backtest.py — backtest ของ algo sr_fade (S/R Book fade) ก่อนตัดสินใจ LIVE.

กฎ quant (เหมือน smc_backtest): causal (signal ที่ i จากแท่งปิด, resolve จาก i+1), SL-first, หัก cost,
trade ไม่ overlap (ข้ามไปหลังไม้ปิด), OOS split (70/30), t-stat, MIN_N. ใช้ compute_cluster_map ตัวเดียว
กับ SRFadeAlgo (S/R source เดียว) — ไม่ drift จาก logic จริง.

รัน:  python scripts/sr_fade_backtest.py            # ทอง H1
      python scripts/sr_fade_backtest.py --all      # ทุกคู่ (ต้อง MT5 login)
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import regime_lib as R                                   # noqa: E402
from agents.cluster_map import compute_cluster_map        # noqa: E402

MAX_HOLD = 240
MIN_N = 100
TOL_ATR, MIN_TOUCH, BUF_ATR, RR = 0.4, 3, 0.5, 1.5


def run_sr_fade(h, l, c, cost, point, rr=RR, min_touch=MIN_TOUCH, tol_atr=TOL_ATR, buf_atr=BUF_ATR, confirm=False):
    """คืน list ของ R ต่อไม้ (non-overlapping). variant params: rr / min_touch / tol / confirm (rejection candle)."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    n = len(c); trades = []
    i = max(R.VOL_LOOKBACK + 40, 210)
    while i < n - 1:
        reg = R.detect_regime(er[i], adx[i], vp[i])
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if reg not in ("NEUTRAL", "RANGE") or av <= 0:
            i += 1; continue
        w0 = max(0, i - 599)                              # 600-bar window = ตรงกับที่ production ป้อน (_BARS_COUNT)
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            i += 1; continue
        px = float(c[i]); mom = cm.get("momentum"); sup, res = cm.get("support"), cm.get("resistance")
        rng = float(h[i] - l[i]) or 1e-9
        rej_buy = (c[i] - l[i]) / rng >= 0.6              # แท่งปฏิเสธล่าง (ปิดครึ่งบน) = bounce ยืนยัน
        rej_sell = (h[i] - c[i]) / rng >= 0.6
        d = zone = None
        if (sup and sup["touches"] >= min_touch and px >= sup["level"] and sup["dist_atr"] <= tol_atr
                and mom != "down" and (not confirm or rej_buy)):
            d, zone = "BUY", sup["level"]
        elif (res and res["touches"] >= min_touch and px <= res["level"] and res["dist_atr"] <= tol_atr
                and mom != "up" and (not confirm or rej_sell)):
            d, zone = "SELL", res["level"]
        if d is None:
            i += 1; continue
        sign = 1 if d == "BUY" else -1
        sl_price = zone - sign * buf_atr * av; sl_pips = abs(px - sl_price) / point
        if sl_pips <= 0:
            i += 1; continue
        sl = px - sign * sl_pips * point; tp = px + sign * sl_pips * rr * point
        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            hit_sl = (l[j] <= sl) if sign > 0 else (h[j] >= sl)
            hit_tp = (h[j] >= tp) if sign > 0 else (l[j] <= tp)
            if hit_sl:                                    # SL-first (conservative)
                r_out, exit_i = -1.0 - cost / sl_pips, j; break
            if hit_tp:
                r_out, exit_i = rr - cost / sl_pips, j; break
        if r_out is None:
            r_out = sign * (c[end] - px) / (sl_pips * point) - cost / sl_pips
        trades.append(r_out)
        i = exit_i + 1                                    # non-overlap: ข้ามไปหลังไม้ปิด
    return trades


def _stats(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0}
    arr = np.array(trades, float)
    wr = round(float((arr > 0).mean()) * 100, 1)
    exp_r = float(arr.mean()); sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = exp_r / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "wr": wr, "exp_R": round(exp_r, 4), "sum_R": round(float(arr.sum()), 1), "t": round(t, 2)}


def _report(label, trades):
    s = _stats(trades)
    if not s["n"]:
        print(f"{label:16s} n=0"); return
    # OOS: 70/30
    k = int(len(trades) * 0.7)
    isr, oos = _stats(trades[:k]), _stats(trades[k:])
    flag = "PASS" if (s["n"] >= MIN_N and s["exp_R"] > 0 and s["t"] > 2 and oos.get("exp_R", -1) > 0) else "—"
    print(f"{label:16s} n={s['n']:4d}  WR {s['wr']:5}%  exp_R {s['exp_R']:+.4f}  t {s['t']:+.2f}  sumR {s['sum_R']:+7.1f}  "
          f"| OOS exp_R {oos.get('exp_R','—')}  [{flag}]")


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    print(f"\n=== sr_fade backtest (S/R fade · causal · SL-first · cost-adj · OOS70/30 · MIN_N={MIN_N}) ===")
    print("verdict PASS = n≥100 + exp_R>0 + t>2 + OOS exp_R>0\n")
    # variant grid — ปรับ sr_fade หา +EV: RR สูง (breakeven WR ต่ำ) + confirmation (แท่งปฏิเสธ = กรอง knife) + zone แข็ง
    VARIANTS = [
        ("baseline rr1.5", dict(rr=1.5)),
        ("rr2.0", dict(rr=2.0)),
        ("rr3.0", dict(rr=3.0)),
        ("confirm(reject)", dict(rr=1.5, confirm=True)),
        ("confirm rr2.0", dict(rr=2.0, confirm=True)),
        ("confirm rr3.0", dict(rr=3.0, confirm=True)),
        ("confirm rr2.0 touch6", dict(rr=2.0, confirm=True, min_touch=6)),
        ("confirm rr2.0 tol0.25", dict(rr=2.0, confirm=True, tol_atr=0.25)),
    ]
    print(f"⚠️ ลอง {len(VARIANTS)} variants (multiple-testing) — ต้องผ่าน t>2 + OOS>0 ถึงเชื่อ (deflate)\n")
    if "--all" in sys.argv:                                # หลัง variant ผ่าน → เทสทุกคู่ variant เดียว
        from connectors.pair_collector import _broker_map
        bmap = _broker_map() or {}
        universe = ["XAUUSD", "XAGUSD", "XAUEUR", "EURUSD", "GBPUSD", "USDCHF", "USDJPY", "BTCUSD", "WTIUSD"]
    else:
        universe = ["XAUUSD"]; bmap = {}
    for logical in universe:
        sym = bmap.get(logical, logical) if bmap else __import__("config").SYMBOL
        try:
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
            info = mt5.symbol_info(sym)
        except Exception:
            r = info = None
        if r is None or len(r) < 800 or info is None or not info.point:
            print(f"{logical:16s} ข้อมูลไม่พอ/ไม่เจอ"); continue
        h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float)
        cost = (_sc.cost_pips(logical) if _sc else None) or 30.0
        point = float(info.point)
        print(f"── {logical} (cost={cost}) ──")
        for name, kw in VARIANTS:
            _report("  " + name, run_sr_fade(h, l, c, cost, point, **kw))
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
