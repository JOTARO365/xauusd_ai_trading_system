#!/usr/bin/env python
"""
hmm_risk_regime.py — CROSS-ASSET risk-on/off HMM (gold + VIX + DXY, daily) + validation (OFFLINE)

ต่อจาก hmm_regime.py (gold-only vol-regime) → เพิ่ม cross-asset feature เป็น **risk-on/off เต็ม**
ตาม deep research (VIX/DXY = risk regime switch). data: Yahoo daily (GC=F/^VIX/DX-Y.NYB) แหล่งเดียว
= aligned ไม่มี timezone issue, 15 ปี.

feature/วัน: [gold_ret, log(gold_vol 20d), log(VIX), dxy_ret] → z-score → Gaussian HMM K states.
interpret: เรียง state ตาม VIX (RISK-ON=VIX ต่ำ → RISK-OFF=VIX สูง) + ดูว่าทองทำตัวยังไงในแต่ละ regime.

VALIDATION (เหมือน hmm_regime): persistence / distinctness / forward-predictive / OOS.
⚠️ = risk CONTEXT (sizing/gating) ไม่ใช่ directional entry edge. vol/regime ทำนายได้ direction ไม่ได้.

รัน: python scripts\\hmm_risk_regime.py            (K=3)
     python scripts\\hmm_risk_regime.py 4
"""
import datetime as _dt
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from scipy.special import logsumexp
from sklearn.cluster import KMeans

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CACHE = os.path.join(_BASE, "data", "risk_daily.json")
VOL_W = 20
YR = 252


class GaussianHMM:
    def __init__(self, K, n_iter=60, seed=0):
        self.K, self.n_iter, self.seed = K, n_iter, seed

    def _init(self, X):
        km = KMeans(self.K, n_init=5, random_state=self.seed).fit(X)
        self.mu = km.cluster_centers_.astype(float)
        self.var = np.array([X[km.labels_ == k].var(0) + 1e-3 for k in range(self.K)])
        self.logA = np.log(np.full((self.K, self.K), 1.0 / self.K))
        self.logpi = np.log(np.full(self.K, 1.0 / self.K))

    def _le(self, X):
        le = np.zeros((len(X), self.K))
        for k in range(self.K):
            d = X - self.mu[k]
            le[:, k] = -0.5 * (np.sum(d * d / self.var[k], 1) + np.sum(np.log(2 * np.pi * self.var[k])))
        return le

    def fit(self, X):
        self._init(X); T = len(X); prev = -np.inf
        for _ in range(self.n_iter):
            le = self._le(X)
            la = np.zeros((T, self.K)); la[0] = self.logpi + le[0]
            for t in range(1, T):
                la[t] = le[t] + logsumexp(la[t - 1][:, None] + self.logA, axis=0)
            lb = np.zeros((T, self.K))
            for t in range(T - 2, -1, -1):
                lb[t] = logsumexp(self.logA + (le[t + 1] + lb[t + 1])[None, :], axis=1)
            ll = logsumexp(la[-1]); g = np.exp(la + lb - ll)
            lxi = np.full((self.K, self.K), -np.inf)
            for t in range(T - 1):
                lxi = np.logaddexp(lxi, la[t][:, None] + self.logA + (le[t + 1] + lb[t + 1])[None, :] - ll)
            self.logpi = (la[0] + lb[0] - ll); self.logpi -= logsumexp(self.logpi)
            self.logA = lxi - logsumexp(lxi, axis=1, keepdims=True)
            for k in range(self.K):
                w = g[:, k]; sw = w.sum() + 1e-9
                self.mu[k] = (w[:, None] * X).sum(0) / sw
                d = X - self.mu[k]; self.var[k] = (w[:, None] * d * d).sum(0) / sw + 1e-4
            if abs(ll - prev) < 1e-3 * abs(prev):
                break
            prev = ll
        return self

    def decode(self, X):
        le = self._le(X); T = len(X)
        d = np.zeros((T, self.K)); bp = np.zeros((T, self.K), int); d[0] = self.logpi + le[0]
        for t in range(1, T):
            m = d[t - 1][:, None] + self.logA; bp[t] = np.argmax(m, 0); d[t] = le[t] + np.max(m, 0)
        s = np.zeros(T, int); s[-1] = int(np.argmax(d[-1]))
        for t in range(T - 2, -1, -1):
            s[t] = bp[t + 1][s[t + 1]]
        return s


def _yahoo(sym, rng="15y"):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range={rng}"
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    ts = res["timestamp"]; cl = res["indicators"]["quote"][0]["close"]
    # key ด้วย "วันที่" (instrument เปิดคนละเวลา → timestamp ต่างกัน แต่วันเดียวกัน align ได้)
    return {_dt.date.fromtimestamp(t).isoformat(): c for t, c in zip(ts, cl) if c is not None}


def load_data():
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    print("fetching gold/VIX/DXY daily จาก Yahoo...", file=sys.stderr)
    g = _yahoo("GC=F"); v = _yahoo("%5EVIX"); x = _yahoo("DX-Y.NYB")
    days = {d: {"gold": g[d], "vix": v[d], "dxy": x[d]} for d in sorted(set(g) & set(v) & set(x))}
    json.dump(days, open(CACHE, "w"))
    return days


def durations(s):
    d, cur, run = [], s[0], 1
    for x in s[1:]:
        if x == cur: run += 1
        else: d.append((cur, run)); cur, run = x, 1
    d.append((cur, run)); return d


def main():
    print("=" * 78)
    print(f"CROSS-ASSET RISK-ON/OFF HMM — gold+VIX+DXY daily, K={K} | Yahoo 15y")
    print("=" * 78)
    days = load_data()
    dates = sorted(days)
    gold = np.array([days[d]["gold"] for d in dates])
    vix = np.array([days[d]["vix"] for d in dates])
    dxy = np.array([days[d]["dxy"] for d in dates])
    gret = np.diff(np.log(gold)); dret = np.diff(np.log(dxy))
    gvol = np.array([gret[max(0, i - VOL_W):i].std() if i >= VOL_W else np.nan for i in range(len(gret))])
    vixL = vix[1:]  # align to ret
    m = ~np.isnan(gvol) & (gvol > 0)
    F = np.column_stack([gret[m], np.log(gvol[m]), np.log(vixL[m]), dret[m]])
    Fz = (F - F.mean(0)) / F.std(0)
    print(f"samples: {len(Fz)} วัน ({len(Fz)/YR:.1f} ปี)\n")

    hmm = GaussianHMM(K).fit(Fz); s = hmm.decode(Fz)
    gr = gret[m]; gv = gvol[m]; vx = vixL[m]; dr = dret[m]
    durs = durations(s)
    order = sorted(range(K), key=lambda k: vx[s == k].mean())  # RISK-ON (VIX ต่ำ) → RISK-OFF
    names = ["RISK-ON", "NEUTRAL", "RISK-OFF", "S3", "S4"]

    print("── regime profile (เรียงตาม VIX) ──")
    print(f"  {'regime':>9} | {'freq':>5} | {'VIX avg':>7} | {'gold ret/yr':>11} | {'gold vol':>8} | "
          f"{'DXY/yr':>7} | {'dur':>6}")
    prof = {}
    for rank, k in enumerate(order):
        mk = s == k
        gann = gr[mk].mean() * YR * 100; gvann = gv[mk].mean() * np.sqrt(YR) * 100
        dann = dr[mk].mean() * YR * 100
        dur = np.mean([r for st, r in durs if st == k])
        nm = names[rank] if K <= 5 else f"S{rank}"
        prof[nm] = {"gold_ret_yr": gann, "vix": vx[mk].mean()}
        print(f"  {nm:>9} | {mk.mean()*100:4.0f}% | {vx[mk].mean():6.1f} | {gann:+8.1f}% | "
              f"{gvann:6.1f}% | {dann:+6.1f}% | {dur:5.1f}d")

    # ── VALIDATION ──
    print("\n── VALIDATION ──")
    all_dur = np.mean([r for _, r in durs])
    print(f"  1) PERSISTENCE: {all_dur:.1f}d avg → {'✅' if all_dur >= 4 else '❌ flip เร็ว'}")
    vixs = [vx[s == k].mean() for k in range(K)]
    dist = max(vixs) / min(vixs)
    print(f"  2) DISTINCTNESS: VIX ratio risk-off/on {dist:.1f}x → {'✅ regime ต่างจริง' if dist >= 1.5 else '❌'}")
    fwd = 10
    fv = [np.mean([gr[i:i + fwd].std() for i in np.where(s == k)[0] if i + fwd < len(gr)]) for k in range(K)]
    fsp = np.nanmax(fv) / np.nanmin(fv)
    print(f"  3) FORWARD-PREDICTIVE: forward-{fwd}d gold-vol ratio {fsp:.1f}x → "
          f"{'✅ regime ทำนาย vol ทองข้างหน้าได้' if fsp >= 1.3 else '❌ ไม่ทำนาย'}")
    cut = int(0.7 * len(Fz))
    s2 = GaussianHMM(K).fit(Fz[:cut]).decode(Fz)
    ov = [vx[cut:][s2[cut:] == k].mean() for k in range(K) if (s2[cut:] == k).any()]
    osp = max(ov) / min(ov) if ov and min(ov) > 0 else 0
    print(f"  4) OOS: VIX ratio {osp:.1f}x → {'✅ robust' if osp >= 1.5 else '❌ พัง OOS'}")

    # ── insight: ทองทำตัวยังไงใน risk-off ──
    print("\n── 🔑 insight: gold ในแต่ละ regime ──")
    ro = prof.get("RISK-OFF", {}); ron = prof.get("RISK-ON", {})
    if ro and ron:
        print(f"  RISK-OFF (VIX {ro['vix']:.0f}): gold {ro['gold_ret_yr']:+.0f}%/yr | "
              f"RISK-ON (VIX {ron['vix']:.0f}): gold {ron['gold_ret_yr']:+.0f}%/yr")
        print(f"  → ทองเป็น haven ตอน risk-off?" +
              (" ✅ ใช่ (ret สูงกว่า)" if ro['gold_ret_yr'] > ron['gold_ret_yr']
               else " ⚠️ ไม่ชัด/กลับ (regime-dependent ตรง deep research)"))

    print("\n" + "=" * 78)
    ok = all_dur >= 4 and dist >= 1.5 and fsp >= 1.3 and osp >= 1.5
    print(f"VERDICT: cross-asset risk-regime {'ผ่าน validation ✅ → ใช้เป็น risk-on/off classifier ได้' if ok else 'ยังไม่ผ่านครบ ⚠️'}")
    print("         = risk CONTEXT (sizing/gating/dashboard) ไม่ใช่ directional edge.")
    print("=" * 78)


if __name__ == "__main__":
    main()
