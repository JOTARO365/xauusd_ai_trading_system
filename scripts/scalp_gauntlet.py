#!/usr/bin/env python
"""scalp_gauntlet.py — validate scalping candidates (persona designs) บน XAUUSD M15 ด้วย gauntlet เดียวที่เชื่อถือได้.

บทเรียน a1: อย่าให้แต่ละ design มี harness ของมันเอง (fill-bar look-ahead bug). อันนี้คือ harness กลาง:
  - intrabar fill pessimistic: scan exit จาก fi+1 (ไม่นับบาร์ entry = ไม่รู้ H/L order), SL ก่อน TP ตอน ambiguous
  - net-of-cost: หัก spread 31p ทุกไม้ (cost_R = cost_pips / sl_pips)
  - gauntlet: full WR/expR/PSR + OOS 40% + quartile consistency + NULL (random-time entry, sl/tp ระยะเดิม)
รัน: & $PY scripts\scalp_gauntlet.py
batch 1: Asian Sweep Reclaim (quant) + London IB Break (quant).
"""
import datetime as dt
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

POINT = R.POINT
COST = 31              # spread floor (points) หักทุกไม้
MIN_N = 100
MAXHOLD_DEF = 8


def _load(fn):
    return np.array(json.load(open(os.path.join(_BASE, "data", fn))), dtype=float)


def sim(fi, entry, direction, sl, tp, h, l, c, maxhold):
    """intrabar pessimistic, exit จาก fi+1. คืน (R_gross, hold, why) หรือ None."""
    sign = 1.0 if direction == "BUY" else -1.0
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    end = min(fi + maxhold, len(c) - 1)
    for j in range(fi + 1, end + 1):
        hit_sl = l[j] <= sl if direction == "BUY" else h[j] >= sl
        hit_tp = h[j] >= tp if direction == "BUY" else l[j] <= tp
        if hit_sl and hit_tp:
            return -1.0, j - fi, "SL_TP"                 # pessimistic
        if hit_sl:
            return -1.0, j - fi, "SL"
        if hit_tp:
            return round(abs(tp - entry) / risk, 3), j - fi, "TP"
    return round(sign * (c[end] - entry) / risk, 3), end - fi, "TIME"


def net_R(t):
    """gross R → net หลังหัก spread (cost_pips / sl_pips ในหน่วย R)."""
    return t["R_gross"] - COST / t["sl_pips"]


def _agg(trades):
    if len(trades) < 1:
        return None
    r = np.array([net_R(t) for t in trades])
    n = len(r)
    wr = float((r > 0).mean())
    exp = float(r.mean())
    sd = float(r.std()) or 1e-9
    sharpe = exp / sd * np.sqrt(n)
    return {"n": n, "wr": wr, "exp": exp, "sharpe": sharpe,
            "psr": BT.psr_zero(r) if n >= 30 else float("nan"), "sumR": float(r.sum())}


def null_test(trades, close, seed=1):
    """re-anchored null: entry ที่เวลาสุ่ม, ทิศ + sl_pips + RR เดิม, sl/tp ที่ระยะ pip เดิม."""
    rng = np.random.RandomState(seed)
    n = len(close)
    out = []
    for t in trades:
        ei = int(rng.randint(50, n - t.get("maxhold", MAXHOLD_DEF) - 1))
        ent = close[ei]
        sign = 1.0 if t["dir"] == "BUY" else -1.0
        sl = ent - sign * t["sl_pips"] * POINT
        tp = ent + sign * t["tp_pips"] * POINT
        r = sim(ei, ent, t["dir"], sl, tp, H, L, C, t.get("maxhold", MAXHOLD_DEF))
        if r:
            out.append({"i": ei, "dir": t["dir"], "sl_pips": t["sl_pips"], "tp_pips": t["tp_pips"],
                        "R_gross": r[0]})
    return out


def gauntlet(name, trades):
    print("\n" + "=" * 92)
    print(f"{name}  |  N={len(trades)}  cost={COST}p")
    print("=" * 92)
    if len(trades) < MIN_N:
        print(f"  N={len(trades)} < {MIN_N} — ไม่พอสรุป (SKIP)")
        return
    s = _agg(trades)
    idx = np.array([t["i"] for t in trades])
    split = np.percentile(idx, 60)
    oos = [t for t in trades if t["i"] >= split]
    so = _agg(oos)
    # quartile by entry index
    qs = []
    lo, hi = idx.min(), idx.max()
    for q in range(4):
        a = lo + (hi - lo) * q / 4
        b = lo + (hi - lo) * (q + 1) / 4
        seg = [t for t in trades if a <= t["i"] < b]
        qs.append(_agg(seg)["exp"] if len(seg) >= 25 else float("nan"))
    ns = _agg(null_test(trades, C))
    print(f"  full : WR {s['wr']*100:5.1f}%  expR {s['exp']:+.3f}  Sharpe {s['sharpe']:+.2f}  "
          f"PSR {s['psr']:.2f}  sumR {s['sumR']:+.1f}")
    print(f"  OOS40: WR {so['wr']*100:5.1f}%  expR {so['exp']:+.3f}  (N={so['n']})")
    print(f"  null : WR {ns['wr']*100:5.1f}%  expR {ns['exp']:+.3f}  (random-time เทียบ)")
    print(f"  quartile expR: " + " ".join(f"Q{i+1}:{v:+.3f}" for i, v in enumerate(qs)))
    q4 = qs[3]
    gates = {
        "expR>0": s["exp"] > 0,
        "PSR>0.95": s["psr"] >= 0.95,
        "OOS>0": so["exp"] > 0,
        "beat-null": s["exp"] > ns["exp"] + 0.02,
        "Q4>0": q4 == q4 and q4 > 0,
        "all-Q>0": all(v == v and v > 0 for v in qs),
    }
    ok = all(gates.values())
    print(f"  VERDICT: {'✅ PASS' if ok else '❌ FAIL'} — " +
          " ".join(f"{k}:{'✓' if v else '✗'}" for k, v in gates.items()))


# ── data ─────────────────────────────────────────────────────────────────────
M = _load("xau_m15.json")
T, O, H, L, C = M[:, 0], M[:, 1], M[:, 2], M[:, 3], M[:, 4]
N = len(C)
HOUR = np.array([dt.datetime.utcfromtimestamp(x).hour for x in T])
DAY = np.array([dt.datetime.utcfromtimestamp(x).toordinal() for x in T])
ATR_M15 = R.atr(H, L, C)
# ATR_H1 aligned (last CLOSED h1 bar, ไม่ look-ahead)
H1 = _load("xau_h1.json")
ATR_H1_S = R.atr(H1[:, 2], H1[:, 3], H1[:, 4])
_h1idx = np.searchsorted(H1[:, 0], T - 3600, side="right") - 1
_h1idx = np.clip(_h1idx, 0, len(ATR_H1_S) - 1)
ATR_H1 = ATR_H1_S[_h1idx]


def _day_range(hlo, hhi):
    """คืน dict day-ordinal → (rng_high, rng_low) จากบาร์ที่ hour ∈ [hlo,hhi)."""
    rng = {}
    for i in range(N):
        if hlo <= HOUR[i] < hhi:
            d = DAY[i]
            if d not in rng:
                rng[d] = [H[i], L[i]]
            else:
                rng[d][0] = max(rng[d][0], H[i])
                rng[d][1] = min(rng[d][1], L[i])
    return rng


def strat_asian_sweep():
    """Quant-A: sweep นอก Asian range (00-06 UTC) แล้ว reclaim กลับเข้า → fade. entry window 06-10 UTC."""
    asian = _day_range(0, 6)
    trades = []
    done = {}                                            # (day, side) → traded แล้ว
    for i in range(1, N):
        if not (6 <= HOUR[i] < 10):
            continue
        d = DAY[i]
        if d not in asian:
            continue
        AH, AL = asian[d]
        a = ATR_M15[i]
        if not (a > 0):
            continue
        w = AH - AL
        if not (0.4 * ATR_H1[i] <= w <= 1.2 * ATR_H1[i]):   # compressed balance เท่านั้น
            continue
        # upside sweep at i-1 + reclaim close at i
        if H[i - 1] > AH + 0.10 * a and C[i] < AH - 0.10 * a and (d, "S") not in done:
            ent = C[i]; sl = H[i - 1] + 0.15 * a
            slp = round((sl - ent) / POINT)
            if 1 <= slp <= 1500:
                tp = ent - 1.5 * (sl - ent)
                r = sim(i, ent, "SELL", sl, tp, H, L, C, 8)
                if r:
                    done[(d, "S")] = 1
                    trades.append({"i": i, "dir": "SELL", "sl_pips": slp, "tp_pips": round(1.5 * slp),
                                   "R_gross": r[0], "maxhold": 8})
        if L[i - 1] < AL - 0.10 * a and C[i] > AL + 0.10 * a and (d, "L") not in done:
            ent = C[i]; sl = L[i - 1] - 0.15 * a
            slp = round((ent - sl) / POINT)
            if 1 <= slp <= 1500:
                tp = ent + 1.5 * (ent - sl)
                r = sim(i, ent, "BUY", sl, tp, H, L, C, 8)
                if r:
                    done[(d, "L")] = 1
                    trades.append({"i": i, "dir": "BUY", "sl_pips": slp, "tp_pips": round(1.5 * slp),
                                   "R_gross": r[0], "maxhold": 8})
    return trades


def strat_london_ib():
    """Quant-B: break compressed initial-balance (07-08 UTC) → follow-through. entry window 08-11 UTC, first break."""
    ib = _day_range(7, 8)
    trades = []
    done = {}
    for i in range(1, N):
        if not (8 <= HOUR[i] < 11):
            continue
        d = DAY[i]
        if d not in ib or d in done:
            continue
        IBH, IBL = ib[d]
        a = ATR_M15[i]
        w = IBH - IBL
        if not (a > 0) or w <= 0:
            continue
        if w > 0.8 * ATR_H1[i]:                          # compressed IB เท่านั้น
            continue
        mid = (IBH + IBL) / 2
        if C[i] > IBH + 0.15 * a:                        # break up → long, SL = IB mid
            ent = C[i]; sl = mid; slp = round((ent - sl) / POINT)
            if 1 <= slp <= 1500:
                tp = ent + 1.5 * (ent - sl)
                r = sim(i, ent, "BUY", sl, tp, H, L, C, 12)
                if r:
                    done[d] = 1
                    trades.append({"i": i, "dir": "BUY", "sl_pips": slp, "tp_pips": round(1.5 * slp),
                                   "R_gross": r[0], "maxhold": 12})
        elif C[i] < IBL - 0.15 * a:
            ent = C[i]; sl = mid; slp = round((sl - ent) / POINT)
            if 1 <= slp <= 1500:
                tp = ent - 1.5 * (sl - ent)
                r = sim(i, ent, "SELL", sl, tp, H, L, C, 12)
                if r:
                    done[d] = 1
                    trades.append({"i": i, "dir": "SELL", "sl_pips": slp, "tp_pips": round(1.5 * slp),
                                   "R_gross": r[0], "maxhold": 12})
    return trades


# ── reversion family (math persona) — helpers ───────────────────────────────
def _ema(x, span):
    a = 2.0 / (span + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _roll_std(x, w):
    c1 = np.cumsum(np.insert(x, 0, 0.0)); c2 = np.cumsum(np.insert(x * x, 0, 0.0))
    s1 = c1[w:] - c1[:-w]; s2 = c2[w:] - c2[:-w]
    mean = s1 / w; var = np.maximum(s2 / w - mean * mean, 1e-12)
    out = np.full(len(x), np.nan); out[w - 1:] = np.sqrt(var)
    return out


def _lag1(seg):
    a, b = seg[1:], seg[:-1]
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _vr(seg, q):
    d1 = np.diff(seg); dq = seg[q:] - seg[:-q]
    v1 = d1.var()
    return 1.0 if v1 < 1e-12 else float(dq.var() / (q * v1))


TYP = (H + L + C) / 3.0
ADX_H1_S = R.adx(H1[:, 2], H1[:, 3], H1[:, 4])
ADX_H1 = ADX_H1_S[np.clip(_h1idx, 0, len(ADX_H1_S) - 1)]


def strat_ou_reversion():
    """Math-A: fade z=2 ของ s=P−EMA(32) เฉพาะเมื่อ OU mean-reversion วัดได้ตอนนี้ (φ∈[0.6,0.985] + VR8<0.85)."""
    m = _ema(C, 32); s = C - m
    sig = _roll_std(s, 200); z = np.where(sig > 0, s / sig, 0.0)
    med_atr = np.full(N, np.nan); med_atr[500:] = np.array(
        [np.median(ATR_M15[i - 500:i]) for i in range(500, N)])          # 500-bar median ATR (vol band)
    trades = []; last = -10 ** 9
    for i in range(200, N):
        if abs(z[i]) < 2.0 or i - last < 4:
            continue
        a = ATR_M15[i]
        if not (a > 0) or med_atr[i] != med_atr[i] or not (0.5 * med_atr[i] <= a <= 2.0 * med_atr[i]):
            continue
        seg = s[i - 200:i]
        phi = _lag1(seg)
        if not (0.60 <= phi <= 0.985):                   # OU validity guard
            continue
        if _vr(seg, 8) >= 0.85:                          # anti-persistence guard
            continue
        if abs(C[i] - C[i - 1]) > 1.5 * sig[i]:          # จุด jump-driven → ข้าม
            continue
        d = "BUY" if z[i] <= -2.0 else "SELL"
        sign = 1.0 if d == "BUY" else -1.0
        sld = min(max(0.9 * sig[i], 400 * POINT), 800 * POINT)
        slp = round(sld / POINT)
        sl = C[i] - sign * sld; tp = C[i] + sign * 1.5 * sld
        r = sim(i, C[i], d, sl, tp, H, L, C, 12)
        if r:
            last = i
            trades.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": round(1.5 * slp),
                           "R_gross": r[0], "maxhold": 12})
    return trades


def strat_session_vwap():
    """Math-B: fade z=1.8 กลับ session-anchor (cumulative TWAP) เฉพาะ balanced session (VR<1 หลาย scale + ADX_H1<22)."""
    A = np.zeros(N); Aop = np.zeros(N)
    cur = None; ssum = 0.0; scnt = 0; aop = 0.0
    for i in range(N):
        if DAY[i] != cur:
            cur = DAY[i]; ssum = 0.0; scnt = 0; aop = TYP[i]
        ssum += TYP[i]; scnt += 1
        A[i] = ssum / scnt; Aop[i] = aop
    s = C - A; sig = _roll_std(s, 96); z = np.where(sig > 0, s / sig, 0.0)
    trades = []; last = -10 ** 9
    for i in range(96, N):
        if not (7 <= HOUR[i] < 20) or abs(z[i]) < 1.8 or i - last < 4:
            continue
        sg = sig[i]
        if not (300 * POINT <= sg <= 900 * POINT):
            continue
        if abs(A[i] - Aop[i]) / sg >= 1.0:               # anchor trending → ไม่ balance
            continue
        if ADX_H1[i] >= 22:                              # HTF trend → skip
            continue
        seg = s[i - 96:i]
        if not (_vr(seg, 4) < 0.9 and _vr(seg, 8) < 0.85 and _vr(seg, 16) < 0.9):
            continue
        d = "BUY" if z[i] <= -1.8 else "SELL"
        sign = 1.0 if d == "BUY" else -1.0
        sld = min(max(0.8 * sg, 350 * POINT), 700 * POINT)
        slp = round(sld / POINT)
        sl = C[i] - sign * sld; tp = C[i] + sign * 1.6 * sld
        r = sim(i, C[i], d, sl, tp, H, L, C, 16)
        if r:
            last = i
            trades.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": round(1.6 * slp),
                           "R_gross": r[0], "maxhold": 16})
    return trades


def strat_donchian_volgate():
    """ML-B proxy: Donchian(20) breakout gated by vol-expansion (ATR≥480-bar median) — ทดสอบ thesis HMM
    โดยไม่ต้อง fit HMM. ถ้า gate นี้ไม่ทำให้ breakout เป็นบวก → HMM เต็มก็ไม่ช่วย (overfit เปล่าๆ)."""
    don_hi = np.full(N, np.nan); don_lo = np.full(N, np.nan)
    for i in range(20, N):
        don_hi[i] = H[i - 20:i].max(); don_lo[i] = L[i - 20:i].min()
    trades = []; last = -10 ** 9
    for i in range(500, N):
        if i - last < 6:
            continue
        a = ATR_M15[i]
        if not (a > 0) or a < np.median(ATR_M15[i - 480:i]):    # vol-expansion gate (HMM proxy)
            continue
        sld = min(max(0.8 * a, 400 * POINT), 800 * POINT); slp = round(sld / POINT)
        if C[i] > don_hi[i]:                             # break up → long
            sl = C[i] - sld; tp = C[i] + 1.5 * sld
            r = sim(i, C[i], "BUY", sl, tp, H, L, C, 6)
            d = "BUY"
        elif C[i] < don_lo[i]:
            sl = C[i] + sld; tp = C[i] - 1.5 * sld
            r = sim(i, C[i], "SELL", sl, tp, H, L, C, 6)
            d = "SELL"
        else:
            continue
        if r:
            last = i
            trades.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": round(1.5 * slp),
                           "R_gross": r[0], "maxhold": 6})
    return trades


if __name__ == "__main__":
    print(f"XAUUSD M15 gauntlet | {N} bars {(T[-1]-T[0])/86400/365:.1f}y | POINT={POINT} cost={COST}p")
    gauntlet("Quant-A · Asian Sweep Reclaim", strat_asian_sweep())
    gauntlet("Quant-B · London IB Break", strat_london_ib())
    gauntlet("Math-A · OU-HalfLife Z-Reversion", strat_ou_reversion())
    gauntlet("Math-B · Session-VWAP OU Reversion", strat_session_vwap())
    gauntlet("ML-B proxy · Donchian breakout + vol-gate", strat_donchian_volgate())
