#!/usr/bin/env python
"""
regime_backtest.py — P2: validation gauntlet for the ONE-algo-per-regime library (OFFLINE).

ไม่ใช่ "backtest ให้ดูสวย" — เป็น **null-first gauntlet** ที่พยายาม *หักล้าง* ว่ามี edge:
  1. INTRABAR fill (H/L ไม่ใช่ close — close-path เคยให้ DSR 0.98 ปลอม → intrabar เหลือ 0.05)
     ถ้า SL+TP อยู่ bar เดียวกัน → assume SL โดน (pessimistic, กัน optimistic bias)
  2. NET OF COST — หัก spread+slippage round-trip (sensitivity 20/30/40 pips)
  3. time-stop (max_hold_bars จาก OU half-life) + MFE/MAE
  4. PSR(0) — prob(true Sharpe>0) ปรับ skew/kurtosis (Bailey-LdP)
  5. NULL TEST — block-bootstrap price → รัน algo เดิม → null distribution ของ expectancy
     real edge = เกิน null p95 (จับ drift-bias: "+0.030R" เคย = null mean +0.027)

**ยังไม่ optimize param** (2 algo fixed) → PBO/CSCV ค่อยทำตอน sweep param (P2b). trials ต่ำ.
เข้า trade ที่ close ของ bar สัญญาณ; เช็ค exit จาก bar ถัดไป (กัน same-bar look-ahead).

รัน:  python scripts\\regime_backtest.py [tf]   (default h1)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

COST_PIPS_GRID = [20, 30, 40]      # round-trip spread+slippage (XAU: 1 pip = $0.01)
MOM_MAX_HOLD = 500                  # bound momentum trades ที่ไม่มี time-stop (SL/TP ควรโดนก่อน)
MIN_N = 100                        # ต่ำกว่านี้ = noise, ไม่สรุป


# ─────────────────────────── intrabar trade simulation ───────────────────────────
def simulate_trade(entry_i, direction, sl_pips, tp_pips, max_hold, high, low, close):
    """เข้าที่ close[entry_i], เช็ค exit จาก bar entry_i+1 ด้วย H/L (intrabar).
    คืน (R_gross, bars_held, mfe_pips, mae_pips, exit_reason). R = ผลลัพธ์/risk (sl distance)."""
    entry = close[entry_i]
    sign = 1.0 if direction == "BUY" else -1.0
    sl = entry - sign * sl_pips * R.POINT
    tp = entry + sign * tp_pips * R.POINT
    risk = sl_pips * R.POINT
    mfe = mae = 0.0
    end = min(entry_i + max_hold, len(close) - 1)
    for j in range(entry_i + 1, end + 1):
        # MFE/MAE (favorable/adverse excursion เทียบ entry)
        fav = sign * (high[j] - entry) if direction == "BUY" else sign * (entry - low[j])
        adv = sign * (entry - low[j]) if direction == "BUY" else sign * (high[j] - entry)
        mfe = max(mfe, sign * (high[j] - entry) if direction == "BUY" else sign * (entry - low[j]))
        mae = max(mae, (entry - low[j]) if direction == "BUY" else (high[j] - entry))
        hit_sl = low[j] <= sl if direction == "BUY" else high[j] >= sl
        hit_tp = high[j] >= tp if direction == "BUY" else low[j] <= tp
        if hit_sl and hit_tp:
            return -1.0, j - entry_i, mfe / R.POINT, mae / R.POINT, "SL_TP_ambig"   # pessimistic: SL ก่อน
        if hit_sl:
            return -1.0, j - entry_i, mfe / R.POINT, mae / R.POINT, "SL"
        if hit_tp:
            return tp_pips / sl_pips, j - entry_i, mfe / R.POINT, mae / R.POINT, "TP"
    # time-stop / max bars: ปิดที่ close ปัจจุบัน
    pnl = sign * (close[end] - entry)
    return pnl / risk, end - entry_i, mfe / R.POINT, mae / R.POINT, "TIME"


def run_algo(algo_name, high, low, close, atr_v, er, adx_v, volpct):
    """สร้างสัญญาณจาก route() แล้ว sim ทุกไม้. คืน list ของ dict ต่อ trade (R_gross + meta)."""
    trades = []
    start = max(R.VOL_LOOKBACK, R.BRK_WIN, R.ER_WIN) + 2
    for i in range(start, len(close) - 1):
        regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct)
        if not sig or sig["algo"] != algo_name:
            continue
        max_hold = sig.get("max_hold_bars", MOM_MAX_HOLD)
        r_gross, bars, mfe, mae, why = simulate_trade(
            i, sig["dir"], sig["sl_pips"], sig["tp_pips"], max_hold, high, low, close)
        trades.append({"i": i, "dir": sig["dir"], "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"],
                       "R_gross": r_gross, "bars": bars, "mfe": mfe, "mae": mae, "why": why})
    return trades


# ─────────────────────────── metrics ───────────────────────────
def net_R(trades, cost_pips):
    """R หลังหัก cost: cost เป็น pips → เป็น R โดยหารด้วย sl ของไม้นั้น."""
    return np.array([t["R_gross"] - cost_pips / t["sl_pips"] for t in trades])


def psr_zero(r):
    """Probabilistic Sharpe Ratio เทียบ benchmark SR=0: prob(true Sharpe>0) ปรับ skew/kurt.
    (Bailey-LdP). ต้องการ non-normality correction เพราะ R ของ SL/TP มี fat tail/skew."""
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    m = r - r.mean()
    skew = (m ** 3).mean() / (r.std() ** 3)
    kurt = (m ** 4).mean() / (r.std() ** 4)          # non-excess
    denom = np.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    from math import erf
    z = sr * np.sqrt(n - 1) / denom
    return 0.5 * (1 + erf(z / np.sqrt(2)))            # Φ(z)


def summarize(name, trades, cost_pips):
    r = net_R(trades, cost_pips)
    n = len(r)
    wins = r[r > 0]; losses = r[r <= 0]
    wr = len(wins) / n if n else 0
    exp = r.mean() if n else 0
    sharpe = r.mean() / r.std(ddof=1) if n > 1 and r.std(ddof=1) > 0 else 0
    return {"name": name, "n": n, "cost": cost_pips, "wr": wr, "exp_R": exp,
            "avg_win": wins.mean() if len(wins) else 0, "avg_loss": losses.mean() if len(losses) else 0,
            "sharpe": sharpe, "psr0": psr_zero(r), "sum_R": r.sum()}


def print_row(s):
    psr = f"{s['psr0']:.2f}" if s["psr0"] == s["psr0"] else "n/a"
    verdict = "＋EV" if s["exp_R"] > 0 else "－EV"
    print(f"  cost={s['cost']:>2}p │ N={s['n']:>5} WR={s['wr']*100:4.1f}% "
          f"expR={s['exp_R']:+.3f} avgW={s['avg_win']:+.2f} avgL={s['avg_loss']:+.2f} "
          f"Sharpe={s['sharpe']:+.3f} PSR₀={psr} sumR={s['sum_R']:+.0f}  {verdict}")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    p = os.path.join(_BASE, "data", f"xau_{tf}.json")
    if not os.path.exists(p):
        print(f"❌ ไม่มี data/xau_{tf}.json"); return
    rows = json.load(open(p))
    high = np.array([r[2] for r in rows]); low = np.array([r[3] for r in rows]); close = np.array([r[4] for r in rows])
    print("=" * 78)
    print(f"REGIME BACKTEST — P2 gauntlet | gold {tf.upper()} {len(close)} bars | intrabar+cost, NULL-first")
    print("=" * 78)
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)

    for algo in ("momentum_breakout", "mean_reversion"):
        trades = run_algo(algo, high, low, close, atr_v, er, adx_v, volpct)
        print(f"\n── {algo} ── ({len(trades)} raw signals)")
        if len(trades) < MIN_N:
            print(f"  ⚠ N<{MIN_N} — noise, ไม่สรุป"); continue
        why = {}
        for t in trades:
            why[t["why"]] = why.get(t["why"], 0) + 1
        print(f"  exits: {why}")
        for c in COST_PIPS_GRID:
            print_row(summarize(algo, trades, c))
    print("\n" + "=" * 78)
    print("อ่านผล: expR>0 ทุก cost + PSR₀>0.95 = candidate. ต้องผ่าน NULL test (step 2) ก่อนเชื่อ.")
    print("ยังไม่ optimize param (trials ต่ำ) — PBO/CSCV ตอน sweep param (P2b).")


if __name__ == "__main__":
    main()
