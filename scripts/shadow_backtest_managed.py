"""scripts/shadow_backtest_managed.py — regen สถิติ shadow จาก "paper order ผ่าน management จริง".

ต่างจาก shadow_backtest.py (เชิงกล SL/TP ตายตัว): ตัวนี้ resolve ด้วย shadow_resolve_managed (BE + trailing
เหมือน live) → paper order เดินครบ lifecycle → สถิติสะท้อนของจริง. entry path เดียวกัน (regime_lib route /
algo_mean_reversion) + measured cost + non-overlapping single-position.

เขียนทับ docs/reports/shadow_backtest.json (algo_id=regime_momentum + mean_reversion, managed=true)
ให้ shadow_matrix อ่าน. READ-ONLY บน MT5. รัน: python scripts/shadow_backtest_managed.py
"""
import json
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
sys.path.insert(0, _BASE)

import config  # noqa: E402,F401
import regime_lib as R                                   # noqa: E402
import shadow_backtest as SB                             # noqa: E402  (reuse _fetch/_aggregate/consts)
from agents.shadow_resolve_managed import resolve_managed  # noqa: E402
from agents import shadow_cost as SC                     # noqa: E402
from connectors.pair_collector import _broker_map, COLLECT  # noqa: E402

_OUTDIR = os.path.join(_BASE, "docs", "reports")
_JSON = os.path.join(_OUTDIR, "shadow_backtest.json")


def _indicators(rates):
    high = rates["high"].astype(float); low = rates["low"].astype(float)
    close = rates["close"].astype(float); times = rates["time"]
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    return high, low, close, times, er, adx_v, volpct, atr_v


def backtest_managed(logical, broker, algo_id="regime_momentum"):
    got = SB._fetch(broker)
    if got is None:
        return {"algo_id": algo_id, "logical": logical, "broker": broker, "ok": False, "note": "no/insufficient bars"}
    rates, point, digits = got
    if point is None:
        return {"algo_id": algo_id, "logical": logical, "broker": broker, "ok": False, "note": "no symbol point"}
    high, low, close, times, er, adx_v, volpct, atr_v = _indicators(rates)
    cost_pips = SC.cost_pips(logical)
    n = len(close)
    trades = []; sig_bars = 0; flat_until = -1
    for i in range(SB._MIN_BARS, n - 1):
        if algo_id == "mean_reversion":
            if R.detect_regime(er[i], adx_v[i], volpct[i]) != "RANGE":
                continue
            sig = R.algo_mean_reversion(i, close, atr_v, point=point)
            if not sig:
                continue
            mh = sig.get("max_hold_bars") or SB.MAX_HOLD
            regime = "RANGE"
        else:
            regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct, point=point)
            if not sig or sig.get("algo") != "momentum_breakout":
                continue
            mh = SB.MAX_HOLD
        sig_bars += 1
        if i <= flat_until:
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]), "sl_pips": sig["sl_pips"],
               "tp_pips": sig["tp_pips"], "bar_ts": SB._iso(times[i])}
        out = resolve_managed(rec, high, low, close, times, atr_v, point=point, cost_pips=cost_pips,
                              max_hold_bars=mh, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":
            break
        trades.append({"i": i, "dir": rec["dir"], "regime": regime, **out})
        flat_until = i + out["bars_held"]
    res = SB._aggregate(logical, broker, trades, cost_pips, point, times, n, sig_bars, algo_id=algo_id)
    res["managed"] = True                                # flag: ผ่าน BE+trailing (ไม่ใช่ mechanical)
    return res


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    bmap = _broker_map()
    rows = []
    for algo_id in ("regime_momentum", "mean_reversion"):
        for logical in COLLECT:
            broker = bmap.get(logical, logical)
            print(f"  · {algo_id:16} {logical} ({broker}) …", flush=True)
            try:
                row = backtest_managed(logical, broker, algo_id=algo_id)
            except Exception as e:
                row = {"algo_id": algo_id, "logical": logical, "broker": broker, "ok": False,
                       "note": f"{type(e).__name__}: {e}"}
            print(f"    → ok={row.get('ok')} n={row.get('n')} exp_R={row.get('exp_R')} WR={row.get('wr')}")
            rows.append(row)
    os.makedirs(_OUTDIR, exist_ok=True)
    with open(_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    ok = sum(1 for r in rows if r.get("ok") and r.get("n"))
    print(f"\n→ wrote {_JSON} ({len(rows)} rows, {ok} with trades · managed=BE+trailing)")


if __name__ == "__main__":
    main()
