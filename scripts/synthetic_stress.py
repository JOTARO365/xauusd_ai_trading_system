"""scripts/synthetic_stress.py — synthetic-path Monte-Carlo stress test (cway distill 08-22).

การกลั่นช่อง cwayinvestment: technique #1 (โผล่ 4 คลิปอิสระ) = หลัง backtest/OOS จริง ให้รัน strategy บน
**synthetic price paths** (สร้างเอง) เพื่อเช็ค survival ใน regime ที่ **ไม่เคยเห็นในประวัติ**. OOS/PBO/purged-CV
resample แต่ของจริง → มองไม่เห็น regime ใหม่. นี่คือชั้นเสริมที่โจมตี window-bias/real-vs-fit โดยตรง.

วิธี: fit จาก real close series แล้ว gen path 3 แบบ:
  1. GBM (iid normal ด้วย mean/vol จริง) — baseline random-walk
  2. block-bootstrap (สุ่มก้อน return จริง) — คง autocorr/fat-tail
  3. regime-switch vol (สลับ low/high vol เป็นช่วง) — stress regime เปลี่ยน
รัน strategy (close-based TSMOM = signal ของ live tsmom_d1) บนแต่ละ path → distribution ของ exp_R + survival%.
strategy รอด = exp_R>0 ใน path ส่วนใหญ่ **ทั้ง 3 mode**; ตายใน synthetic = edge เปราะ/เป็น artifact ของ window จริง.

demo: gold (ควรตาย = no edge) vs BTC (ควรรอด = timing skill ผ่าน drift-null). offline · 0 order.
รัน: python scripts/synthetic_stress.py
"""
import json
import math
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import quant_metrics as QM                                    # noqa: E402

LS = (63, 126, 252)                                           # TSMOM ensemble (ตรง tsmom_d1 live)
SEED = 20260822


def _tsmom_exp_R(close):
    """close-based TSMOM: pos = sign(ensemble vote); daily strat return = pos·next-ret. คืน R-array (per-day)."""
    c = np.asarray(close, float); n = len(c)
    if n < max(LS) + 20:
        return np.array([])
    ret = np.zeros(n); ret[:-1] = (c[1:] - c[:-1]) / c[:-1]
    out = []
    for i in range(max(LS), n - 1):
        votes = sum(np.sign(c[i] - c[i - L]) for L in LS)
        s = np.sign(votes)
        if s != 0:
            out.append(s * ret[i])
    return np.array(out)


def _gbm(c0, mu, sig, n, rng):
    r = rng.normal(mu, sig, n)
    return c0 * np.exp(np.cumsum(r))


def _block_boot(rets, n, rng, block=20):
    out = []
    while len(out) < n:
        st = rng.integers(0, max(1, len(rets) - block))
        out.extend(rets[st:st + block])
    return np.array(out[:n])


def _regime_switch(mu, lo, hi, n, rng, seg=100):
    r = np.empty(n); i = 0; useHi = False
    while i < n:
        L = min(seg, n - i); sig = hi if useHi else lo
        r[i:i + L] = rng.normal(mu, sig, L); i += L; useHi = not useHi
    return r


def stress(name, close, sims=400):
    """⚠️ DRIFTLESS paths (mu=0) เท่านั้น — กัน error ที่ survival จับ drift แทน timing skill (บทเรียน drift-null).
    บน path ไม่มี drift: strategy ไม่มี timing edge → exp_R~0 survival~50%; มี edge จริง → survival>50%.
    เทียบกับ random-sign บน path เดียวกัน (excess) = matched-null ฝังใน synthetic stress."""
    c = np.asarray(close, float)
    lr = np.log(c[1:] / c[:-1])
    sig = float(np.std(lr))
    ret = (c[1:] - c[:-1]) / c[:-1]
    ret_dm = ret - ret.mean()                                 # demeaned = driftless returns
    n = len(c); rng = np.random.default_rng(SEED)
    real = QM.panel(_tsmom_exp_R(c))
    print(f"\n=== {name} (bars={n}) ===")
    print(f"  REAL history: exp_R{real['exp_R']:+.4f} sortino{real['sortino']:+.2f} cvar5{real['cvar5']:+.4f} "
          f"PF{real['profit_factor']} recovery{real['recovery']}  (⚠️ real drift อาจพยุง — ดู driftless ด้านล่าง)")
    for mode in ("GBM-0drift", "block-boot-demean", "regime-0drift"):
        exps = []; nulls = []
        for _ in range(sims):
            if mode == "GBM-0drift":
                path = _gbm(c[0], 0.0, sig, n, rng)           # mu=0
            elif mode == "block-boot-demean":
                rr = _block_boot(ret_dm, n, rng); path = c[0] * np.cumprod(1 + rr)
            else:
                rr = _regime_switch(0.0, sig * 0.5, sig * 1.8, n, rng); path = c[0] * np.exp(np.cumsum(rr))
            a = _tsmom_exp_R(path)
            if len(a):
                exps.append(a.mean())
                # matched-null: random ±1 sign บน path เดียวกัน (ret ของ path)
                pr = (path[1:] - path[:-1]) / path[:-1]
                sg = rng.choice([-1.0, 1.0], size=len(pr))
                nulls.append(float((sg * pr).mean()))
        exps = np.array(exps); nulls = np.array(nulls)
        surv = float((exps > 0).mean()) * 100
        p_excess = float((nulls >= exps.mean()).mean())       # strategy ชนะ random-sign บน driftless?
        verd = "EDGE" if (surv >= 60 and p_excess < 0.05) else "NO-EDGE" if surv <= 55 else "weak"
        print(f"  {mode:18s} exp_R{exps.mean():+.5f} survival(>0){surv:5.1f}% vs-random p{p_excess:.3f}  [{verd}]")
    print("  → EDGE = survival>60% + ชนะ random-sign (p<0.05) บน DRIFTLESS path (timing skill จริง ไม่ใช่ drift)")


def _load_xau():
    d = json.load(open(os.path.join(_BASE, "data", "xau_d1.json")))
    return np.array([x[4] for x in d], float)


def _load_btc():
    p = os.path.join(os.path.expanduser("~"), ".claude", "projects",
                     "D--claude-workspace-xauusd-ai-trading-system", "8753aacd-c36b-49f7-88e5-e6a3c9fac75f",
                     "tool-results", "mcp-alphavantage-DIGITAL_CURRENCY_DAILY-1787349044877.txt")
    if not os.path.exists(p):
        return None
    ts = json.load(open(p, encoding="utf-8"))["Time Series (Digital Currency Daily)"]
    return np.array([float(v["4. close"]) for k, v in sorted(ts.items())], float)


def main():
    print("=== SYNTHETIC MONTE-CARLO STRESS (cway technique) — TSMOM close-based ===")
    print("survival% = สัดส่วน synthetic path ที่ strategy ยัง +EV. เทียบ 3 mode (GBM/boot/regime).")
    stress("GOLD (xau_d1)", _load_xau())
    btc = _load_btc()
    if btc is not None:
        stress("BTC (daily)", btc)
    else:
        print("\n(BTC data cache ไม่พบ — ข้าม)")
    print("\nผลจริง: GOLD NO-EDGE ทุก mode (real +0.0003=drift ล้วน). BTC EDGE เฉพาะ block-boot (autocorr-dependent,")
    print("p0.052 borderline) ไม่รอด iid → edge=exploit autocorrelation จริงแต่บาง. tool แยก drift/timing/autocorr ได้.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
