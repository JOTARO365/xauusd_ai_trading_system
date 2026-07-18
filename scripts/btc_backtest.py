#!/usr/bin/env python
"""
btc_backtest.py — B1: BTC algorithm library + backtest harness (OFFLINE, exploratory)

quant-skill deterministic algorithms บน BTC daily OHLCV:
  • momentum-breakout : close ทะลุ N-day high/low → เข้าตามทิศ (trending)
  • mean-reversion    : close แตะ Bollinger ±kσ → เข้าสวน (range/mean-revert)
SL/TP = ATR-based (self-scale ตาม vol BTC, ไม่ใช่ fixed pips). RR≥2. net of fee.

⚠️ EXPLORATORY เท่านั้น — daily 1 ปี = few trades + single path + coarse. **ไม่ใช่ validation**:
   ยังไม่มี CPCV/PBO/Deflated-Sharpe/min-N (ต้องทำก่อน enable — docs/VALIDATION_CHECKLIST.md).
   ใช้เช็คว่า harness ทำงาน + ดูภาพหยาบ ไม่ใช่พิสูจน์ edge.

รัน: & $PY scripts\\btc_backtest.py   (ต้องมี data/btc_daily_raw.json จาก Binance ก่อน)
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
_HOURLY = os.path.join(_BASE, "data", "btc_hourly_raw.json")
_DAILY  = os.path.join(_BASE, "data", "btc_daily_raw.json")
RAW     = _HOURLY if os.path.exists(_HOURLY) else _DAILY   # hourly = ไม้เยอะพอมีวินัย

# ── params (จะเป็น N ที่ต้อง count ตอน validate จริง) ──
BRK_LOOKBACK = 20      # breakout: N-day high/low
ATR_P        = 14
ATR_SL       = 1.5     # SL = 1.5·ATR
RR           = 2.0     # TP = RR·SL
BB_P, BB_K   = 20, 2.0 # mean-reversion band
TIME_STOP    = 20      # ปิดถ้าไม่ถึง SL/TP ใน N แท่ง
FEE_PCT      = 0.1     # ต่อ side (Binance spot ~0.1%) → round-trip 0.2%


def load_ohlcv():
    d = json.load(open(RAW))
    # Binance kline: [openTime, open, high, low, close, volume, ...]
    o = np.array([float(k[1]) for k in d]); h = np.array([float(k[2]) for k in d])
    l = np.array([float(k[3]) for k in d]); c = np.array([float(k[4]) for k in d])
    return o, h, l, c


def atr(h, l, c, p):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    for i in range(p, len(c)):
        out[i] = tr[i - p:i].mean()
    return out


def sma(x, p):
    out = np.full(len(x), np.nan)
    for i in range(p, len(x)):
        out[i] = x[i - p + 1:i + 1].mean()
    return out


def rollstd(x, p):
    out = np.full(len(x), np.nan)
    for i in range(p, len(x)):
        out[i] = x[i - p + 1:i + 1].std()
    return out


def signals(o, h, l, c):
    """คืน list ของ (i, algo, direction) — จุดที่ precondition ยิง."""
    a = atr(h, l, c, ATR_P)
    m = sma(c, BB_P); s = rollstd(c, BB_P)
    sigs = []
    for i in range(max(BRK_LOOKBACK, BB_P, ATR_P) + 1, len(c) - 1):
        if np.isnan(a[i]) or a[i] == 0:
            continue
        hh = h[i - BRK_LOOKBACK:i].max(); ll = l[i - BRK_LOOKBACK:i].min()
        # momentum-breakout
        if c[i] > hh:
            sigs.append((i, "breakout", "BUY"))
        elif c[i] < ll:
            sigs.append((i, "breakout", "SELL"))
        # mean-reversion (Bollinger)
        if not np.isnan(m[i]):
            if c[i] < m[i] - BB_K * s[i]:
                sigs.append((i, "mean_rev", "BUY"))
            elif c[i] > m[i] + BB_K * s[i]:
                sigs.append((i, "mean_rev", "SELL"))
    return sigs, a


def backtest():
    o, h, l, c = load_ohlcv()
    sigs, a = signals(o, h, l, c)
    trades = []
    open_until = -1   # กัน overlap: 1 ไม้/ช่วง
    for i, algo, d in sigs:
        if i <= open_until:
            continue
        entry = c[i]; A = a[i]
        sign = 1 if d == "BUY" else -1
        sl = entry - sign * ATR_SL * A
        tp = entry + sign * RR * ATR_SL * A
        risk = abs(entry - sl)
        outcome = None
        for j in range(i + 1, min(i + 1 + TIME_STOP, len(c))):
            if d == "BUY":
                if l[j] <= sl: outcome = ("LOSS", sl, j); break
                if h[j] >= tp: outcome = ("WIN", tp, j); break
            else:
                if h[j] >= sl: outcome = ("LOSS", sl, j); break
                if l[j] <= tp: outcome = ("WIN", tp, j); break
        if outcome is None:
            j = min(i + TIME_STOP, len(c) - 1)
            outcome = ("TIME", c[j], j)   # ปิดที่ราคาปิด
        res, px, jx = outcome
        gross_r = sign * (px - entry) / risk
        cost_r = (2 * FEE_PCT / 100) * entry / risk   # round-trip fee เป็นสัดส่วนของ risk
        net_r = gross_r - cost_r
        open_until = jx
        trades.append({"i": i, "algo": algo, "dir": d, "res": res, "gross_r": gross_r,
                       "net_r": net_r, "hold": jx - i})
    return trades, len(c)


def _boot_ci(x, B=3000):
    """95% bootstrap CI ของ mean (deterministic seed)."""
    x = np.asarray(x, float); rng = np.random.default_rng(0)
    means = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(B)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _line(name, ts):
    n = len(ts)
    if not n:
        print(f"  [{name:10}] n=0"); return
    nets = np.array([t["net_r"] for t in ts])
    wins = int((nets > 0).sum()); net = nets.sum(); mean = nets.mean()
    sd = nets.std(); sharpe = mean / sd if sd > 0 else 0
    eq = np.cumsum(nets); dd = float((np.maximum.accumulate(eq) - eq).max())
    print(f"  [{name:10}] n={n:4} WR={wins/n*100:3.0f}%  net {net:+7.1f}R  "
          f"avg {mean:+.3f}R  Sharpe(trade) {sharpe:+.2f}  maxDD {dd:.1f}R")


def report(trades, nbars):
    tf = "hourly" if "hourly" in RAW else "daily"
    print("=" * 70)
    print(f"BTC BACKTEST ({tf}, {nbars} bars ≈ 1 ปี) — ระบบ algorithm library ที่เราเขียน")
    print("=" * 70)
    if not trades:
        print("ไม่มีไม้"); return

    print("\n── ภาพรวม + per-algorithm (net of fee 0.2% round-trip) ──")
    _line("ALL", trades)
    for algo in ("breakout", "mean_rev"):
        _line(algo, [t for t in trades if t["algo"] == algo])

    nets = [t["net_r"] for t in trades]
    lo, hi = _boot_ci(nets)
    sig = "ต่างจาก 0 อย่างมีนัย ✅" if lo > 0 else ("แย่กว่า 0 ชัด ❌" if hi < 0 else "คร่อม 0 = แยกจาก noise ไม่ได้ ⚠️")
    print(f"\n── หลักฐานทางสถิติ (net R/ไม้) ──")
    print(f"  mean net-R 95% bootstrap CI: [{lo:+.3f}, {hi:+.3f}]  → {sig}")

    # OOS split (in-sample 70% / out-of-sample 30% ตามเวลา — ไม่ tune บน OOS)
    cut = 0.7 * nbars
    is_t = [t for t in trades if t["i"] < cut]; oos_t = [t for t in trades if t["i"] >= cut]
    print(f"\n── Out-of-sample test (แบ่งตามเวลา, ไม่ tune บนส่วน OOS) ──")
    _line("in-sample", is_t)
    _line("OUT-SAMPLE", oos_t)
    if oos_t:
        oos_net = sum(t["net_r"] for t in oos_t)
        print(f"  → OOS net {oos_net:+.1f}R  {'ยืนได้นอกกลุ่ม fit ✅' if oos_net>0 else 'พังนอก in-sample ❌ (สัญญาณ overfit)'}")

    print(f"\n  params (=trials ต้องนับ): brk{BRK_LOOKBACK} atr{ATR_P}×{ATR_SL} RR{RR} BB{BB_P}×{BB_K} ts{TIME_STOP} fee{FEE_PCT}%")
    print("\n⚠️  ยังไม่ครบ VALIDATION_CHECKLIST: นี่คือ OOS+bootstrap (ยังไม่มี CPCV/PBO/Deflated-Sharpe เต็ม,")
    print("   param ยังไม่ sweep = trial-count ยังไม่มี, single symbol/path). ใช้ตัดสิน 'มี/ไม่มีสัญญาณ' หยาบ ๆ ก่อน enable.")


if __name__ == "__main__":
    t, n = backtest()
    report(t, n)
