"""scripts/gold_complex_statarb.py — gold-complex stat-arb (cway direction, 08-22 [[gold-complex-statarb-direction]]).

Monetize "gold no directional edge" → trade SPREAD (market-neutral mean-reversion) ของ gold-complex.
data ผ่าน MT5 (broker มี miner CFD ลึก): Barrick/Agnico 24ปี, Newmont 12ปี, GOLD# 24ปี.
คู่: miner-vs-miner (same sector = coint สะอาด) + gold-vs-miner.

pipeline (reuse cointegration_scan + cway techniques + our discipline):
  1. align common dates · 2. cointegration gate (ADF<crit + Hurst<0.5 + HL 5-500 + split-half) — reuse _test_pair
  3. tradeable → z-score backtest (causal rolling β+z, enter|z|≥2, exit|z|≤0.5, stop|z|≥3.5, non-overlap)
  4. **validation (discipline): matched-null** (z-timing ชนะ random entry บน spread เดียวกันไหม, p<0.05) + cost
honest: equity legs = dividend-drag + idiosyncratic risk (miner ≠ pure gold beta). offline · read-only · 0 order.
รัน: python scripts/gold_complex_statarb.py
"""
import json
import math
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import cointegration_scan as CS                               # noqa: E402

WIN = 60            # rolling window (bar) สำหรับ β + z (causal)
Z_IN, Z_OUT, Z_STOP = 2.0, 0.5, 3.5
COST_Z = 0.10       # cost ต่อ round-trip เป็นสัดส่วน z-unit (2-leg spread + commission)
MAX_HOLD = 120
MIN_N = 30          # pairs = swing, ไม้น้อยโดยธรรมชาติ


def _load(fn):
    d = json.load(open(os.path.join(_BASE, "data", fn)))
    return {int(x[0] // 86400): float(x[4]) for x in d}       # day-bucket → close (align by date)


def _aligned(a, b):
    ks = sorted(set(a) & set(b))
    return np.array([a[k] for k in ks]), np.array([b[k] for k in ks]), len(ks)


def _z_backtest(y, x, force_rand=False, seed=0):
    """causal rolling-β spread z-score mean-reversion. คืน R-array (per trade)."""
    n = len(y); rng = np.random.default_rng(seed); trades = []
    i = WIN + 5
    while i < n - 1:
        yy, xx = y[i - WIN:i], x[i - WIN:i]                   # causal window (ก่อน i)
        b, a = CS._ols_beta(yy, xx)
        sp = yy - b * xx; mu, sd = sp.mean(), sp.std()
        if sd <= 0:
            i += 1; continue
        z = ((y[i] - b * x[i]) - mu) / sd
        d = 0
        if z >= Z_IN:
            d = -1                                            # spread สูง → short spread (short y / long x)
        elif z <= -Z_IN:
            d = 1
        if d == 0:
            i += 1; continue
        if force_rand:
            d = rng.choice([-1, 1])
        # exit: |z|≤Z_OUT (win) หรือ |z|≥Z_STOP (loss) — วัด z ต่อ bar
        end = min(i + MAX_HOLD, n - 1); r = None; ex = end
        for j in range(i + 1, end + 1):
            yw, xw = y[j - WIN:j], x[j - WIN:j]
            bj, _ = CS._ols_beta(yw, xw); spj = yw - bj * xw
            zj = ((y[j] - bj * x[j]) - spj.mean()) / (spj.std() or 1e9)
            adverse = zj >= Z_STOP if d < 0 else zj <= -Z_STOP
            favor = abs(zj) <= Z_OUT
            if adverse:
                r, ex = -1.0 - COST_Z / (Z_STOP - Z_IN), j; break
            if favor:
                r, ex = (Z_IN - Z_OUT) / (Z_STOP - Z_IN) - COST_Z / (Z_STOP - Z_IN), j; break
        if r is None:
            r = -COST_Z / (Z_STOP - Z_IN)                     # time-exit ~flat
        trades.append(r); i = ex + 1
    return np.array(trades)


def _stat(r):
    n = len(r)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = r.std(ddof=1); t = r.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((r > 0).mean()) * 100, 1), float(r.mean()), t


PAIRS = [
    ("barrick", "agnico", "miner_barrick_d1.json", "miner_agnico_d1.json"),
    ("barrick", "newmont", "miner_barrick_d1.json", "miner_newmont_d1.json"),
    ("agnico", "newmont", "miner_agnico_d1.json", "miner_newmont_d1.json"),
    ("gold", "barrick", "xau_d1.json", "miner_barrick_d1.json"),
    ("gold", "agnico", "xau_d1.json", "miner_agnico_d1.json"),
    ("gold", "newmont", "xau_d1.json", "miner_newmont_d1.json"),
]


def main():
    print("=== GOLD-COMPLEX STAT-ARB (cway direction) · coint-gate + z-score + drift-null ===")
    print("tradeable ⇔ ADF<crit + Hurst<0.5 + HL 5-500 + split-half. backtest เฉพาะ tradeable; matched-null ตัดสิน edge\n")
    print("%-18s %6s %7s %6s %7s | %-28s" % ("pair", "ADF", "Hurst", "HL", "corr", "tradeable? → backtest"))
    for na, nb, fa, fb in PAIRS:
        try:
            y, x, ncom = _aligned(_load(fa), _load(fb))
        except Exception as e:
            print("  %-16s load fail %s" % (na + "~" + nb, e)); continue
        if ncom < 300:
            print("  %-16s n=%d (น้อยไป)" % (na + "~" + nb, ncom)); continue
        r = CS._test_pair(y, x)
        line = "  %-16s %+6.2f %6.2f %6.0f %6.2f | " % (na + "~" + nb, r["adf"], r["hurst"], r["hl"] if r["hl"] < 9e8 else -1, r["corr"] or 0)
        if not r["tradeable"]:
            print(line + "NOT cointegrated"); continue
        tr = _z_backtest(y, x)
        n, wr, ex, t = _stat(tr)
        if n < MIN_N:
            print(line + "tradeable แต่ n=%d น้อยไป" % n); continue
        k = int(n * 0.7); oos = _stat(tr[k:])[2]
        nexp = np.array([_z_backtest(y, x, force_rand=True, seed=s).mean() for s in range(120)])
        p = float((nexp >= ex).mean())
        fl = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oos > 0 and p < 0.05) else "—"
        print(line + "TRADEABLE n%d WR%.0f%% exp_R%+.3f t%+.2f OOS%+.3f null-p%.3f [%s]" % (n, wr, ex, t, oos, p, fl))
    print("\nPASS = cointegrated + n≥30 + exp_R>0 + t>2 + OOS>0 + ชนะ matched-null(p<0.05)")
    print("⚠️ equity legs: dividend-drag + idiosyncratic (ไม่ใช่ pure gold). ถ้า PASS → shadow ก่อน live")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
