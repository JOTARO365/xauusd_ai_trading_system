#!/usr/bin/env python
"""
gold_sim_nulltest.py — SYNTHETIC NULL test ของ gold_entry_sim (empirical overfitting/harness check)

ไอเดีย (จากบทความ synthetic data — ใช้ถูกทาง = "เกมรับ"): สร้าง gold ปลอมที่ **ไม่มี edge โดยตั้งใจ**
(block-bootstrap สลับบล็อกของ bar จริง → ทำลาย S/R + trend + multi-bar structure ที่กลยุทธ์เกาะ
แต่เก็บ return distribution + fat-tail + per-bar OHLC geometry ไว้) แล้วรัน **sim ตัวจริง** บนมันหลายชุด.
ถ้า net-R null กระจุกที่ ~0 → harness สะอาด → +0.030R/ไม้ บน data จริง = signal จริง (อ่อนๆ).
ถ้า null เลื่อนบวก → **harness bias** (กลยุทธ์ทำเงินจาก noise = เจอ artifact ก่อน deploy).

reuse โค้ด sim จริง 100% (run_sim/decide/HTFCache จาก gold_entry_sim) — ป้อน data สังเคราะห์ใน memory.
consistent หลาย TF: สร้าง m15 ปลอม → aggregate เป็น h1/h4/d1/w1 (o=first,h=max,l=min,c=last).

config ผ่าน env (กัน argv ชนตอน import gold_entry_sim): NN=จำนวนชุด, LL=ความยาว m15, BB=block size.
รัน: NN=10 LL=100000 BB=16 & $PY scripts\\gold_sim_nulltest.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "scripts"))

import gold_entry_sim as G   # reuse: load_tf, run_sim, HTFCache, TF_SEC, POINT

NN = int(os.environ.get("NN", "10"))
LL = int(os.environ.get("LL", "100000"))
BB = int(os.environ.get("BB", "16"))
SPREAD = 30.0
# ค่าจริงจาก sim บน data จริง (100k m15, 4.2y) @30pt — เทียบกับ null
REAL_AVG_PER_TRADE = 0.0297
REAL_TOTAL = 40.6
REAL_N = 1368

_AGG = {"h1": 4, "h4": 16, "d1": 96, "w1": 480}


def _wrap(rows, tf):
    dicts = [{"time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "tick_volume": r[5]}
             for r in rows]
    close_t = [r[0] + G.TF_SEC[tf] for r in rows]
    return {"rows": rows, "dicts": dicts, "close_t": close_t}


def synth_m15(real_rows, L, block, rng):
    """block-bootstrap: เก็บ per-bar OHLC geometry (factor เทียบ prev close) + return dist, สลับ order."""
    rc = np.array([r[4] for r in real_rows], float)
    prevc = np.concatenate([[rc[0]], rc[:-1]])
    fo = np.array([r[1] for r in real_rows]) / prevc
    fh = np.array([r[2] for r in real_rows]) / prevc
    fl = np.array([r[3] for r in real_rows]) / prevc
    fc = rc / prevc
    vol = [r[5] for r in real_rows]
    n = len(real_rows)
    idx = []
    while len(idx) < L:
        s = int(rng.integers(0, n - block))
        idx.extend(range(s, s + block))
    idx = idx[:L]
    base = real_rows[0][0]
    P = rc[0]
    out = []
    for k, j in enumerate(idx):
        o = P * fo[j]; h = P * fh[j]; l = P * fl[j]; c = P * fc[j]
        out.append([base + k * 900, o, h, l, c, vol[j]])
        P = c
    return out


def aggregate(m15_rows, k):
    out = []
    for i in range(0, len(m15_rows) - k + 1, k):
        ch = m15_rows[i:i + k]
        out.append([ch[0][0], ch[0][1], max(x[2] for x in ch),
                    min(x[3] for x in ch), ch[-1][4], sum(x[5] for x in ch)])
    return out


def one_null_run(real_m15_rows, L, block, seed):
    rng = np.random.default_rng(seed)
    m15r = synth_m15(real_m15_rows, L, block, rng)
    m15 = _wrap(m15r, "m15")
    caches = {tf: G.HTFCache(tf, _wrap(aggregate(m15r, _AGG[tf]), tf)) for tf in ("h4", "h1", "d1", "w1")}
    trades, nbars = G.run_sim(m15, caches)
    if not trades:
        return None
    gross = np.array([t["gross_r"] for t in trades])
    sl = np.array([t["sl"] for t in trades])
    net = gross - SPREAD / sl
    return {"n": len(trades), "avg": float(net.mean()), "total": float(net.sum())}


def main():
    print("=" * 72)
    print(f"GOLD SIM NULL-TEST — block-bootstrap (block={BB} m15), N={NN} ชุด, L={LL} bars/ชุด @{SPREAD}pt")
    print("=" * 72)
    real = G.load_tf("m15")
    print(f"real m15: {len(real['rows'])} bars → สร้าง null {NN} ชุด (สลับบล็อก ทำลาย structure)\n", file=sys.stderr)
    res = []
    for s in range(NN):
        r = one_null_run(real["rows"], LL, BB, seed=s)
        if r:
            res.append(r)
            print(f"  null #{s:>2}: n={r['n']:>4}  avg {r['avg']:+.4f}R/ไม้  total {r['total']:+.1f}R", flush=True)
    if not res:
        print("ไม่มีผล null"); return
    avgs = np.array([r["avg"] for r in res])
    print(f"\n── null distribution ของ avg net-R/ไม้ ({len(res)} ชุด) @{SPREAD}pt ──")
    print(f"  mean {avgs.mean():+.4f} | std {avgs.std():+.4f} | "
          f"min {avgs.min():+.4f} | max {avgs.max():+.4f}")
    # p-value: null ที่ >= real
    p = float((avgs >= REAL_AVG_PER_TRADE).mean())
    z = (REAL_AVG_PER_TRADE - avgs.mean()) / avgs.std() if avgs.std() > 0 else 0
    print(f"\n── เทียบ REAL (data จริง 4.2y): avg {REAL_AVG_PER_TRADE:+.4f}R/ไม้ (total {REAL_TOTAL:+.1f}R, n={REAL_N}) ──")
    print(f"  null mean {avgs.mean():+.4f}  |  real z-score เทียบ null = {z:+.2f}")
    print(f"  p(null ≥ real) = {p:.2f}  →  ", end="")
    if avgs.mean() > REAL_AVG_PER_TRADE * 0.5:
        print("❌ null เลื่อนบวกใกล้ real = **HARNESS BIAS** (กลยุทธ์ทำเงินจาก noise ด้วย)")
    elif p <= 0.10:
        print("✅ real อยู่นอก null (z สูง) = harness สะอาด, +0.030R เป็น signal จริง (อ่อนๆ)")
    else:
        print("⚠️ real อยู่ในกลุ่ม null = แยกจาก noise ไม่ได้ (สอดคล้อง CI คร่อม 0)")
    print("\n" + "=" * 72)
    print("⚠️ block-bootstrap ทำลาย S/R+trend เก็บ distribution+per-bar geometry. reuse sim จริง 100%.")
    print("   นี่คือ synthetic ใช้ถูกทาง = null/overfitting check (เกมรับ) — ไม่ใช่หา edge.")


if __name__ == "__main__":
    main()
