"""scripts/silver_leadlag_screen.py — Phase 2: does GOLD's D1 momentum lead SILVER (tradeable)?

Personas' shared silver idea: gold is the liquid leader; a confirmed gold D1 move drags higher-beta
silver. Standalone silver momentum failed (noise + 51pt spread); gated on a decisive gold move it may
have a real driver. Entry = sign of gold's k-bar momentum z-score when |z|>=Z_MIN; SL/TP ATR-based on
SILVER; net of silver's 51pt spread; non-overlapping.

Anti-bias (ML Idea B controls):
  · LAGGED (honest, tradeable): decide on gold bar i, enter silver at bar i+1 — no contemporaneous leak.
  · CONTEMPORANEOUS (control): enter silver at bar i. If it beats LAGGED a lot, the "lead" is really
    coincident co-movement → NOT exploitable.
  · SHUFFLE (control): gold signal times permuted — a real lead-lag must vanish.
  · net of measured spread, IS/OOS split, judged vs the deflated bar (params fixed a-priori => N small).
Read-only, 0 order.  python scripts/silver_leadlag_screen.py
"""
import os
import sys
from datetime import datetime, timezone
from statistics import NormalDist

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401
import regime_lib as R                   # noqa: E402
from agents.shadow_resolve import resolve_signal   # noqa: E402
from connectors.pair_collector import _broker_map  # noqa: E402

GOLD_K = 63          # gold momentum lookback (a-priori: TSMOM short leg)
Z_MIN = 1.0          # confirmed gold move = |z| >= 1 sigma
SL_ATR = 1.5; RR = 2.0; MAX_HOLD = 20
SILVER_SPREAD = 51
N_TRIALS = 8         # this screen adds ~2 cells to the running budget
_Z = NormalDist()


def _c_n(N):
    g = 0.5772156649
    return (1 - g) * _Z.inv_cdf(1 - 1.0 / N) + g * _Z.inv_cdf(1 - 1.0 / (N * _np_e()))


def _np_e():
    return float(np.e)


def _aligned():
    import MetaTrader5 as mt5
    bmap = _broker_map()
    g = mt5.copy_rates_from_pos(bmap.get("XAUUSD", "GOLD#"), mt5.TIMEFRAME_D1, 0, 6000)
    s = mt5.copy_rates_from_pos(bmap.get("XAGUSD", "SILVER#"), mt5.TIMEFRAME_D1, 0, 6000)
    if g is None or s is None:
        return None
    gm = {int(x["time"]): x for x in g}; sm = {int(x["time"]): x for x in s}
    common = sorted(set(gm) & set(sm))
    if len(common) < GOLD_K + 300:
        return None
    G = {k: np.array([gm[t][k] for t in common], float) for k in ("high", "low", "close")}
    S = {k: np.array([sm[t][k] for t in common], float) for k in ("high", "low", "close")}
    return G, S, np.array(common), float(mt5.symbol_info(bmap.get("XAGUSD", "SILVER#")).point), \
        int(mt5.symbol_info(bmap.get("XAGUSD", "SILVER#")).digits)


def _run(G, S, times, point, digits, mode, rng=None):
    gc = G["close"]; g_atr = R.atr(G["high"], G["low"], gc)
    s_high, s_low, s_close = S["high"], S["low"], S["close"]
    s_atr = R.atr(s_high, s_low, s_close)
    n = len(gc)
    # gold confirmed-move signal per bar
    sig = np.zeros(n)
    for i in range(GOLD_K, n):
        if g_atr[i] > 0:
            z = (gc[i] - gc[i - GOLD_K]) / (g_atr[i] * np.sqrt(GOLD_K))
            if abs(z) >= Z_MIN:
                sig[i] = np.sign(z)
    if rng is not None:                                   # SHUFFLE control: permute signal times
        sig = sig.copy(); rng.shuffle(sig)
    lag = 1 if mode == "lagged" else 0
    cut = int(n * 0.6); trades = []; flat = -1
    for i in range(GOLD_K, n - MAX_HOLD - 2):
        if sig[i] == 0 or i <= flat:
            continue
        e = i + lag                                       # silver entry bar
        if e >= n - 1 or not np.isfinite(s_atr[e]) or s_atr[e] <= 0:
            continue
        d = "BUY" if sig[i] > 0 else "SELL"
        sl_pips = max(1, round(SL_ATR * s_atr[e] / point))
        rec = {"dir": d, "entry": float(s_close[e]), "sl_pips": sl_pips,
               "tp_pips": round(sl_pips * RR), "bar_ts": ""}
        out = resolve_signal(rec, s_high, s_low, s_close, times, point=point,
                             cost_pips=SILVER_SPREAD, max_hold_bars=MAX_HOLD, price_digits=digits, i0=e)
        if out is None or out.get("result") == "OPEN":
            continue
        trades.append((out["realized_R"], e < cut)); flat = e + out["bars_held"]
    if not trades:
        return {"n": 0}
    allR = np.array([x for x, _ in trades]); isR = [x for x, i_ in trades if i_]; ooR = [x for x, i_ in trades if not i_]
    sd = float(allR.std(ddof=1)) if len(allR) > 1 else 0.0
    exp = float(allR.mean())
    bar = sd * (_c_n(N_TRIALS) + 1.65) / np.sqrt(len(allR)) if sd > 0 else None
    return {"n": len(allR), "exp_R": round(exp, 3), "sd": round(sd, 2),
            "t": round(exp / sd * np.sqrt(len(allR)), 2) if sd > 0 else 0,
            "bar": round(bar, 3) if bar else None, "sum_R": round(float(allR.sum()), 1),
            "is": round(float(np.mean(isR)), 3) if isR else None,
            "oos": round(float(np.mean(ooR)), 3) if ooR else None}


def main():
    got = _aligned()
    if got is None:
        print("insufficient aligned gold/silver D1 data"); return
    G, S, times, point, digits = got
    print(f"Silver lead-lag (gold→silver D1) · {datetime.now(timezone.utc).isoformat()[:16]}Z · "
          f"gold_k={GOLD_K} z>={Z_MIN} RR={RR} · net {SILVER_SPREAD}pt · bar-uses σ")
    print(f"aligned D1 bars: {len(times)} (~{len(times)/252:.1f}y)\n")
    for mode in ("lagged", "contemporaneous"):
        d = _run(G, S, times, point, digits, mode)
        if d["n"] == 0:
            print(f"  {mode:16s} no trades"); continue
        v = "BELIEVE" if (d["bar"] and d["exp_R"] > d["bar"] and d["oos"] and d["oos"] > 0 and d["n"] >= 100) \
            else ("OOS<=0" if (d["oos"] is not None and d["oos"] <= 0) else "reject")
        print(f"  {mode:16s} n={d['n']:<4d} exp_R={d['exp_R']:+.3f} σ={d['sd']} t={d['t']:+.2f} "
              f"bar={d['bar']} IS={d['is']} OOS={d['oos']}  {v}")
    # shuffle control (seeded, no Math.random equiv issue — numpy default_rng with fixed seed)
    sh = _run(G, S, times, point, digits, "lagged", rng=np.random.default_rng(7))
    if sh.get("n"):
        print(f"  {'shuffle(ctrl)':16s} n={sh['n']:<4d} exp_R={sh['exp_R']:+.3f} t={sh['t']:+.2f}  "
              f"(ต้อง ~0; ถ้าบวก = edge จริงน่าสงสัย)")
    print("\nBELIEVE = LAGGED exp_R > bar AND OOS>0 AND n>=100. ถ้า contemporaneous >> lagged = coincident ไม่ใช่ lead.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
