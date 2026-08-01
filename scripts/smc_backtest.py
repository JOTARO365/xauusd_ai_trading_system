"""scripts/smc_backtest.py — SMC-derived candidate algos, no-look-ahead + cost-adjusted.

จาก research (skill smc-ict-quant-evidence): SMC ที่มีหลักฐานจริง = FVG (สะอาดสุด),
round-number/prior-day H-L liquidity (Osler kernel), BOS=momentum. ทดสอบ 3 candidate:

  A) momentum + FVG filter — ปรับ algo เดิม (regime_momentum) ให้เข้าเฉพาะเมื่อมี FVG หนุนทิศ
  B) liquidity-sweep reversal — algo ใหม่: fade การ sweep prior-day H/L ที่ปิดกลับเข้าใน (RANGE/NEUTRAL)
  C) FVG-fill fade — เข้าหา gap-fill (mean-revert)

กฎ quant (skill quant-systematic-trading): causal ล้วน (signal ที่ i, resolve จาก i+1),
SL-first เมื่อ ambiguous, หัก cost (spread pips), report n/WR/exp_R/sharpe/PSR, MIN_N,
+ log ว่าลองกี่ variant (multiple-testing). เทียบ baseline momentum เสมอ.

Run: python scripts/smc_backtest.py            # h1 default
     python scripts/smc_backtest.py h1 30       # tf, cost_pips
ข้อมูล: data/xau_h1.json + data/xau_d1.json (array [ts,o,h,l,c,v], oldest-first). READ-ONLY.
"""
import json
import math
import sys
from bisect import bisect_right
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regime_lib as R   # causal indicators + detect_regime (LA-free)

POINT = 0.01                     # gold: 1 pip = $0.01
MIN_N = 100
MAX_HOLD = 240                   # H1 bars (~10 วัน) เพดานถือ
_ROOT = Path(__file__).resolve().parent.parent


def _load(tf):
    rows = json.loads((_ROOT / f"data/xau_{tf}.json").read_text())
    t = np.array([r[0] for r in rows], dtype=np.int64)
    o = np.array([r[1] for r in rows], dtype=float)
    h = np.array([r[2] for r in rows], dtype=float)
    l = np.array([r[3] for r in rows], dtype=float)
    c = np.array([r[4] for r in rows], dtype=float)
    return t, o, h, l, c


# ── excursion sim (SL-first, causal จาก i+1) ────────────────────────────────────
def _sim(h, l, direction, entry, sl_pips, tp_pips, i, cost_pips):
    """คืน (net_R, reason). SL=1R. tp_pips=0 → exit-on-maxhold (ไม่มี TP)."""
    sign = 1 if direction == "BUY" else -1
    sl = entry - sign * sl_pips * POINT
    tp = entry + sign * tp_pips * POINT if tp_pips else None
    end = min(i + MAX_HOLD, len(c) - 1)
    for j in range(i + 1, end + 1):
        hit_sl = (l[j] <= sl) if sign > 0 else (h[j] >= sl)
        hit_tp = tp is not None and ((h[j] >= tp) if sign > 0 else (l[j] <= tp))
        if hit_sl and hit_tp:
            return -1.0 - cost_pips / sl_pips, "SL_TP_ambig"      # pessimistic
        if hit_sl:
            return -1.0 - cost_pips / sl_pips, "SL"
        if hit_tp:
            return tp_pips / sl_pips - cost_pips / sl_pips, "TP"
    # maxhold → mark-to-close
    px = c[end]
    r_gross = sign * (px - entry) / (sl_pips * POINT)
    return r_gross - cost_pips / sl_pips, "TIME"


def summarize(name, trades, n_variants_note=""):
    rs = [r for r, _ in trades]
    n = len(rs)
    if n == 0:
        return {"name": name, "n": 0}
    arr = np.array(rs)
    wins = arr[arr > 0]
    wr = len(wins) / n
    exp_r = float(arr.mean())
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    sharpe = exp_r / sd * math.sqrt(n) if sd > 0 else 0.0     # per-sample t-stat-like
    # PSR vs 0 (skew/kurt-adjusted probabilistic sharpe)
    if sd > 0 and n > 3:
        sk = float(((arr - exp_r) ** 3).mean() / sd ** 3)
        ku = float(((arr - exp_r) ** 4).mean() / sd ** 4)
        sr = exp_r / sd
        psr = 0.5 * (1 + math.erf((sr * math.sqrt(n - 1)) /
                    math.sqrt(max(1e-9, 1 - sk * sr + (ku - 1) / 4 * sr ** 2)) / math.sqrt(2)))
    else:
        psr = float("nan")
    reasons = {}
    for _, why in trades:
        reasons[why] = reasons.get(why, 0) + 1
    return {"name": name, "n": n, "wr": round(wr, 3), "exp_R": round(exp_r, 4),
            "sharpe_t": round(sharpe, 2), "psr0": round(psr, 3),
            "sum_R": round(float(arr.sum()), 1), "reasons": reasons, "note": n_variants_note}


# ── indicators shared ───────────────────────────────────────────────────────────
def _regime_series(h, l, c):
    er = R.efficiency_ratio(c, R.ER_WIN)
    adx = R.adx(h, l, c, R.ADX_WIN)
    vp = R.vol_percentile(c, R.VOL_WIN, R.VOL_LOOKBACK)
    atr = R.atr(h, l, c, R.ATR_WIN)
    return er, adx, vp, atr


def _fvg_dir_at(h, l, o, c, j):
    """FVG ที่ 'ก่อตัวเสร็จ' ที่แท่ง j (ใช้ j-2,j-1,j ทั้งหมด closed → causal ถ้าใช้ที่ j ขึ้นไป).
    bull: low[j] > high[j-2] (+ displacement แท่งกลางเขียว) · bear: high[j] < low[j-2]."""
    if j < 2:
        return None
    if l[j] > h[j - 2] and c[j - 1] > o[j - 1]:
        return "BUY"
    if h[j] < l[j - 2] and c[j - 1] < o[j - 1]:
        return "SELL"
    return None


# ── prior-day H/L (completed D1 ก่อนหน้า) — causal ──────────────────────────────
def _pd_levels(t_h1, td1, hd1, ld1):
    """คืน (PDH[], PDL[]) ต่อแท่ง H1 = high/low ของ 'วันก่อนหน้าที่ปิดแล้ว'. causal."""
    pdh = np.full(len(t_h1), np.nan)
    pdl = np.full(len(t_h1), np.nan)
    for i, t in enumerate(t_h1):
        k = bisect_right(td1, int(t)) - 1        # D1 บาร์ของวันปัจจุบัน (กำลังก่อตัว/หรือปิดพอดี)
        if k - 1 >= 0:                            # วันก่อนหน้า = ปิดแล้วแน่นอน
            pdh[i] = hd1[k - 1]
            pdl[i] = ld1[k - 1]
    return pdh, pdl


# ═══════════════════════════════════════════════════════════════════════════════
# CANDIDATE A — momentum baseline + FVG filter
# ═══════════════════════════════════════════════════════════════════════════════
def run_momentum(h, l, o, c, cost, fvg_filter=False, fvg_lookback=6):
    er, adx, vp, atr = _regime_series(h, l, c)
    start = max(R.VOL_LOOKBACK, R.BRK_WIN, R.ER_WIN) + 2
    trades = []
    for i in range(start, len(c) - 1):
        if R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            continue
        hh = h[i - R.BRK_WIN:i].max()
        ll = l[i - R.BRK_WIN:i].min()
        d = "BUY" if c[i] > hh else ("SELL" if c[i] < ll else None)
        if d is None or math.isnan(atr[i]) or atr[i] <= 0:
            continue
        if fvg_filter:
            hit = any(_fvg_dir_at(h, l, o, c, j) == d for j in range(i - fvg_lookback, i + 1))
            if not hit:
                continue
        sl_pips = round(R.ATR_SL * atr[i] / POINT)
        if sl_pips <= 0:
            continue
        tp_pips = round(sl_pips * R.RR)
        trades.append(_sim(h, l, d, c[i], sl_pips, tp_pips, i, cost))
    return trades


# ═══════════════════════════════════════════════════════════════════════════════
# CANDIDATE B — liquidity-sweep reversal (fade sweep ของ prior-day H/L)
# ═══════════════════════════════════════════════════════════════════════════════
def run_sweep_reversal(h, l, o, c, atr, pdh, pdl, cost, regimes=("NEUTRAL", "RANGE"),
                       buf_atr=0.5, rr=1.5, tp_mode="rr", er=None, adxv=None, vp=None):
    """sweep: แตะเลย PDH/PDL แล้วปิดกลับเข้าใน → fade. เข้าเฉพาะ regime ที่ไม่ใช่ TREND."""
    start = max(R.VOL_LOOKBACK, R.ER_WIN) + 2
    trades = []
    for i in range(start, len(c) - 1):
        if math.isnan(atr[i]) or atr[i] <= 0 or math.isnan(pdh[i]) or math.isnan(pdl[i]):
            continue
        reg = R.detect_regime(er[i], adxv[i], vp[i])
        if reg not in regimes:
            continue
        d = None
        if h[i] > pdh[i] and c[i] < pdh[i]:          # sweep high → SELL
            d, swept = "SELL", h[i]
        elif l[i] < pdl[i] and c[i] > pdl[i]:        # sweep low → BUY
            d, swept = "BUY", l[i]
        if d is None:
            continue
        sign = 1 if d == "BUY" else -1
        sl_price = swept - sign * buf_atr * atr[i]   # SL เลยปลาย sweep
        sl_pips = round(abs(c[i] - sl_price) / POINT)
        if sl_pips <= 0:
            continue
        if tp_mode == "rr":
            tp_pips = round(sl_pips * rr)
        else:  # target = opposite prior-day level
            tp_price = pdl[i] if d == "BUY" else pdh[i]
            tp_pips = round(abs(tp_price - c[i]) / POINT)
            if tp_pips <= 0:
                continue
        trades.append(_sim(h, l, d, c[i], sl_pips, tp_pips, i, cost))
    return trades


# ═══════════════════════════════════════════════════════════════════════════════
# CANDIDATE C — FVG-fill fade (เข้าหา gap fill, mean-revert, non-TREND)
# ═══════════════════════════════════════════════════════════════════════════════
def run_fvg_fill(h, l, o, c, atr, cost, rr=1.0, regimes=("NEUTRAL", "RANGE"),
                 er=None, adxv=None, vp=None):
    """เมื่อเกิด FVG ใหม่ที่ i → fade เข้าหา fill (bull FVG=ราคาพุ่ง→SELL กลับเข้า gap)."""
    start = max(R.VOL_LOOKBACK, R.ER_WIN) + 2
    trades = []
    for i in range(start, len(c) - 1):
        if math.isnan(atr[i]) or atr[i] <= 0:
            continue
        reg = R.detect_regime(er[i], adxv[i], vp[i])
        if reg not in regimes:
            continue
        fvg = _fvg_dir_at(h, l, o, c, i)
        if fvg is None:
            continue
        d = "SELL" if fvg == "BUY" else "BUY"        # fade: bull FVG (พุ่งขึ้น) → SELL หา fill
        sl_pips = round(1.0 * atr[i] / POINT)
        if sl_pips <= 0:
            continue
        tp_pips = round(sl_pips * rr)
        trades.append(_sim(h, l, d, c[i], sl_pips, tp_pips, i, cost))
    return trades


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    cost = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    global c
    t, o, h, l, c = _load(tf)
    td1, _, hd1, ld1, _ = (_load("d1")[i] for i in (0, 1, 2, 3, 4))
    td1 = list(map(int, td1))
    er, adxv, vp, atr = _regime_series(h, l, c)
    pdh, pdl = _pd_levels(t, td1, hd1, ld1)

    print(f"\n=== SMC candidate backtest — XAU {tf.upper()} | cost={cost} pips | bars={len(c)} "
          f"| {int(t[0])}..{int(t[-1])} ===")
    print("gate: causal (signal@i, resolve@i+1), SL-first, MIN_N=%d, MAX_HOLD=%d\n" % (MIN_N, MAX_HOLD))

    results = []
    # A: momentum baseline vs +FVG filter (variants logged for multiple-testing honesty)
    results.append(summarize("A0 momentum (baseline TREND)", run_momentum(h, l, o, c, cost)))
    results.append(summarize("A1 momentum + FVG filter (k=6)",
                             run_momentum(h, l, o, c, cost, fvg_filter=True, fvg_lookback=6),
                             "variant of A0"))
    # B: sweep reversal — variants: tp rr1.5 / rr1.0 / opposite-level ; regimes NEUTRAL+RANGE
    results.append(summarize("B1 sweep-rev PDH/PDL rr1.5",
                             run_sweep_reversal(h, l, o, c, atr, pdh, pdl, cost, rr=1.5,
                                                er=er, adxv=adxv, vp=vp), "NEW algo"))
    results.append(summarize("B2 sweep-rev rr1.0",
                             run_sweep_reversal(h, l, o, c, atr, pdh, pdl, cost, rr=1.0,
                                                er=er, adxv=adxv, vp=vp), "variant of B1"))
    results.append(summarize("B3 sweep-rev target=opp-level",
                             run_sweep_reversal(h, l, o, c, atr, pdh, pdl, cost, tp_mode="level",
                                                er=er, adxv=adxv, vp=vp), "variant of B1"))
    # C: FVG-fill fade
    results.append(summarize("C1 FVG-fill fade rr1.0",
                             run_fvg_fill(h, l, o, c, atr, cost, rr=1.0,
                                          er=er, adxv=adxv, vp=vp), "NEW algo"))

    hdr = f"{'candidate':<34}{'n':>7}{'WR':>7}{'exp_R':>9}{'t':>7}{'PSR0':>7}{'sumR':>9}  note"
    print(hdr); print("-" * len(hdr))
    for r in results:
        if r["n"] == 0:
            print(f"{r['name']:<34}{'0':>7}   (no trades)")
            continue
        flag = "" if r["n"] >= MIN_N else "  <MIN_N!"
        print(f"{r['name']:<34}{r['n']:>7}{r['wr']:>7}{r['exp_R']:>9}{r['sharpe_t']:>7}"
              f"{r['psr0']:>7}{r['sum_R']:>9}  {r.get('note','')}{flag}")
    print("\nexit-reason breakdown:")
    for r in results:
        if r["n"]:
            print(f"  {r['name']:<34} {r['reasons']}")
    print("\n⚠️ variants tried this run = 6 (log for multiple-testing; A1/B2/B3 are tweaks of A0/B1).")
    print("⚠️ cost = spread only, swap NOT modelled (multi-day holds worse). in-sample — needs OOS/CPCV before trust.")


if __name__ == "__main__":
    main()
