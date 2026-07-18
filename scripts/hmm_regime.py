#!/usr/bin/env python
"""
hmm_regime.py — Gaussian HMM regime classifier บนทอง + VALIDATION เข้ม (OFFLINE)

กลั่นจาก AAT (Halls-Moore) HMM regime detection — แต่ **ต้อง validate ว่า regime มีความหมายจริง**
ไม่ใช่แค่ label สวย (วินัย session นี้). implement Gaussian HMM เอง (numpy+scipy, ไม่ต้อง hmmlearn).

feature (gold H1): [log-return, log realized-vol 24-bar] → z-score → fit K-state Gaussian HMM (Baum-Welch)
→ Viterbi decode → state sequence.

VALIDATION (regime จะใช้ได้ต่อเมื่อ):
  1) PERSISTENCE — avg duration >> 1 bar (ไม่ flip ทุกแท่ง; นี่คือจุดที่ HMM ชนะ GMM)
  2) DISTINCTNESS — แต่ละ state มี return/vol profile ต่างจริง
  3) FORWARD-PREDICTIVE — forward vol/return ต่างกันตาม state ปัจจุบัน (= มีประโยชน์จริง)
  4) OOS — fit บน 70% แรก → decode 30% หลัง → state ยังแยก vol ได้ (ไม่ overfit)

รัน: python scripts\\hmm_regime.py            (K=3, gold H1)
     python scripts\\hmm_regime.py 2 h4        (K states, timeframe)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from scipy.special import logsumexp
from sklearn.cluster import KMeans

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = int(sys.argv[1]) if len(sys.argv) > 1 else 3
TF = sys.argv[2] if len(sys.argv) > 2 else "h1"
VOL_W = 24
BARS_PER = {"h1": 24 * 252, "h4": 6 * 252, "d1": 252}.get(TF, 24 * 252)   # annualize factor


class GaussianHMM:
    """diagonal-covariance Gaussian HMM, Baum-Welch EM + Viterbi (log-space, stable)."""
    def __init__(self, K, n_iter=30, seed=0):
        self.K, self.n_iter, self.seed = K, n_iter, seed

    def _init(self, X):
        km = KMeans(self.K, n_init=5, random_state=self.seed).fit(X)
        self.mu = km.cluster_centers_.astype(float)
        self.var = np.array([X[km.labels_ == k].var(0) + 1e-3 for k in range(self.K)])
        self.logA = np.log(np.full((self.K, self.K), 1.0 / self.K))
        self.logpi = np.log(np.full(self.K, 1.0 / self.K))

    def _log_emit(self, X):
        le = np.zeros((len(X), self.K))
        for k in range(self.K):
            d = X - self.mu[k]
            le[:, k] = -0.5 * (np.sum(d * d / self.var[k], 1) + np.sum(np.log(2 * np.pi * self.var[k])))
        return le

    def fit(self, X):
        self._init(X); T = len(X)
        prev_ll = -np.inf
        for _ in range(self.n_iter):
            le = self._log_emit(X)
            la = np.zeros((T, self.K)); la[0] = self.logpi + le[0]
            for t in range(1, T):
                la[t] = le[t] + logsumexp(la[t - 1][:, None] + self.logA, axis=0)
            lb = np.zeros((T, self.K))
            for t in range(T - 2, -1, -1):
                lb[t] = logsumexp(self.logA + (le[t + 1] + lb[t + 1])[None, :], axis=1)
            ll = logsumexp(la[-1])
            g = np.exp(la + lb - ll)
            lxi = np.full((self.K, self.K), -np.inf)
            for t in range(T - 1):
                lxi = np.logaddexp(lxi, la[t][:, None] + self.logA + (le[t + 1] + lb[t + 1])[None, :] - ll)
            self.logpi = (la[0] + lb[0] - ll)
            self.logpi -= logsumexp(self.logpi)
            self.logA = lxi - logsumexp(lxi, axis=1, keepdims=True)
            for k in range(self.K):
                w = g[:, k]; sw = w.sum() + 1e-9
                self.mu[k] = (w[:, None] * X).sum(0) / sw
                d = X - self.mu[k]
                self.var[k] = (w[:, None] * d * d).sum(0) / sw + 1e-4
            if abs(ll - prev_ll) < 1e-3 * abs(prev_ll):
                break
            prev_ll = ll
        return self

    def decode(self, X):
        le = self._log_emit(X); T = len(X)
        d = np.zeros((T, self.K)); bp = np.zeros((T, self.K), int)
        d[0] = self.logpi + le[0]
        for t in range(1, T):
            m = d[t - 1][:, None] + self.logA
            bp[t] = np.argmax(m, 0); d[t] = le[t] + np.max(m, 0)
        s = np.zeros(T, int); s[-1] = int(np.argmax(d[-1]))
        for t in range(T - 2, -1, -1):
            s[t] = bp[t + 1][s[t + 1]]
        return s


def load_gold(tf):
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    return np.array([r[4] for r in rows], float)


def features(close):
    ret = np.diff(np.log(close))
    vol = np.array([ret[max(0, i - VOL_W):i].std() if i >= VOL_W else np.nan for i in range(len(ret))])
    m = ~np.isnan(vol) & (vol > 0)
    F = np.column_stack([ret[m], np.log(vol[m])])
    Fz = (F - F.mean(0)) / F.std(0)
    return Fz, ret[m], vol[m], np.where(m)[0]


def durations(s):
    d, cur, run = [], s[0], 1
    for x in s[1:]:
        if x == cur:
            run += 1
        else:
            d.append((cur, run)); cur, run = x, 1
    d.append((cur, run))
    return d


def main():
    print("=" * 76)
    print(f"HMM REGIME — gold {TF.upper()}, K={K} states | feature=[ret, log realized-vol {VOL_W}b]")
    print("=" * 76)
    close = load_gold(TF)
    Fz, ret, vol, idx = features(close)
    print(f"samples: {len(Fz)}  ({len(Fz)/BARS_PER:.1f} ปี)\n")

    hmm = GaussianHMM(K).fit(Fz)
    s = hmm.decode(Fz)

    # ── per-state profile ──
    print("── state profile ──")
    print(f"  {'state':>5} | {'freq':>5} | {'mean ret/bar':>12} | {'ann vol':>8} | {'avg duration':>12}")
    durs = durations(s)
    order = sorted(range(K), key=lambda k: vol[s == k].mean())   # เรียงตาม vol (calm→turbulent)
    for rank, k in enumerate(order):
        mask = s == k
        avg_dur = np.mean([r for st, r in durs if st == k]) if any(st == k for st, _ in durs) else 0
        ann_vol = vol[mask].mean() * np.sqrt(BARS_PER) * 100
        tag = ["CALM", "NORMAL", "TURBULENT", "S3", "S4"][rank] if K <= 5 else f"S{rank}"
        print(f"  {tag:>5} | {mask.mean()*100:4.0f}% | {ret[mask].mean()*1e4:+9.1f}bp | "
              f"{ann_vol:6.1f}% | {avg_dur:7.1f} bars")

    # ── VALIDATION ──
    print("\n── VALIDATION ──")
    # 1) persistence
    all_dur = np.mean([r for _, r in durs])
    print(f"  1) PERSISTENCE: avg duration {all_dur:.1f} bars → "
          f"{'✅ regime persist (HMM > GMM)' if all_dur >= 4 else '❌ flip เร็ว (ไม่ใช่ regime)'}")
    # 2) distinctness — spread ของ mean vol ระหว่าง state
    vols = [vol[s == k].mean() for k in range(K)]
    spread = max(vols) / min(vols) if min(vols) > 0 else 0
    print(f"  2) DISTINCTNESS: turbulent/calm vol ratio {spread:.1f}x → "
          f"{'✅ state ต่างจริง' if spread >= 1.5 else '❌ state คล้ายกัน'}")
    # 3) forward-predictive — forward 24-bar realized vol ต่างตาม state ปัจจุบันมั้ย
    fwd = min(24, len(ret) // 20)
    fvol_by = []
    for k in range(K):
        fv = [ret[i:i + fwd].std() for i in np.where(s == k)[0] if i + fwd < len(ret)]
        fvol_by.append(np.mean(fv) if fv else np.nan)
    fspread = np.nanmax(fvol_by) / np.nanmin(fvol_by) if np.nanmin(fvol_by) > 0 else 0
    print(f"  3) FORWARD-PREDICTIVE: forward-{fwd}b vol ratio {fspread:.1f}x → "
          f"{'✅ regeme ทำนาย vol ข้างหน้าได้ (ใช้ประโยชน์ได้)' if fspread >= 1.3 else '❌ ไม่ทำนาย forward (ไร้ประโยชน์)'}")
    # 4) OOS
    cut = int(0.7 * len(Fz))
    hmm2 = GaussianHMM(K).fit(Fz[:cut])
    s_oos = hmm2.decode(Fz)
    oos_vols = [vol[cut:][s_oos[cut:] == k].mean() for k in range(K) if (s_oos[cut:] == k).any()]
    oos_spread = (max(oos_vols) / min(oos_vols)) if oos_vols and min(oos_vols) > 0 else 0
    print(f"  4) OOS (fit 70% → decode 30% หลัง): vol ratio {oos_spread:.1f}x → "
          f"{'✅ แยกได้นอกกลุ่ม fit' if oos_spread >= 1.5 else '❌ พัง OOS'}")

    print("\n" + "=" * 76)
    ok = all_dur >= 4 and spread >= 1.5 and fspread >= 1.3 and oos_spread >= 1.5
    if ok:
        print("VERDICT: HMM regime มีความหมาย + ทำนาย forward vol ได้ + robust OOS ✅")
        print("         → ใช้เป็น regime classifier (ป้อน macro_regime/dashboard) ได้ — แต่ vol-regime เท่านั้น")
        print("         (ยังไม่ใช่ directional edge; เพิ่ม cross-asset feature = risk-on/off เต็มได้ทีหลัง)")
    else:
        print("VERDICT: HMM regime ยังไม่ผ่าน validation ครบ ⚠️ — ดู flag ด้านบนว่าตกข้อไหน")
    print("=" * 76)
    print("⚠️ vol-regime บน gold-only. risk-on/off เต็ม ต้องเพิ่ม DXY/VIX (มี data แล้ว). = context ไม่ใช่ edge.")


if __name__ == "__main__":
    main()
