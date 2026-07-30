"""scripts/structural_sl_backtest.py — พิสูจน์ structural SL ก่อนเปิด live.

เทียบ SL แบบ fixed/ATR (live เดิม) vs structural (**ปลายไส้แท่ง D1 ปิดล่าสุด** + buffer, ไม่ clamp) บน signal
momentum ชุด**เดียวกัน** (no look-ahead: signal ใช้ข้อมูล ≤ i, ไส้ D1 ใช้แท่ง D1 ที่ปิดก่อน time ของ signal,
forward-sim จาก i+1).

วัด: SL-hit%, TP-hit%, exp_R, และ "rescued" = ไม้ที่ fixed โดน SL แต่ structural ได้ TP (= แก้ตรงอาการ
"เข้าถูกทางแต่โดน SL ก่อน"). ตรงข้าม "worsened" = fixed TP แต่ structural SL (structural กว้างไปโดนสวน).

รัน (บอทเปิดอยู่/ปิดก็ได้ — read-only):
  python scripts/structural_sl_backtest.py                 # ทุกคู่ LIVE + ทอง
  python scripts/structural_sl_backtest.py OILCash# GOLD#   # เจาะจง

⚠️ window = ข้อมูลที่ MT5 ให้ (คู่/โบรกต่างกัน); เทียบ fixed vs structural บน signal เดียวกัน → relative valid.
"""
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "scripts"))

import regime_lib as R
from agents import structural_sl as S

H1_COUNT = 60000            # ~10 ปี H1 (MT5 ให้เท่าที่มี)
H4_COUNT = 20000
D1_COUNT = 3000
MAX_HOLD = 240             # forward-sim สูงสุด (H1 บาร์) ~10 วันเทรด
BUFFER_ATR = float(os.getenv("BT_BUFFER_ATR") or 0.3)   # sensitivity: BT_BUFFER_ATR=0.2 python ...
PICK = os.getenv("BT_PICK", "farthest")                 # ตรง config default; BT_PICK=nearest เทียบได้
TFS = ("H4", "D1")


def _pull(symbol):
    import MetaTrader5 as mt5
    from connectors.price_feed import get_ohlcv
    out = {}
    for tf, mtf, cnt in [("H1", mt5.TIMEFRAME_H1, H1_COUNT), ("H4", mt5.TIMEFRAME_H4, H4_COUNT),
                         ("D1", mt5.TIMEFRAME_D1, D1_COUNT)]:
        r = get_ohlcv(symbol=symbol, timeframe=mtf, count=cnt)
        if r is None or len(r) < 50:
            out[tf] = None
        else:
            out[tf] = (r["high"].astype(float), r["low"].astype(float),
                       r["close"].astype(float), np.asarray(r["time"], dtype=np.int64))
    info = mt5.symbol_info(symbol)
    out["point"] = float(info.point) if info and info.point else None
    return out


def _last_closed_wick(bars, t):
    """(high, low) ของแท่ง TF ที่ปิดก่อน time t (no look-ahead). None ถ้าไม่พอ.
    MT5 bar time = เปิดแท่ง → แท่งกำลังก่อตัว index k-1, ปิดล่าสุด = k-2."""
    if not bars:
        return None
    hi, lo, _cl, tm = bars
    k = int(np.searchsorted(tm, t, side="right"))
    j = k - 2
    if j < 0:
        return None
    return (float(hi[j]), float(lo[j]))


def _sim(direction, entry, sl_pips, tp_pips, point, fh, fl, start):
    """forward-sim H1 จาก index start. คืน (R_outcome, hit) hit∈{'SL','TP','TIMEOUT'}.
    conservative: บาร์เดียวชนทั้ง SL+TP → นับ SL ก่อน (pessimistic)."""
    if sl_pips <= 0:
        return 0.0, "TIMEOUT"
    rr = tp_pips / sl_pips if tp_pips > 0 else 0.0
    if direction == "BUY":
        sl_px = entry - sl_pips * point
        tp_px = entry + tp_pips * point if tp_pips > 0 else None
    else:
        sl_px = entry + sl_pips * point
        tp_px = entry - tp_pips * point if tp_pips > 0 else None
    end = min(len(fh), start + MAX_HOLD)
    for j in range(start, end):
        hi, lo = fh[j], fl[j]
        hit_sl = (lo <= sl_px) if direction == "BUY" else (hi >= sl_px)
        hit_tp = tp_px is not None and ((hi >= tp_px) if direction == "BUY" else (lo <= tp_px))
        if hit_sl:
            return -1.0, "SL"
        if hit_tp:
            return rr, "TP"
    return 0.0, "TIMEOUT"


def backtest(symbol, sl_mult=1.0):
    data = _pull(symbol)
    h1 = data["H1"]; point = data["point"]
    if not h1 or not point:
        return {"symbol": symbol, "error": "no H1/point"}
    high, low, close, times = h1
    n = len(close)
    er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
    vol = R.vol_percentile(close); atr = R.atr(high, low, close)
    start = max(R.VOL_LOOKBACK, R.BRK_WIN, R.ER_WIN) + 2

    agg = {"n": 0, "fix": {"SL": 0, "TP": 0, "TIMEOUT": 0, "R": 0.0},
           "str": {"SL": 0, "TP": 0, "TIMEOUT": 0, "R": 0.0, "used": 0},
           "rescued": 0, "worsened": 0}
    for i in range(start, n - 1):
        if R.detect_regime(er[i], adx[i], vol[i]) != "TREND":
            continue
        sig = R.algo_momentum_breakout(i, high, low, close, atr, point=point)
        if not sig:
            continue
        direction = sig["dir"]; entry = float(close[i])
        base_sl = float(sig["sl_pips"]) * sl_mult
        base_tp = float(sig["tp_pips"])
        atr_px = float(atr[i])
        if base_sl <= 0 or atr_px <= 0:
            continue
        # structural (ปลายไส้ H4/D1 ปิดล่าสุด, point-in-time, no clamp)
        wicks = {}
        for tf in TFS:
            w = _last_closed_wick(data.get(tf), int(times[i]))
            if w:
                wicks[tf] = w
        r = S.wick_sl(direction, entry, atr_px, point, wicks, BUFFER_ATR, mode=PICK) if wicks else None
        used = r is not None
        s_sl = r["sl_pips"] if used else base_sl
        if used and os.getenv("BT_RR_PRESERVE") == "1":
            s_tp = (base_tp / base_sl) * s_sl                        # (เทียบเฉยๆ) คง RR — TP ขยายตาม SL = แย่กว่า
        else:
            s_tp = base_tp                                            # live: คง TP เดิม (เปลี่ยน SL อย่างเดียว)

        rf, hf = _sim(direction, entry, base_sl, base_tp, point, high, low, i + 1)
        rs, hs = _sim(direction, entry, s_sl, s_tp, point, high, low, i + 1)

        agg["n"] += 1
        agg["fix"][hf] += 1; agg["fix"]["R"] += rf
        agg["str"][hs] += 1; agg["str"]["R"] += rs
        if used:
            agg["str"]["used"] += 1
            if hf == "SL" and hs == "TP":
                agg["rescued"] += 1
            elif hf == "TP" and hs == "SL":
                agg["worsened"] += 1
    return {"symbol": symbol, "point": point, "bars": n, **agg}


def _fmt(res):
    if res.get("error"):
        return f"{res['symbol']:10s} ERROR: {res['error']}"
    n = res["n"] or 1
    f, s = res["fix"], res["str"]
    def line(tag, d):
        return (f"  {tag}: SL {d['SL']:4d} ({d['SL']/n*100:4.1f}%) | TP {d['TP']:4d} ({d['TP']/n*100:4.1f}%) | "
                f"TO {d['TIMEOUT']:4d} | expR {d['R']/n:+.3f}")
    return (f"{res['symbol']}  (bars={res['bars']}, signals={res['n']}, structural-used={s['used']})\n"
            f"{line('FIXED     ', f)}\n{line('STRUCTURAL', s)}\n"
            f"  rescued (fix SL->str TP): {res['rescued']}  |  worsened (fix TP->str SL): {res['worsened']}  |  "
            f"delta expR: {(s['R']-f['R'])/n:+.3f}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from connectors.price_feed import connect_mt5
    if not connect_mt5():
        print("MT5 connect fail"); return
    args = sys.argv[1:]
    if args:
        symbols = [(a, 1.0) for a in args]
    else:
        from connectors.mt5_connector import SYMBOL as GOLD
        from connectors.pair_collector import _broker_map
        from agents import shadow_switches as sw, algo_registry as reg
        import config as cfg
        bmap = _broker_map()
        # sl_mult ต่อ symbol (WTI 0.7 ฯลฯ) จาก config
        smult = {}
        for kv in str(getattr(cfg, "ALGO_SL_MULT", "")).split(","):
            if ":" in kv:
                k, v = kv.split(":", 1)
                try: smult[k.strip()] = float(v)
                except ValueError: pass
        live = sw.combos_in(sw.LIVE, reg.combos(reg.UNIVERSE))
        symbols = []
        seen = set()
        for algo_id, sym in live:
            br = bmap.get(sym, sym)
            if br in seen:
                continue
            seen.add(br)
            symbols.append((br, smult.get(sym, 1.0)))
        if GOLD not in seen:
            symbols.append((GOLD, 1.0))
    print(f"Structural SL backtest — SL=ปลายไส้ {'+'.join(TFS)} ปิดล่าสุด pick={PICK} +buffer={BUFFER_ATR}ATR hold≤{MAX_HOLD}H1\n")
    for sym, mult in symbols:
        print(_fmt(backtest(sym, mult)))
        print()


if __name__ == "__main__":
    main()
