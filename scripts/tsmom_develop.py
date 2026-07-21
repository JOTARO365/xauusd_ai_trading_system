#!/usr/bin/env python
"""tsmom_develop.py — พัฒนา/validate TSMOM-D1 (validated winner จาก strategy search) แบบ proper.

TSMOM (Moskowitz-Ooi-Pedersen): position = sign(trailing L-day return), vol-targeted, flip เมื่อ signal เปลี่ยน.
ประเมินแบบ position-based (continuous, net cost) ไม่ใช่ discrete SL/TP screen. ตรวจ:
- L-sweep robustness (plateau ไม่ใช่ cliff)  - net Sharpe/return/maxDD  - per-quartile consistency
- deflated Sharpe (นับ trials รวม)  - long-only vs long-short  - turnover/cost drag
รัน: & $PY scripts\tsmom_develop.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ANN = 252                      # trading days/year
SPREAD = 0.30                  # price units/turnover (~30 pips gold) — cost ต่อการปรับ position 1 หน่วย
TARGET_VOL = 0.10 / np.sqrt(ANN)   # daily target vol (10% annual)


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_d1.json"))), dtype=float)
    return d[:, 0], d[:, 4]     # ts, close


def _metrics(sret):
    """คืน dict metric จาก daily strategy returns (net)."""
    sret = np.asarray(sret)
    sret = sret[np.isfinite(sret)]
    n = len(sret)
    if n < 30 or sret.std() == 0:
        return None
    sharpe = sret.mean() / sret.std() * np.sqrt(ANN)
    eq = np.cumprod(1 + sret); dd = 1 - eq / np.maximum.accumulate(eq)
    return {"n": n, "sharpe": sharpe, "cagr": eq[-1] ** (ANN / n) - 1,
            "maxdd": dd.max(), "wr": (sret > 0).mean(), "total": eq[-1] - 1}


def backtest(close, L, mode="ls"):
    """position-based TSMOM. mode: 'ls'=long-short, 'lo'=long-only. คืน (daily net returns, positions)."""
    ret = np.zeros(len(close)); ret[1:] = np.diff(close) / close[:-1]
    # realized vol สำหรับ vol-target (EWMA)
    vol = np.zeros(len(close)); vol[0] = abs(ret[0]) + 1e-6
    for i in range(1, len(close)):
        vol[i] = np.sqrt(0.94 * vol[i - 1] ** 2 + 0.06 * ret[i] ** 2)
    pos = np.zeros(len(close))
    for t in range(L, len(close)):
        mom = np.sign(close[t] - close[t - L])
        if mode == "lo":
            mom = max(mom, 0.0)
        w = mom * min(TARGET_VOL / (vol[t] + 1e-9), 3.0)      # vol-target, cap leverage 3
        pos[t] = w
    sret = np.zeros(len(close))
    for t in range(L + 1, len(close)):
        turnover = abs(pos[t - 1] - pos[t - 2]) if t >= 2 else abs(pos[t - 1])
        cost = turnover * (SPREAD / close[t - 1])
        sret[t] = pos[t - 1] * ret[t] - cost
    return sret[L + 1:], pos[L:]


def main():
    ts, close = _load()
    print("=" * 88)
    print(f"TSMOM-D1 DEVELOPMENT — gold D1 {len(close)} bars | vol-target 10% ann | cost {SPREAD}/turnover")
    print("=" * 88)

    # 1) L-sweep robustness (plateau?)
    print("\n── 1. L-sweep robustness (long-short) — มองหา plateau ไม่ใช่ cliff ──")
    print(f"  {'L(days)':>8}{'Sharpe':>8}{'CAGR':>8}{'maxDD':>8}{'WR':>7}{'N':>6}")
    Ls = [21, 42, 63, 90, 126, 189, 252]
    sweeps = {}
    for L in Ls:
        sret, _ = backtest(close, L)
        m = _metrics(sret); sweeps[L] = (sret, m)
        if m:
            print(f"  {L:>8}{m['sharpe']:>8.2f}{m['cagr']*100:>7.1f}%{m['maxdd']*100:>7.1f}%{m['wr']*100:>6.1f}%{m['n']:>6}")

    # 2) ensemble (เฉลี่ยหลาย L = robust กว่าเลือกตัวเดียว)
    print("\n── 2. Multi-L ensemble (เฉลี่ย L=63,126,252 — กัน overfit เลือก L เดียว) ──")
    core = [63, 126, 252]
    mn = min(len(sweeps[L][0]) for L in core)
    ens = np.mean([sweeps[L][0][-mn:] for L in core], axis=0)
    me = _metrics(ens)
    print(f"  Sharpe {me['sharpe']:.2f} · CAGR {me['cagr']*100:.1f}% · maxDD {me['maxdd']*100:.1f}% · WR {me['wr']*100:.1f}% · N {me['n']}")

    # 3) per-quartile consistency (edge จริง=ทุกช่วง, artifact=ช่วงเดียว)
    print("\n── 3. Per-quartile consistency (ensemble) — Sharpe แต่ละช่วงเวลา ──")
    q = len(ens) // 4
    qs = [_metrics(ens[i * q:(i + 1) * q]) for i in range(4)]
    print("  " + " | ".join(f"Q{i+1}: Sharpe {m['sharpe']:+.2f}" if m else f"Q{i+1}: n/a" for i, m in enumerate(qs)))
    qpos = sum(1 for m in qs if m and m['sharpe'] > 0)

    # 4) long-only vs long-short (gold มี secular uptrend — LO อาจแค่ beta?)
    print("\n── 4. Long-only vs Long-short (แยก edge จาก secular uptrend) ──")
    for mode, lbl in (("ls", "long-short"), ("lo", "long-only")):
        sret, _ = backtest(close, 126, mode)
        m = _metrics(sret)
        bh = _metrics(np.diff(close[-len(sret) - 1:]) / close[-len(sret) - 1:-1])
        print(f"  {lbl:>11}: Sharpe {m['sharpe']:.2f} CAGR {m['cagr']*100:.1f}% | buy&hold Sharpe {bh['sharpe']:.2f}")

    # 5) deflated Sharpe (นับ trials: 7 L × 2 mode + 13 strategies ก่อนหน้า ≈ 27)
    N_TRIALS = 27
    from math import sqrt, log
    # t-stat ของกลยุทธ์ (Sharpe เป็น z-score) เทียบ expected-max-z ของ N null trials (Bailey-LdP)
    t_stat = me['sharpe'] * np.sqrt(me['n'] / ANN)   # Sharpe × √(ปี) = t-stat
    emax_z = sqrt(2 * log(N_TRIALS)) - (log(log(N_TRIALS)) + log(4 * np.pi)) / (2 * sqrt(2 * log(N_TRIALS)))
    print(f"\n── 5. Deflated Sharpe (t-stat vs expected-max-z ของ ~{N_TRIALS} trials) ──")
    print(f"  strategy t-stat ≈ {t_stat:.2f}  vs  expected-max-z(null,{N_TRIALS}) ≈ {emax_z:.2f}")
    print(f"  → {'ผ่าน (survives deflation)' if t_stat > emax_z else 'ไม่ผ่าน (ต่ำกว่า noise ceiling)'}")

    print("\n" + "=" * 88)
    verdict = "แข็งแรง" if (me['sharpe'] > 0.5 and qpos >= 3) else ("อ่อน/ต้องระวัง" if me['sharpe'] > 0 else "ไม่ผ่าน")
    print(f"VERDICT: ensemble Sharpe {me['sharpe']:.2f}, quartile+ {qpos}/4 → {verdict}")
    print("หมายเหตุ: TSMOM WR<50% ปกติ (trend-following) — ตัดสินที่ Sharpe/EV net ไม่ใช่ WR")


if __name__ == "__main__":
    main()
