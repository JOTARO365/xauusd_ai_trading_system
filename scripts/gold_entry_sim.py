#!/usr/bin/env python
"""
gold_entry_sim.py — B4: OFFLINE replay ของ ENTRY algo จริงของบอททอง (deterministic ชั้น, 0-LLM)

จุดประสงค์: ตอบว่า "ชั้น deterministic ของทอง (structure signal + SL/TP จริง) มี EV เองมั้ย"
โดย **reuse ฟังก์ชันจริงของ chart_watcher** (ไม่ reimplement = fidelity):
  calculate_indicators / find_swing_levels / find_key_levels / scan_entry_setups /
  _sane_atr / calc_sl_from_wick / compute_tp_pips
แทน LLM direction ด้วย scan["best_direction"] (analogue deterministic ที่ chart_watcher คำนวณเองอยู่แล้ว).

⚠️ ขอบเขต: นี่ = บอท "ลบ LLM ลบข่าว" — ทดสอบ structure+SL/TP algo เท่านั้น ไม่ใช่ decision จริงเต็ม
   (LLM เป็นคนตัดสิน direction จริง; gate ที่อิง conf/ข่าว ยังไม่ใส่ใน MVP นี้ — เพิ่มทีหลังได้).
   ถ้าชั้นนี้ EV บวก = รากฐานดี; ถ้าลบ = edge (ถ้ามี) มาจาก LLM/ข่าว ไม่ใช่ structure.

กฎเหล็ก (บทเรียน close-path artifact): **intrabar M15 H/L fill (SL-priority) + spread cost + ไม่ look-ahead**
  (higher-TF ใช้เฉพาะแท่งที่ปิดแล้ว ณ เวลา decision).

data: data/xau_{m15,h1,h4,d1,w1}.json จาก scripts/export_xau_history.py (GOLD# MT5 จริง).
รัน: & $PY scripts\\gold_entry_sim.py            (spread 30 pt default)
     & $PY scripts\\gold_entry_sim.py 40         (spread 40 pt)
"""
import bisect
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
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)   # รันจาก scripts/ → ต้อง add root ก่อน import agents

from agents.chart_watcher import (
    calculate_indicators, find_swing_levels, find_key_levels,
    scan_entry_setups, _sane_atr, calc_sl_from_wick, compute_tp_pips,
)
POINT = 0.01
TF_SEC = {"m15": 900, "h1": 3600, "h4": 14400, "d1": 86400, "w1": 604800}
# count ต่อ TF (ตรงกับ analyze_chart :1528-1532) + window swing params
WIN = {"h4": (200, 5, 5), "h1": (100, 3, 5), "m15": (100, None, None),
       "d1": (60, 3, 5), "w1": (30, 2, 4)}
TIME_STOP = 192        # m15 แท่ง (~48h) — ปิดที่ market ถ้าไม่ถึง SL/TP
SPREAD_PIPS = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0   # round-trip cost (points)
GAMMA = 0.5772156649015329


def load_tf(name):
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{name}.json")))
    dicts = [{"time": r[0], "open": r[1], "high": r[2], "low": r[3],
              "close": r[4], "tick_volume": r[5]} for r in rows]
    close_t = [r[0] + TF_SEC[name] for r in rows]   # เวลาปิดแท่ง (สำหรับกัน look-ahead)
    return {"rows": rows, "dicts": dicts, "close_t": close_t}


class HTFCache:
    """cache ind-dict ของ higher-TF — recompute เฉพาะเมื่อมีแท่งใหม่ปิด (เร็วขึ้นมาก, ค่าเท่าเดิม)."""
    def __init__(self, tf, data):
        self.tf, self.data = tf, data
        self.count, self.win, self.mx = WIN[tf]
        self.last_idx = -1
        self.cache = None
        self.sr = None

    def at(self, dt):
        # index ของแท่งสุดท้ายที่ปิด <= dt
        j = bisect.bisect_right(self.data["close_t"], dt) - 1
        if j < self.count - 1:
            return None, None
        if j != self.last_idx:
            window = self.data["dicts"][j - self.count + 1: j + 1]
            ind = calculate_indicators(window)
            sr = (find_swing_levels(ind["df"], window=self.win, max_levels=self.mx)
                  if self.win else None)
            self.last_idx, self.cache, self.sr = j, ind, sr
        return self.cache, self.sr


def build_ind_m15(m15, i):
    """m15 ind-dict บน window 100 แท่งจบที่ i (recompute ทุกแท่ง — ถูก, 100 rows)."""
    cnt = WIN["m15"][0]
    if i < cnt - 1:
        return None
    window = m15["dicts"][i - cnt + 1: i + 1]
    return calculate_indicators(window)


def decide(i, m15, m15_ind, caches, keylvl_cache):
    """เรียก scan จริง → (direction, score, sl_pips, tp_pips) หรือ None. ไม่ look-ahead."""
    dt = m15["close_t"][i]
    h4i, h4_sr = caches["h4"].at(dt)
    h1i, h1_sr = caches["h1"].at(dt)
    d1i, d1_sr = caches["d1"].at(dt)
    w1i, w1_sr = caches["w1"].at(dt)
    if h4i is None or h1i is None or d1i is None or w1i is None:
        return None
    # key levels (pdh/pdl/round) จาก h4 df — cache ตาม h4 bar
    key_lvl = keylvl_cache.get(caches["h4"].last_idx)
    if key_lvl is None:
        key_lvl = find_key_levels(h4i["df"])
        keylvl_cache.clear(); keylvl_cache[caches["h4"].last_idx] = key_lvl
    scan = scan_entry_setups(h4i, h1i, m15_ind, h4_sr, h1_sr, key_lvl,
                             d1_sr or {"resistance": [], "support": []},
                             w1_sr or {"resistance": [], "support": []})
    d = scan["best_direction"]
    if d not in ("BUY", "SELL"):
        return None
    h4_atr = _sane_atr(h4i)
    sl_pips = calc_sl_from_wick(m15_ind, d, h4_atr)
    all_levels = h4_sr["resistance"] + h4_sr["support"] + h1_sr["resistance"] + h1_sr["support"]
    price = m15_ind["close"]
    tp_pips = compute_tp_pips(d, price, sl_pips, all_levels)
    return d, scan["best_score"], sl_pips, tp_pips


def run_sim(m15, caches):
    """เดินทุกแท่ง m15 ตอน flat → เจอ signal → เข้าไม้ถัดไป → intrabar fill. 1 ไม้/ครั้ง (no overlap)."""
    rows = m15["rows"]; N = len(rows)
    # warmup: เริ่มเมื่อ higher-TF พร้อม
    start = 300
    trades = []
    keylvl_cache = {}
    i = start
    while i < N - TIME_STOP - 2:
        m15_ind = build_ind_m15(m15, i)
        if m15_ind is None:
            i += 1; continue
        sig = decide(i, m15, m15_ind, caches, keylvl_cache)
        if sig is None:
            i += 1; continue
        d, score, sl_pips, tp_pips = sig
        # เข้าไม้ที่ open ของแท่งถัดไป
        entry_i = i + 1
        entry = rows[entry_i][1]           # open
        sign = 1 if d == "BUY" else -1
        risk = sl_pips * POINT
        sl_px = entry - sign * risk
        tp_px = entry + sign * tp_pips * POINT
        exit_px, exit_i = None, None
        for j in range(entry_i, min(entry_i + TIME_STOP, N)):
            hi, lo = rows[j][2], rows[j][3]
            if d == "BUY":
                if lo <= sl_px: exit_px, exit_i = sl_px, j; break     # SL ก่อน (conservative)
                if hi >= tp_px: exit_px, exit_i = tp_px, j; break
            else:
                if hi >= sl_px: exit_px, exit_i = sl_px, j; break
                if lo <= tp_px: exit_px, exit_i = tp_px, j; break
        if exit_px is None:
            exit_i = min(entry_i + TIME_STOP, N - 1); exit_px = rows[exit_i][4]
        gross_r = sign * (exit_px - entry) / risk   # spread คิดทีหลัง (fills บน mid → net = gross - spread/sl)
        trades.append({"i": i, "dir": d, "score": score, "sl": sl_pips, "tp": tp_pips,
                       "rr": tp_pips / sl_pips, "gross_r": gross_r, "hold": exit_i - entry_i})
        i = exit_i + 1        # no overlap
        if len(trades) % 50 == 0:
            print(f"  ... {len(trades)} ไม้ (bar {i}/{N})", file=sys.stderr)
    return trades, N


def sharpe(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std()) if len(x) > 1 and x.std() > 0 else 0.0


def boot_ci(x, B=3000):
    x = np.asarray(x, float); rng = np.random.default_rng(0)
    m = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(B)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def dsr(best_nets, all_sh, N):
    sr = sharpe(best_nets); T = len(best_nets); v = np.var(all_sh, ddof=1)
    if v <= 0 or T < 3:
        return None, sr, 0.0
    sr0 = np.sqrt(v) * ((1 - GAMMA) * stats.norm.ppf(1 - 1.0 / N) + GAMMA * stats.norm.ppf(1 - 1.0 / (N * np.e)))
    sk = float(stats.skew(best_nets)); ku = float(stats.kurtosis(best_nets, fisher=False))
    den = np.sqrt(1 - sk * sr + (ku - 1) / 4.0 * sr ** 2)
    z = (sr - sr0) * np.sqrt(T - 1) / den if den > 0 else 0.0
    return float(stats.norm.cdf(z)), sr, float(sr0)


def _net(trades, spread, thr=0):
    return np.array([t["gross_r"] - spread / t["sl"] for t in trades if t["score"] >= thr])


SPREADS = [0, 20, 30, 40, 50]


def report(trades, nbars):
    print("=" * 78)
    print(f"GOLD ENTRY SIM (real chart_watcher algo, 0-LLM) — {nbars} m15 bars ({nbars/96/365:.1f}y) "
          f"| intrabar fill")
    print("=" * 78)
    if not trades:
        print("ไม่มีไม้ (signal ไม่ยิงเลย?)"); return
    avg_rr = float(np.mean([t["rr"] for t in trades]))
    be_wr = 1.0 / (1.0 + avg_rr) * 100
    cut = 0.7 * nbars

    # ── LEVER 3: spread sweep (entries รันครั้งเดียว, spread = พจน์ cost) ──
    print(f"\n── spread sweep (n={len(trades)}, WR breakeven @ avgRR {avg_rr:.1f} = {be_wr:.0f}%) ──")
    print(f"  {'spread':>7} | {'WR':>4} | {'net R':>8} | {'avg/ไม้':>9} | {'Sharpe':>7} | "
          f"{'95% CI (mean net-R)':>22} | OOS")
    for sp in SPREADS:
        nets = _net(trades, sp)
        lo, hi = boot_ci(nets)
        oos = _net([t for t in trades if t["i"] >= cut], sp)
        oos_net = float(oos.sum()) if len(oos) else 0.0
        sig = "บวก✅" if lo > 0 else ("ลบ❌" if hi < 0 else "คร่อม0")
        print(f"  {sp:>4}pt  | {(nets>0).mean()*100:>3.0f}% | {nets.sum():>+8.1f} | "
              f"{nets.mean():>+9.4f} | {sharpe(nets):>+7.3f} | [{lo:>+.4f},{hi:>+.4f}] {sig:>6} | "
              f"{'+' if oos_net>0 else '-'}{abs(oos_net):.0f}R")

    # ── score-threshold sweep @ spread 30 (conf-gate analog) + DSR ──
    print(f"\n── score-threshold @ spread 30pt (conf-gate analog) + Deflated Sharpe ──")
    print(f"  {'thr':>4} | {'n':>4} | {'WR':>4} | {'net R':>8} | {'Sharpe':>7}")
    ths = [0, 57, 65, 68, 80]; sub_sh, sub = [], {}
    for th in ths:
        s = _net(trades, 30, th); sub[th] = s
        if len(s) >= 20:
            sub_sh.append(sharpe(s))
            print(f"  {th:>4} | {len(s):>4} | {(s>0).mean()*100:>3.0f}% | {s.sum():>+8.1f} | {sharpe(s):>+7.3f}")
        else:
            print(f"  {th:>4} | {len(s):>4} | (ไม้ไม่พอ)")
    if len(sub_sh) >= 2:
        best_th = max([th for th in ths if len(sub[th]) >= 20], key=lambda th: sharpe(sub[th]))
        d, sr, sr0 = dsr(sub[best_th], np.array(sub_sh), len(sub_sh))
        print(f"  best thr={best_th}: SR {sr:+.3f} vs SR0 {sr0:+.3f} → DSR {d:.3f}  "
              f"{'✅' if (d or 0) > 0.95 else '❌'}  ⚠️ nested subset → DSR optimistic")

    print("\n" + "=" * 78)
    n30 = _net(trades, 30); lo30, _ = boot_ci(n30)
    oos30 = _net([t for t in trades if t["i"] >= cut], 30)
    if lo30 > 0:
        print("VERDICT: structure algo (0-LLM) มี EV บวก significant @ 30pt ✅")
    elif n30.sum() > 0 and float(oos30.sum()) > 0:
        print("VERDICT: structure algo (0-LLM) net บวก + OOS ยืน แต่ CI คร่อม 0 = marginal ⚠️ (ต้อง data เพิ่ม)")
    else:
        print("VERDICT: structure algo (0-LLM) ไม่มี EV บวกที่พิสูจน์ได้ ❌")
    print("=" * 78)
    print(f"⚠️ = บอทลบ LLM/ข่าว/gate-conf. intrabar M15 fill. 1 ไม้/ครั้ง. RR avg {avg_rr:.1f} (TP=next S/R ≥2×SL).")


def main():
    print("โหลด data + precompute...", file=sys.stderr)
    m15 = load_tf("m15")
    caches = {tf: HTFCache(tf, load_tf(tf)) for tf in ("h4", "h1", "d1", "w1")}
    print("รัน sim (reuse chart_watcher จริง)...", file=sys.stderr)
    trades, nbars = run_sim(m15, caches)
    report(trades, nbars)


if __name__ == "__main__":
    main()
