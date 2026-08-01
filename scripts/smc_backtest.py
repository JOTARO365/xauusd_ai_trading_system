"""scripts/smc_backtest.py — SMC-derived candidate algos, no-look-ahead + cost-adjusted.

จาก research (skill smc-ict-quant-evidence): SMC ที่มีหลักฐานจริง = FVG (สะอาดสุด),
round-number/prior-day H-L liquidity (Osler kernel), BOS=momentum. ทดสอบ:

  A) momentum + FVG filter — ปรับ algo เดิม (= registry regime_momentum_fvg)
  B) liquidity-sweep reversal — algo ใหม่ (= registry sweep_reversal): fade sweep prior-day H/L
  C) FVG-fill fade — เข้าหา gap-fill (XAU research table เท่านั้น)

กฎ quant: causal (signal ที่ i, resolve จาก i+1), SL-first, หัก cost, MIN_N, log variants.
FVG = gap-only (ให้ตรงกับ registry algo ที่ bars ไม่มี open). prior-day = จาก H1 เอง (bucket UTC).

Run:
  python scripts/smc_backtest.py            # XAU H1 offline (6-candidate table + OOS)
  python scripts/smc_backtest.py --all      # + ทุกคู่ผ่าน MT5 (matrix_backtest ต่อ (algo,symbol))
เขียน data/smc_backtest.json (dashboard อ่าน — SMC panel + Shadow Matrix). READ-ONLY บน MT5.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regime_lib as R    # causal indicators + detect_regime (LA-free)

MIN_N = 100
MAX_HOLD = 240                   # H1 bars (~10 วัน)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))   # repo root → import connectors/agents (all-pairs MT5 mode)
UNIVERSE = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD",
            "GBPUSD", "USDCHF", "USDJPY", "BTCUSD", "WTIUSD"]


def _load(tf):
    rows = json.loads((_ROOT / f"data/xau_{tf}.json").read_text())
    a = lambda k: np.array([r[k] for r in rows], dtype=(np.int64 if k == 0 else float))
    return a(0), a(1), a(2), a(3), a(4)   # t,o,h,l,c


# ── excursion sim (SL-first, causal จาก i+1) ────────────────────────────────────
def _sim(h, l, c, direction, entry, sl_pips, tp_pips, i, cost_pips, point):
    sign = 1 if direction == "BUY" else -1
    sl = entry - sign * sl_pips * point
    tp = entry + sign * tp_pips * point if tp_pips else None
    end = min(i + MAX_HOLD, len(c) - 1)
    for j in range(i + 1, end + 1):
        hit_sl = (l[j] <= sl) if sign > 0 else (h[j] >= sl)
        hit_tp = tp is not None and ((h[j] >= tp) if sign > 0 else (l[j] <= tp))
        if hit_sl and hit_tp:
            return -1.0 - cost_pips / sl_pips, "SL_TP_ambig"
        if hit_sl:
            return -1.0 - cost_pips / sl_pips, "SL"
        if hit_tp:
            return tp_pips / sl_pips - cost_pips / sl_pips, "TP"
    px = c[end]
    return sign * (px - entry) / (sl_pips * point) - cost_pips / sl_pips, "TIME"


def summarize(name, trades, note=""):
    rs = [r for r, _ in trades]
    n = len(rs)
    if n == 0:
        return {"name": name, "n": 0, "note": note}
    arr = np.array(rs)
    exp_r = float(arr.mean()); sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    sharpe = exp_r / sd * math.sqrt(n) if sd > 0 else 0.0
    if sd > 0 and n > 3:
        sk = float(((arr - exp_r) ** 3).mean() / sd ** 3)
        ku = float(((arr - exp_r) ** 4).mean() / sd ** 4)
        sr = exp_r / sd
        psr = 0.5 * (1 + math.erf((sr * math.sqrt(n - 1)) /
              math.sqrt(max(1e-9, 1 - sk * sr + (ku - 1) / 4 * sr ** 2)) / math.sqrt(2)))
    else:
        psr = float("nan")
    reasons = {}
    for _, w in trades:
        reasons[w] = reasons.get(w, 0) + 1
    return {"name": name, "n": n, "wr": round(sum(1 for x in arr if x > 0) / n, 3),
            "exp_R": round(exp_r, 4), "sharpe_t": round(sharpe, 2), "psr0": round(psr, 3),
            "sum_R": round(float(arr.sum()), 1), "reasons": reasons, "note": note}


def _regime_series(h, l, c):
    return (R.efficiency_ratio(c, R.ER_WIN), R.adx(h, l, c, R.ADX_WIN),
            R.vol_percentile(c, R.VOL_WIN, R.VOL_LOOKBACK), R.atr(h, l, c, R.ATR_WIN))


def _gap_fvg_dir(h, l, j):
    """FVG gap-only (ตรงกับ registry): bull low[j]>high[j-2] · bear high[j]<low[j-2]. causal ที่ j."""
    if j < 2:
        return None
    if l[j] > h[j - 2]:
        return "BUY"
    if h[j] < l[j - 2]:
        return "SELL"
    return None


def _prior_day_levels(high, low, times):
    """pdh[],pdl[] ต่อแท่ง = H/L ของวัน UTC ก่อนหน้า (ปิดครบ) — causal, O(n)."""
    from datetime import datetime, timezone
    days = [datetime.fromtimestamp(int(t), timezone.utc).date() for t in times]
    day_hl = {}; order = []
    for k, d in enumerate(days):
        if d not in day_hl:
            day_hl[d] = [high[k], low[k]]; order.append(d)
        else:
            if high[k] > day_hl[d][0]: day_hl[d][0] = high[k]
            if low[k] < day_hl[d][1]: day_hl[d][1] = low[k]
    prev = {order[i]: order[i - 1] for i in range(1, len(order))}
    pdh = np.full(len(days), np.nan); pdl = np.full(len(days), np.nan)
    for k, d in enumerate(days):
        p = prev.get(d)
        if p is not None:
            pdh[k] = day_hl[p][0]; pdl[k] = day_hl[p][1]
    return pdh, pdl


# ── candidate A: momentum (+optional FVG filter) ────────────────────────────────
def run_momentum(h, l, c, cost, point, fvg_filter=False, fvg_lb=6, lo=None, hi=None, pre=None):
    er, adx, vp, atr = pre or _regime_series(h, l, c)
    start = max(R.VOL_LOOKBACK, R.BRK_WIN, R.ER_WIN) + 2
    trades = []
    for i in range(max(start, lo or 0), hi or (len(c) - 1)):
        if R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            continue
        hh = h[i - R.BRK_WIN:i].max(); ll = l[i - R.BRK_WIN:i].min()
        d = "BUY" if c[i] > hh else ("SELL" if c[i] < ll else None)
        if d is None or not (atr[i] == atr[i]) or atr[i] <= 0:
            continue
        if fvg_filter and not any(_gap_fvg_dir(h, l, j) == d for j in range(max(2, i - fvg_lb), i + 1)):
            continue
        sl = round(R.ATR_SL * atr[i] / point)
        if sl <= 0:
            continue
        trades.append(_sim(h, l, c, d, c[i], sl, round(sl * R.RR), i, cost, point))
    return trades


# ── candidate B: sweep-reversal (fade prior-day H/L, non-TREND) ──────────────────
def run_sweep(h, l, c, times, cost, point, rr=1.5, buf_atr=0.5, pre=None, pdlev=None):
    er, adx, vp, atr = pre or _regime_series(h, l, c)
    pdh, pdl = pdlev or _prior_day_levels(h, l, times)
    start = max(R.VOL_LOOKBACK, R.ER_WIN) + 2
    trades = []
    for i in range(start, len(c) - 1):
        if not (atr[i] == atr[i]) or atr[i] <= 0 or not (pdh[i] == pdh[i]) or not (pdl[i] == pdl[i]):
            continue
        if R.detect_regime(er[i], adx[i], vp[i]) not in ("NEUTRAL", "RANGE"):
            continue
        d = swept = None
        if h[i] > pdh[i] and c[i] < pdh[i]:
            d, swept = "SELL", h[i]
        elif l[i] < pdl[i] and c[i] > pdl[i]:
            d, swept = "BUY", l[i]
        if d is None:
            continue
        sign = 1 if d == "BUY" else -1
        sl = round(abs(c[i] - (swept - sign * buf_atr * atr[i])) / point)
        if sl <= 0:
            continue
        trades.append(_sim(h, l, c, d, c[i], sl, round(sl * rr), i, cost, point))
    return trades


def run_fvg_fill(h, l, c, cost, point, rr=1.0, pre=None):
    er, adx, vp, atr = pre or _regime_series(h, l, c)
    start = max(R.VOL_LOOKBACK, R.ER_WIN) + 2
    trades = []
    for i in range(start, len(c) - 1):
        if not (atr[i] == atr[i]) or atr[i] <= 0:
            continue
        if R.detect_regime(er[i], adx[i], vp[i]) not in ("NEUTRAL", "RANGE"):
            continue
        fvg = _gap_fvg_dir(h, l, i)
        if fvg is None:
            continue
        d = "SELL" if fvg == "BUY" else "BUY"
        sl = round(1.0 * atr[i] / point)
        if sl <= 0:
            continue
        trades.append(_sim(h, l, c, d, c[i], sl, round(sl * rr), i, cost, point))
    return trades


# ── matrix backtest ต่อคู่ (= 2 registry shadow algos) ──────────────────────────
def _matrix_for(logical, h, l, c, times, cost, point):
    pre = _regime_series(h, l, c)
    out = []
    m = summarize("mfvg", run_momentum(h, l, c, cost, point, fvg_filter=True, pre=pre), "")
    s = summarize("swp", run_sweep(h, l, c, times, cost, point, pre=pre), "")
    for aid, st in (("regime_momentum_fvg", m), ("sweep_reversal", s)):
        if st["n"]:
            out.append({"algo_id": aid, "symbol": logical, "exp_R": st["exp_R"],
                        "n": st["n"], "wr": round(st["wr"] * 100, 1), "managed": False})
    return out


def all_pairs_matrix():
    """ดึง H1 ต่อคู่จาก MT5 (broker symbol map) → matrix_backtest ต่อ (algo,symbol). ต้อง MT5 login."""
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    if not mt5.initialize():
        print("  MT5 init fail — ข้าม all-pairs"); return []
    bmap = _broker_map() or {}
    entries = []
    for logical in UNIVERSE:
        sym = bmap.get(logical, logical)
        try:
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
            info = mt5.symbol_info(sym)
        except Exception:
            r = info = None
        if r is None or len(r) < R.VOL_LOOKBACK + 100 or info is None or not info.point:
            print(f"  {logical:8s} ({sym}): ข้อมูลไม่พอ/symbol ไม่เจอ — ข้าม"); continue
        h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float); t = np.array([int(x["time"]) for x in r])
        cost = (_sc.cost_pips(logical) if _sc else None) or 30.0
        rows = _matrix_for(logical, h, l, c, t, cost, float(info.point))
        for e in rows:
            print(f"  {logical:8s} {e['algo_id']:20s} n={e['n']:5d} expR={e['exp_R']:+.4f} wr={e['wr']}")
        entries += rows
    mt5.shutdown()
    return entries


def main():
    all_mode = "--all" in sys.argv
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    tf = argv[0] if argv else "h1"
    cost = float(argv[1]) if len(argv) > 1 else 30.0
    t, o, h, l, c = _load(tf)
    pre = _regime_series(h, l, c)
    pdlev = _prior_day_levels(h, l, t)
    POINT = 0.01

    print(f"\n=== SMC candidate backtest — XAU {tf.upper()} | cost={cost} | bars={len(c)} ===\n")
    results = [
        summarize("A0 momentum (baseline TREND)", run_momentum(h, l, c, cost, POINT, pre=pre)),
        summarize("A1 momentum + FVG filter (k=6)", run_momentum(h, l, c, cost, POINT, fvg_filter=True, pre=pre), "variant of A0"),
        summarize("B1 sweep-rev PDH/PDL rr1.5", run_sweep(h, l, c, t, cost, POINT, pre=pre, pdlev=pdlev), "NEW algo"),
        summarize("B2 sweep-rev rr1.0", run_sweep(h, l, c, t, cost, POINT, rr=1.0, pre=pre, pdlev=pdlev), "variant of B1"),
        summarize("C1 FVG-fill fade rr1.0", run_fvg_fill(h, l, c, cost, POINT, pre=pre), "NEW algo"),
    ]
    hdr = f"{'candidate':<34}{'n':>7}{'WR':>7}{'exp_R':>9}{'t':>7}{'PSR0':>7}{'sumR':>9}  note"
    print(hdr); print("-" * len(hdr))
    for r in results:
        if not r["n"]:
            print(f"{r['name']:<34}{'0':>7}   (no trades)"); continue
        flag = "" if r["n"] >= MIN_N else "  <MIN_N!"
        print(f"{r['name']:<34}{r['n']:>7}{r['wr']:>7}{r['exp_R']:>9}{r['sharpe_t']:>7}{r['psr0']:>7}{r['sum_R']:>9}  {r.get('note','')}{flag}")

    def _er(tr):
        rs = [x for x, _ in tr]
        return {"n": len(rs), "exp_R": round(sum(rs) / len(rs), 4) if rs else None,
                "wr": round(sum(1 for x in rs if x > 0) / len(rs), 3) if rs else None}
    cut = int(len(c) * 0.7)
    oos = {"cut_ts": int(t[cut]),
           "in_sample":  {"A0": _er(run_momentum(h, l, c, cost, POINT, hi=cut, pre=pre)),
                          "A1": _er(run_momentum(h, l, c, cost, POINT, fvg_filter=True, hi=cut, pre=pre))},
           "out_sample": {"A0": _er(run_momentum(h, l, c, cost, POINT, lo=cut, pre=pre)),
                          "A1": _er(run_momentum(h, l, c, cost, POINT, fvg_filter=True, lo=cut, pre=pre))}}
    print(f"\nOOS split: IS A0 {oos['in_sample']['A0']['exp_R']}/A1 {oos['in_sample']['A1']['exp_R']}"
          f" | OOS A0 {oos['out_sample']['A0']['exp_R']}/A1 {oos['out_sample']['A1']['exp_R']}")

    # matrix: XAU (offline) เสมอ + ทุกคู่ (MT5) ถ้า --all
    matrix = _matrix_for("XAUUSD", h, l, c, t, cost, POINT)
    if all_mode:
        print("\n=== all-pairs (MT5) ===")
        try:
            extra = all_pairs_matrix()
            matrix = [e for e in matrix if e["symbol"] != "XAUUSD" or
                      e["algo_id"] not in {x["algo_id"] for x in extra if x["symbol"] == "XAUUSD"}] + extra
        except Exception as e:
            print(f"  all-pairs fail: {e}")

    from datetime import datetime, timezone
    payload = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "instrument": f"XAUUSD {tf.upper()}", "bars": len(c), "cost_pips": cost,
               "range": [int(t[0]), int(t[-1])],
               "candidates": [{k: r.get(k) for k in ("name", "n", "wr", "exp_R", "sharpe_t", "psr0", "sum_R", "note", "reasons")} for r in results],
               "oos": oos,
               "verdict": "ไม่มี candidate ให้ edge หลัง cost; FVG filter ไม่รอด OOS (window bias); sweep-fade = high-WR/low-RR trap",
               "shadow_algos": ["regime_momentum_fvg", "sweep_reversal"],
               "matrix_backtest": matrix}
    try:
        (_ROOT / "data" / "smc_backtest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ wrote data/smc_backtest.json ({len(matrix)} matrix rows)")
    except OSError as e:
        print(f"\n⚠️ write failed: {e}")


if __name__ == "__main__":
    main()
