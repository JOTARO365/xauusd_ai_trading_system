#!/usr/bin/env python
"""scripts/tsmom_btc_wti_backtest.py — TSMOM บน BTC/WTI + drift-null (บทเรียน gold 08-22).

หลัง gold long-breakout ถูก REFUTE ด้วย drift-null (edge = แค่ secular drift + exit convexity),
คราวนี้ทดสอบ BTC/WTI โดย **ใส่ drift-null ตั้งแต่แรก**. คำถามไม่ใช่ "TSMOM ได้กำไรไหม" (drift-up asset
ถือ long ก็บวก) แต่คือ "TSMOM มี **timing skill เหนือสุ่มที่ exposure เท่ากัน** ไหม".

TSMOM (close-based, ตรงกับ tsmom_d1 live): signal = ensemble vote sign(c[i]-c[i-L]) L∈{63,126,252};
ถือ position 1 วันตาม signal, อัปเดตรายวัน (exit-on-flip โดยธรรมชาติ), cost หักตอน flip.

Null ที่วัด (สำคัญ):
  1. buy-hold (drift benchmark) — TSMOM Sharpe ต้องชนะ
  2. **random-sign matched-exposure**: สุ่ม ±1 โดย P(+1) = %long ของ TSMOM (คุม drift exposure ให้เท่ากัน)
     → 1000 sim → p-value ของ excess. นี่คือ null ที่ gold ตกม้าตาย
  3. long-leg vs short-leg decomposition: short ทำเงินหรือ bleed (asset drift-up → short มักเสีย)
  4. period halves stability

data: WTI close-only (AlphaVantage commodity), BTC OHLC (DIGITAL_CURRENCY_DAILY). อ่าน tool-result files ตรง.
read-only · offline (ไม่แตะ MT5/live) · 0 order.
รัน: python scripts/tsmom_btc_wti_backtest.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TR = os.path.join(os.path.expanduser("~"), ".claude", "projects",
                   "D--claude-workspace-xauusd-ai-trading-system",
                   "8753aacd-c36b-49f7-88e5-e6a3c9fac75f", "tool-results")
_WTI = os.path.join(_TR, "mcp-alphavantage-WTI-1787349044197.txt")
_BTC = os.path.join(_TR, "mcp-alphavantage-DIGITAL_CURRENCY_DAILY-1787349044877.txt")

LS = (63, 126, 252)                                          # ensemble lookback (ตรง tsmom_d1)
SEED = 12345                                                 # fix (Math.random ห้ามใน workflow; ที่นี่ script ปกติ)


def _load_wti():
    d = json.load(open(_WTI, encoding="utf-8"))["data"]
    rows = [(x["date"], float(x["value"])) for x in d if x["value"] not in (".", "", None)]
    rows.sort()                                              # เก่า→ใหม่
    return np.array([r[1] for r in rows], float)


def _load_btc():
    ts = json.load(open(_BTC, encoding="utf-8"))["Time Series (Digital Currency Daily)"]
    rows = sorted((k, float(v["4. close"])) for k, v in ts.items())
    return np.array([r[1] for r in rows], float)


def _tsmom_signal(c):
    """ensemble vote: sign ของ majority ของ sign(c[i]-c[i-L]). คืน array s[i]∈{-1,0,+1}, causal."""
    n = len(c); s = np.zeros(n)
    for i in range(max(LS), n):
        votes = sum(np.sign(c[i] - c[i - L]) for L in LS)
        s[i] = np.sign(votes)
    return s


def _daily_ret(c):
    r = np.zeros(len(c))
    r[:-1] = (c[1:] - c[:-1]) / c[:-1]                       # r[i] = return จาก i→i+1
    return r


def _sharpe_t(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2 or x.std(ddof=1) == 0:
        return 0.0, 0.0, 0.0
    mu = x.mean(); sd = x.std(ddof=1)
    return mu * 252, mu / sd * math.sqrt(252), mu / (sd / math.sqrt(n))   # annRet, annSharpe, t


def analyze(name, c, cost_bps):
    start = max(LS)
    s = _tsmom_signal(c)
    r = _daily_ret(c)
    idx = np.arange(start, len(c) - 1)                       # วันที่มี signal + มี next-day return
    sig = s[idx]; ret = r[idx]
    flips = np.abs(np.diff(np.concatenate([[0], sig]))) > 0  # จุดเปลี่ยน position → cost
    cost = flips.astype(float) * (cost_bps / 1e4)
    strat = sig * ret - cost
    bh = ret                                                 # buy-hold (always long)

    aR, aS, t = _sharpe_t(strat)
    bR, bS, bt = _sharpe_t(bh)
    pct_long = float((sig > 0).mean()); pct_short = float((sig < 0).mean())
    long_leg = strat[sig > 0]; short_leg = strat[sig < 0]
    _, lS, _ = _sharpe_t(long_leg) if len(long_leg) > 2 else (0, 0, 0)
    _, sS, _ = _sharpe_t(short_leg) if len(short_leg) > 2 else (0, 0, 0)
    short_mean = float(short_leg.mean()) if len(short_leg) else float("nan")

    # null: random-sign matched-exposure (P(+1)=pct_long, P(-1)=pct_short, else 0) — คุม drift exposure
    rng = np.random.default_rng(SEED)
    p_flat = 1 - pct_long - pct_short
    null_sh = np.empty(1000)
    for k in range(1000):
        u = rng.random(len(sig))
        rs = np.where(u < pct_long, 1.0, np.where(u < pct_long + pct_short, -1.0, 0.0))
        fl = np.abs(np.diff(np.concatenate([[0], rs]))) > 0
        rr = rs * ret - fl.astype(float) * (cost_bps / 1e4)
        _, ns, _ = _sharpe_t(rr)
        null_sh[k] = ns
    p_val = float((null_sh >= aS).mean())                    # 1-sided: null Sharpe ≥ TSMOM Sharpe

    # period halves stability
    h = len(strat) // 2
    _, s1, _ = _sharpe_t(strat[:h]); _, s2, _ = _sharpe_t(strat[h:])

    print(f"\n--- {name} (n_days={len(sig)}, cost={cost_bps}bps/flip, %long={pct_long*100:.0f} "
          f"%short={pct_short*100:.0f} %flat={p_flat*100:.0f}) ---")
    print(f"  TSMOM      annRet{aR*100:+6.1f}% Sharpe{aS:+.2f} t{t:+.2f}")
    print(f"  buy-hold   annRet{bR*100:+6.1f}% Sharpe{bS:+.2f} t{bt:+.2f}  (drift benchmark)")
    print(f"  null-sign  Sharpe mean{null_sh.mean():+.2f} sd{null_sh.std():.2f} 95pct{np.percentile(null_sh,95):+.2f}")
    print(f"  >>> TSMOM vs matched-exposure-random:  p={p_val:.3f}  "
          f"{'TIMING SKILL' if p_val<0.05 else 'NO skill beyond drift'}")
    print(f"  legs: long Sharpe{lS:+.2f} · short Sharpe{sS:+.2f} short_mean_daily{short_mean*100:+.3f}% "
          f"{'(short bleeds)' if short_mean<0 else '(short adds)'}")
    print(f"  stability: half1 Sharpe{s1:+.2f} · half2 Sharpe{s2:+.2f} "
          f"{'STABLE' if (s1>0 and s2>0) else 'unstable'}")
    return p_val, aS


def main():
    print("=== TSMOM BTC/WTI + drift-null (บทเรียน gold: วัด timing-skill เหนือ matched-exposure random) ===")
    print("VERDICT ที่สนใจ: p<0.05 vs matched-random = มี timing skill จริง (ไม่ใช่แค่ ride drift)")
    wti = _load_wti(); btc = _load_btc()
    analyze("WTI daily (close-only, spot)", wti, cost_bps=5)
    analyze("BTC daily (close)", btc, cost_bps=10)
    print("\n⚠️ ถ้า p≥0.05 = TSMOM ไม่ชนะสุ่มที่ exposure เท่ากัน = 'edge' เป็นแค่ drift (เหมือน gold breakout).")
    print("⚠️ short leg bleed + %long สูง = สัญญาณว่ากำไรมาจาก long-drift ไม่ใช่ two-sided timing.")
    print("⚠️ WTI = spot close (AV) ไม่ใช่ futures/MT5 OHLC — ไม่มี intrabar SL; ต่างจาก tsmom_d1 live เล็กน้อย.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
