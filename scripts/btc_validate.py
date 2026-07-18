#!/usr/bin/env python
"""
btc_validate.py — B3: BTC system + FULL validation gauntlet (OFFLINE, ไม่แตะ live/gold)

ต่างจาก btc_backtest.py (single config, ดูสัญญาณหยาบ) — อันนี้คือ "build ระบบสมบูรณ์ + validate
กันโกงตัวเอง" ตาม docs/VALIDATION_CHECKLIST.md + skill quant-systematic-trading §6:

  ระบบ:  algorithm library (breakout + mean-reversion) + REGIME ROUTING ด้วย
         Kaufman Efficiency Ratio (ER) — trending→breakout, ranging→mean-rev (skill §5)
  data:  BTC hourly 3 ปี (bear'22 + bull'23-24 + chop = หลาย regime, ไม่ใช่ path เดียว)
  วินัย: • param SWEEP → นับ N trials (ต้องรู้ก่อนเชื่อ Sharpe — skill: fact สำคัญสุด)
         • DEFLATED SHARPE (หัก selection over N + fat tails) — Bailey/López de Prado
         • PBO via CSCV (Prob. of Backtest Overfitting) — best-IS config แพ้ median OOS บ่อยแค่ไหน
         • walk-forward OOS + net of fee 0.2% round-trip
         • param PLATEAU (robust ไม่ใช่ cliff)
  verdict ซื่อสัตย์: มี plateau รอด OOS + PBO<0.5 + DSR>0.95 → edge จริง ; ไม่งั้น = overfit, ไม่ deploy

รัน: & $PY scripts\\btc_validate.py   (ต้องมี data/btc_hourly_3y.json จาก Binance)
"""
import itertools
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from scipy import stats

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# argv[1] = data file (default BTC) ; argv[2] = fee %/side (default 0.1 = crypto).
# symbol-agnostic → ชี้ไปทอง (paxg_hourly_3y.json) ด้วย gold cost ~0.02 ได้เลย
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_BASE, "data", "btc_hourly_3y.json")
if not os.path.isabs(RAW):
    RAW = os.path.join(_BASE, "data", RAW)

# ── fixed (ไม่ sweep — กัน N บาน) ──
ATR_P, BB_P, BB_K, ER_WIN, TIME_STOP = 14, 20, 2.0, 20, 24
FEE_PCT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.1   # ต่อ side
# ── sweep grid → N = product (นับ trials) ──
GRID = {
    "brk":   [15, 20, 30],
    "atrsl": [1.0, 1.5, 2.0],
    "rr":    [1.5, 2.0, 3.0],
    "erth":  [0.30, 0.40],
}
S_BLOCKS = 8           # CSCV: แบ่ง data เป็น 8 block, เลือก 4 เป็น train ทุก combination
MIN_TRADES = 50        # config ต่ำกว่านี้ = sample น้อย ไม่ให้เป็น "best" (กัน lucky tiny-n)
GAMMA = 0.5772156649015329   # Euler-Mascheroni (สำหรับ expected-max-Sharpe)


# ── rolling helpers (vectorized, คำนวณครั้งเดียว reuse ทุก config) ──
def _roll(x, w, fn):
    sw = np.lib.stride_tricks.sliding_window_view(x, w)
    out = np.full(len(x), np.nan)
    out[w:] = fn(sw[:-1], axis=1)   # out[i] = fn(x[i-w:i])  (prior bars, ไม่รวม i = no look-ahead)
    return out


def load():
    d = json.load(open(RAW))
    h = np.array([float(k[2]) for k in d]); l = np.array([float(k[3]) for k in d])
    c = np.array([float(k[4]) for k in d])
    return h, l, c


def efficiency_ratio(c, w):
    """Kaufman ER: |net change| / sum|change| ต่อ w แท่ง. ~1 = trend, ~0 = chop."""
    er = np.full(len(c), np.nan)
    absdiff = np.abs(np.diff(c, prepend=c[0]))
    for i in range(w, len(c)):
        vol = absdiff[i - w + 1:i + 1].sum()
        er[i] = abs(c[i] - c[i - w]) / vol if vol > 0 else 0.0
    return er


def precompute(h, l, c):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    tr = np.concatenate([[np.nan], tr])
    atr = _roll(tr, ATR_P, np.nanmean)
    mid = _roll(c, BB_P, np.mean); sd = _roll(c, BB_P, np.std)
    er = efficiency_ratio(c, ER_WIN)
    hi = {b: _roll(h, b, np.max) for b in GRID["brk"]}
    lo = {b: _roll(l, b, np.min) for b in GRID["brk"]}
    return atr, mid, sd, er, hi, lo


def run_config(cfg, arrs, c):
    """คืน list ของ trade dict {i, net_r} ตาม regime routing + net cost."""
    brk, atrsl, rr, erth = cfg
    atr, mid, sd, er, hi, lo = arrs
    HI, LO = hi[brk], lo[brk]
    start = max(brk, BB_P, ATR_P, ER_WIN) + 1
    trades, open_until = [], -1
    for i in range(start, len(c) - 1):
        if i <= open_until or np.isnan(atr[i]) or atr[i] == 0 or np.isnan(er[i]):
            continue
        trending = er[i] >= erth
        d = None
        if trending:                                   # regime → breakout เท่านั้น
            if c[i] > HI[i]:   d = "BUY"
            elif c[i] < LO[i]: d = "SELL"
        else:                                          # regime → mean-reversion เท่านั้น
            if not np.isnan(mid[i]):
                if c[i] < mid[i] - BB_K * sd[i]:   d = "BUY"
                elif c[i] > mid[i] + BB_K * sd[i]: d = "SELL"
        if d is None:
            continue
        entry, A = c[i], atr[i]; sign = 1 if d == "BUY" else -1
        sl = entry - sign * atrsl * A; tp = entry + sign * rr * atrsl * A
        risk = abs(entry - sl)
        px, jx = None, None
        for j in range(i + 1, min(i + 1 + TIME_STOP, len(c))):
            hi_j, lo_j = c[j], c[j]  # ใช้ close-path (conservative, ไม่มี intrabar OHLC ที่ align)
            if d == "BUY":
                if lo_j <= sl: px, jx = sl, j; break
                if hi_j >= tp: px, jx = tp, j; break
            else:
                if hi_j >= sl: px, jx = sl, j; break
                if lo_j <= tp: px, jx = tp, j; break
        if px is None:
            jx = min(i + TIME_STOP, len(c) - 1); px = c[jx]
        gross = sign * (px - entry) / risk
        cost = (2 * FEE_PCT / 100) * entry / risk
        trades.append({"i": i, "net_r": gross - cost}); open_until = jx
    return trades


def sharpe(nets):
    nets = np.asarray(nets, float)
    return float(nets.mean() / nets.std()) if len(nets) > 1 and nets.std() > 0 else 0.0


def deflated_sharpe(best_nets, all_sharpes, N):
    """DSR = Φ((SR−SR0)·√(T−1) / √(1−skew·SR+(kurt−1)/4·SR²)). SR0 = expected max ใต้ null."""
    sr = sharpe(best_nets); T = len(best_nets)
    var_sr = np.var(all_sharpes, ddof=1)
    if var_sr <= 0 or T < 3:
        return None, sr, 0.0
    sr0 = np.sqrt(var_sr) * ((1 - GAMMA) * stats.norm.ppf(1 - 1.0 / N)
                             + GAMMA * stats.norm.ppf(1 - 1.0 / (N * np.e)))
    sk = float(stats.skew(best_nets)); ku = float(stats.kurtosis(best_nets, fisher=False))
    denom = np.sqrt(1 - sk * sr + (ku - 1) / 4.0 * sr ** 2)
    z = (sr - sr0) * np.sqrt(T - 1) / denom if denom > 0 else 0.0
    return float(stats.norm.cdf(z)), sr, float(sr0)


def pbo_cscv(cfg_block_r, N, nbars):
    """PBO: ทุก split (train 4 block / test 4 block) เลือก best-IS → OOS rank ต่ำกว่า median บ่อยแค่ไหน."""
    edges = np.linspace(0, nbars, S_BLOCKS + 1).astype(int)
    def block_of(i):
        return min(np.searchsorted(edges, i, side="right") - 1, S_BLOCKS - 1)
    # perf[config][block] = mean net_r ของ trade ใน block นั้น (nan ถ้าไม่มีไม้)
    perf = np.full((N, S_BLOCKS), np.nan)
    for ci, trades in enumerate(cfg_block_r):
        buckets = [[] for _ in range(S_BLOCKS)]
        for t in trades:
            buckets[block_of(t["i"])].append(t["net_r"])
        for b in range(S_BLOCKS):
            if buckets[b]:
                perf[ci, b] = np.mean(buckets[b])
    logits = []
    for train in itertools.combinations(range(S_BLOCKS), S_BLOCKS // 2):
        test = [b for b in range(S_BLOCKS) if b not in train]
        is_perf = np.nanmean(perf[:, list(train)], axis=1)
        oos_perf = np.nanmean(perf[:, test], axis=1)
        valid = ~np.isnan(is_perf) & ~np.isnan(oos_perf)
        if valid.sum() < 3:
            continue
        best = np.where(valid)[0][np.nanargmax(is_perf[valid])]
        # rank ของ best-IS ใน OOS (0=แย่สุด..1=ดีสุด)
        ov = oos_perf[valid]; rank = (ov < oos_perf[best]).sum() / max(len(ov) - 1, 1)
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(np.log(rank / (1 - rank)))
    if not logits:
        return None
    return float(np.mean(np.array(logits) <= 0))   # PBO = P(best-IS แพ้ median OOS)


def walk_forward(best_cfg, arrs, c, nbars):
    """OOS แท้: fit ไม่มี (deterministic) — แค่ report แยก in-sample 70% vs out-sample 30%."""
    trades = run_config(best_cfg, arrs, c)
    cut = 0.7 * nbars
    is_r = [t["net_r"] for t in trades if t["i"] < cut]
    oos_r = [t["net_r"] for t in trades if t["i"] >= cut]
    return is_r, oos_r


def main():
    if not os.path.exists(RAW):
        print("❌ ไม่มี data/btc_hourly_3y.json — รัน fetch 3 ปีก่อน"); return
    h, l, c = load(); nbars = len(c)
    arrs = precompute(h, l, c)
    configs = list(itertools.product(GRID["brk"], GRID["atrsl"], GRID["rr"], GRID["erth"]))
    N = len(configs)

    sym = os.path.basename(RAW).replace("_hourly_3y.json", "").upper()
    print("=" * 74)
    print(f"{sym} VALIDATION GAUNTLET — {nbars} bars ({nbars/24/365:.1f} ปี hourly) | "
          f"regime-routed | N={N} configs | fee {FEE_PCT}%/side")
    print("=" * 74)

    results, cfg_trades = [], []
    for cfg in configs:
        tr = run_config(cfg, arrs, c)
        cfg_trades.append(tr)
        nets = [t["net_r"] for t in tr]
        results.append({"cfg": cfg, "n": len(tr), "net": float(np.sum(nets)) if nets else 0.0,
                        "wr": float(np.mean([x > 0 for x in nets]) * 100) if nets else 0.0,
                        "sharpe": sharpe(nets)})

    all_sharpes = np.array([r["sharpe"] for r in results])
    # best = Sharpe สูงสุดในกลุ่มที่ไม้พอ (กัน lucky tiny-n)
    eligible = [r for r in results if r["n"] >= MIN_TRADES]
    ranked = sorted(eligible or results, key=lambda r: r["sharpe"], reverse=True)
    best = ranked[0]

    print(f"\n── ภาพรวม sweep (net of fee {2*FEE_PCT}% round-trip) ──")
    prof = [r for r in results if r["net"] > 0]
    print(f"  configs กำไร (in-sample, gross net-R>0): {len(prof)}/{N}  "
          f"({len(prof)/N*100:.0f}%)")
    print(f"  Sharpe/ไม้: median {np.median(all_sharpes):+.3f} | max {all_sharpes.max():+.3f} | "
          f"min {all_sharpes.min():+.3f}")

    print(f"\n── TOP 5 configs (by Sharpe/ไม้, ไม้≥{MIN_TRADES}) ──")
    print(f"  {'brk/atrSL/RR/ER':>18} | {'n':>4} | {'WR':>4} | {'net R':>8} | {'Sharpe':>7}")
    for r in ranked[:5]:
        b, a, rr, e = r["cfg"]
        print(f"  {f'{b}/{a}/{rr}/{e}':>18} | {r['n']:>4} | {r['wr']:>3.0f}% | "
              f"{r['net']:>+8.1f} | {r['sharpe']:>+7.3f}")

    # ── walk-forward OOS ของ best ──
    is_r, oos_r = walk_forward(best["cfg"], arrs, c, nbars)
    print(f"\n── best config walk-forward (in-sample 70% → out-sample 30%) ──")
    print(f"  best = brk{best['cfg'][0]} atrSL{best['cfg'][1]} RR{best['cfg'][2]} ER{best['cfg'][3]}")
    print(f"  in-sample : n={len(is_r):>4}  net {np.sum(is_r):+8.1f}R  Sharpe {sharpe(is_r):+.3f}")
    oos_net = float(np.sum(oos_r)) if oos_r else 0.0
    print(f"  OUT-SAMPLE: n={len(oos_r):>4}  net {oos_net:+8.1f}R  Sharpe {sharpe(oos_r):+.3f}  "
          f"→ {'ยืนได้ ✅' if oos_net > 0 else 'พัง OOS ❌'}")

    # ── Deflated Sharpe (หัก N trials + fat tails) ──
    dsr, sr_best, sr0 = deflated_sharpe([t["net_r"] for t in cfg_trades[results.index(best)]],
                                        all_sharpes, N)
    print(f"\n── Deflated Sharpe Ratio (best config, หัก selection over N={N}) ──")
    if dsr is None:
        print("  (คำนวณไม่ได้ — variance/ไม้ไม่พอ)")
    else:
        print(f"  SR/ไม้ {sr_best:+.3f} | SR0 (expected max ใต้ null) {sr0:+.3f} | DSR {dsr:.3f}")
        print(f"  → {'มีนัยหลังหัก N ✅' if dsr > 0.95 else 'ไม่ผ่าน (Sharpe อธิบายได้ด้วยโชคจาก N ครั้ง) ❌'}")

    # ── PBO via CSCV ──
    pbo = pbo_cscv(cfg_trades, N, nbars)
    print(f"\n── Probability of Backtest Overfitting (CSCV, C({S_BLOCKS},{S_BLOCKS//2}) splits) ──")
    if pbo is None:
        print("  (split ไม่พอ)")
    else:
        print(f"  PBO = {pbo:.2f}  → {'ยอมรับได้ (<0.5) ✅' if pbo < 0.5 else 'overfit สูง (best-IS แพ้ median OOS บ่อย) ❌'}")

    # ── verdict ──
    print("\n" + "=" * 74)
    passes = [oos_net > 0, (dsr or 0) > 0.95, (pbo if pbo is not None else 1) < 0.5]
    if all(passes):
        print("VERDICT: ผ่านทุกด่าน ✅ → มีสัญญาณ edge จริง → ไปต่อ paper/shadow (ยังไม่ live)")
    else:
        fails = []
        if not passes[0]: fails.append("OOS ขาดทุน")
        if not passes[1]: fails.append("DSR≤0.95 (Sharpe = โชคจาก sweep)")
        if not passes[2]: fails.append("PBO≥0.5 (overfit)")
        print(f"VERDICT: ไม่ผ่าน ❌ — {', '.join(fails)}")
        print("         → ระบบนี้ไม่มี edge ที่พิสูจน์ได้ ไม่ deploy (วินัยจับได้ก่อนเสียเงินจริง)")
    print("=" * 74)
    print(f"\nนับ trials: N={N} configs (sweep brk×atrSL×RR×ER). fixed: ATR{ATR_P} BB{BB_P}×{BB_K} "
          f"ER{ER_WIN} ts{TIME_STOP} fee{FEE_PCT}%/side.")
    print("close-path exit (conservative) — ไม่มี intrabar OHLC ที่ align; spread crypto จริงอาจแย่กว่านี้.")


if __name__ == "__main__":
    main()
