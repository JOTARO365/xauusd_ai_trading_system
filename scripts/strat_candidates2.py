#!/usr/bin/env python
"""strat_candidates2.py — candidates ชุด 2 (ML/advanced) สำหรับ strategy_search.

ML strategies fit บน IS (60% แรก) เท่านั้น → harness OOS gate ทดสอบ holdout (ไม่ look-ahead).
gen(D) คืน list {i,dir,sl_pips,tp_pips}. ใช้ sklearn/scipy. GARCH→EWMA proxy (ไม่มี arch lib).
"""
import json
import os

import numpy as np

import regime_lib as R
import strat_stats as S

POINT = R.POINT
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _atr(D, n=14):
    return R.atr(D["h"], D["l"], D["c"], n)


def _roll_min(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].min()
    return out


def _features(D):
    """feature matrix ต่อบาร์ (คำนวณจากอดีตล้วน). คืน (X dict, n)."""
    c, h, l = D["c"], D["h"], D["l"]; n = len(c)
    er = R.efficiency_ratio(c, 20); adx = R.adx(h, l, c); atr = _atr(D)
    vp = R.vol_percentile(c)
    r = np.zeros(n); r[1:] = np.diff(np.log(c))
    ac1 = np.full(n, 0.0)
    for i in range(52, n):                                # autocorr lag-1 rolling 50
        a = r[i - 50:i]; b = r[i - 51:i - 1]
        if a.std() > 0 and b.std() > 0:
            ac1[i] = np.corrcoef(a, b)[0, 1]
    rmin = _roll_min(l, 50); rmax = -_roll_min(-h, 50)
    dist = np.where(atr > 0, (c - rmin) / atr, 0.0)
    hr = ((D["ts"] // 3600) % 24).astype(float)
    return {"er": er, "adx": adx, "atr": atr, "vp": vp, "ac1": ac1, "dist": dist,
            "hsin": np.sin(2 * np.pi * hr / 24), "hcos": np.cos(2 * np.pi * hr / 24), "r": r}, n


def _triple_barrier(i, side, atr, h, l, c, tp_m=1.0, sl_m=1.0, vbar=24):
    """label 1 ถ้าแตะ TP (ทิศ side) ก่อน SL/timeout. side=+1 long / −1 short."""
    entry = c[i]; a = atr[i]
    if a <= 0:
        return 0
    tp = entry + side * tp_m * a; sl = entry - side * sl_m * a
    end = min(i + vbar, len(c) - 1)
    for j in range(i + 1, end + 1):
        if side > 0:
            if l[j] <= sl:
                return 0
            if h[j] >= tp:
                return 1
        else:
            if h[j] >= sl:
                return 0
            if l[j] <= tp:
                return 1
    return 0


# ── TSMOM-D1: time-series momentum รายวัน vol-targeted (ML S4 — documented anomaly, horizon ยาว) ──
def tsmom_d1(_D):
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_d1.json"))), dtype=float)
    ts, h, l, c = d[:, 0], d[:, 2], d[:, 3], d[:, 4]
    atr = R.atr(h, l, c, 22); L = 63; n = len(c); out = []
    for i in range(L, n - 1):
        if i % 5 != 0:                                     # rebalance ทุก 5 D1 (weekly)
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        mom = np.sign(np.log(c[i] / c[i - L]))
        if mom == 0:
            continue
        d_ = "BUY" if mom > 0 else "SELL"
        slp = max(1, round(3.0 * a / POINT)); tpp = max(1, round(6.0 * a / POINT))
        out.append({"i": i, "dir": d_, "sl_pips": slp, "tp_pips": tpp})
    return out


# ── Meta-labeling: primary=momentum sign, logistic กรอง "เมื่อไหร่ควรเชื่อ" (ML S1 top-pick) ──
def meta_label(D):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    c, h, l = D["c"], D["h"], D["l"]; F, n = _features(D); atr = F["atr"]
    split = int(n * 0.6); cols = ["er", "adx", "vp", "dist", "ac1", "hsin", "hcos"]
    Xs, ys, idx = [], [], []
    for i in range(500, split):                            # train: IS (หลัง vp warmup 480)
        if atr[i] <= 0:
            continue
        side = np.sign(c[i] - c[i - 12])
        if side == 0:
            continue
        row = [F[k][i] for k in cols]
        if not np.all(np.isfinite(row)):
            continue
        Xs.append(row); ys.append(_triple_barrier(i, side, atr, h, l, c, 1, 1, 24)); idx.append(i)
    if len(set(ys)) < 2 or len(ys) < 200:
        return []
    sc = StandardScaler().fit(Xs); clf = LogisticRegression(max_iter=200).fit(sc.transform(Xs), ys)
    out = []
    for i in range(500, n - 1):                            # predict: หลัง warmup
        if atr[i] <= 0:
            continue
        side = np.sign(c[i] - c[i - 12])
        if side == 0:
            continue
        row = [F[k][i] for k in cols]
        if not np.all(np.isfinite(row)):
            continue
        p = clf.predict_proba(sc.transform([row]))[0, 1]
        if p < 0.60:
            continue
        d_ = "BUY" if side > 0 else "SELL"
        slp = max(1, round(1.0 * atr[i] / POINT))
        out.append({"i": i, "dir": d_, "sl_pips": slp, "tp_pips": slp})
    return out


# ── Clustering conditional drift: KMeans market-states → เทรด cluster ที่ drift มีนัย (ML S3) ──
def cluster_drift(D):
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    c = D["c"]; F, n = _features(D); atr = F["atr"]
    vov = np.zeros(n)
    for i in range(52, n):                                 # vol-of-vol
        seg = atr[i - 50:i]
        vov[i] = np.std(np.diff(seg) / (seg[:-1] + 1e-9))
    cols = [F["er"], F["adx"], F["vp"], F["ac1"], vov]
    X = np.column_stack(cols); split = int(n * 0.6); H = 12
    fwd = np.full(n, np.nan); fwd[:n - H] = np.log(c[H:] / c[:n - H])
    fin = np.all(np.isfinite(X), axis=1)                   # กัน NaN warmup (vp 480)
    tr_mask = fin.copy(); tr_mask[split:] = False; tr_mask[:500] = False
    Xtr = X[tr_mask]; fwd_tr = fwd[tr_mask]
    if len(Xtr) < 500:
        return []
    sc = StandardScaler().fit(Xtr); km = KMeans(n_clusters=5, n_init=5, random_state=0).fit(sc.transform(Xtr))
    lab_tr = km.labels_
    sel = {}
    for k in range(5):                                     # cluster ที่ drift มีนัย (IS)
        m = fwd_tr[lab_tr == k]; m = m[~np.isnan(m)]
        if len(m) < 50:
            continue
        t = m.mean() / (m.std() / np.sqrt(len(m)) + 1e-12)
        if abs(t) >= 3:
            sel[k] = "BUY" if m.mean() > 0 else "SELL"
    if not sel:
        return []
    out = []
    for i in range(500, n - 1):
        if atr[i] <= 0 or not fin[i]:
            continue
        lab = km.predict(sc.transform(X[i:i + 1]))[0]
        if lab not in sel:
            continue
        slp = max(1, round(1.5 * atr[i] / POINT))
        out.append({"i": i, "dir": sel[lab], "sl_pips": slp, "tp_pips": slp})
    return out


# ── CUSUM event → logistic classifier (ML S8 — event sampling ลด noise) ──
def cusum_event(D):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    c, h, l = D["c"], D["h"], D["l"]; F, n = _features(D); atr = F["atr"]; r = F["r"]
    ew = np.zeros(n)                                        # ewma std ของ return
    for i in range(1, n):
        ew[i] = 0.94 * ew[i - 1] + 0.06 * r[i] ** 2
    ews = np.sqrt(ew); sp = sm = 0.0; events = []
    for i in range(2, n):
        sp = max(0.0, sp + r[i]); sm = min(0.0, sm + r[i]); thr = 3.0 * ews[i]
        if sp >= thr:
            events.append((i, +1)); sp = sm = 0.0
        elif sm <= -thr:
            events.append((i, -1)); sp = sm = 0.0
    split = int(n * 0.6); cols = ["er", "adx", "vp", "dist"]
    Xs, ys = [], []
    for (i, bd) in events:
        if i >= split or i < 500 or atr[i] <= 0:
            continue
        row = [F[k][i] for k in cols] + [bd]
        if not np.all(np.isfinite(row)):
            continue
        Xs.append(row); ys.append(_triple_barrier(i, bd, atr, h, l, c, 1, 1, 8))
    if len(set(ys)) < 2 or len(ys) < 150:
        return []
    sc = StandardScaler().fit(Xs); clf = LogisticRegression(max_iter=200).fit(sc.transform(Xs), ys)
    out = []
    for (i, bd) in events:
        if i < 500 or atr[i] <= 0:
            continue
        row = [F[k][i] for k in cols] + [bd]
        if not np.all(np.isfinite(row)):
            continue
        p = clf.predict_proba(sc.transform([row]))[0, 1]
        if p < 0.58:
            continue
        slp = max(1, round(1.0 * atr[i] / POINT))
        out.append({"i": i, "dir": "BUY" if bd > 0 else "SELL", "sl_pips": slp, "tp_pips": slp})
    return out


# ── Fracdiff + AR-sign reversion (Math S6 — stationary แต่คง long memory) ──
def fracdiff_ar(D, W=200, ZT=1.8, COOL=6):
    c = D["c"]; atr = _atr(D); logp = np.log(c)
    Fd = S.fracdiff(logp, 0.4); n = len(c); out = []; last = -10 ** 9
    for i in range(W + 20, n - 1):
        if i - last < COOL or np.isnan(Fd[i]):
            continue
        seg = Fd[i - W:i + 1]
        if np.isnan(seg).any() or seg.std() == 0:
            continue
        z = (Fd[i] - seg[:-1].mean()) / seg[:-1].std()
        ac = np.corrcoef(seg[1:], seg[:-1])[0, 1]
        if ac >= 0 or abs(z) < ZT:                         # ต้อง mean-revert (autocorr<0)
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        d_ = "SELL" if z > 0 else "BUY"
        slp = max(1, round(2.0 * a / POINT)); tpp = max(1, round(2.0 * a / POINT))
        out.append({"i": i, "dir": d_, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


# ── Permutation-entropy-gated reversion (Math S8 — เข้า reversion เฉพาะช่วง predictable) ──
def pe_reversion(D, W=200, COOL=6):
    c = D["c"]; atr = _atr(D); ema = S.ema(c, 20); n = len(c); out = []; last = -10 ** 9
    pe = np.full(n, np.nan)
    for i in range(W, n):
        pe[i] = S.perm_entropy(c[i - W:i + 1], m=4, tau=1)
    for i in range(W + 50, n - 1):
        if i - last < COOL or np.isnan(pe[i]):
            continue
        peh = pe[i - 300:i]; peh = peh[~np.isnan(peh)]
        if len(peh) < 50 or pe[i] >= np.percentile(peh, 20):   # ต้อง entropy ต่ำ (predictable)
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        sd = np.std(c[i - 20:i])
        z = (c[i] - ema[i]) / (sd + 1e-9)
        if abs(z) < 1.5:
            continue
        d_ = "SELL" if z > 0 else "BUY"
        slp = max(1, round(2.0 * a / POINT)); tpp = max(1, round(abs(c[i] - ema[i]) / POINT) or 1)
        out.append({"i": i, "dir": d_, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


ALL = [
    ("TSMOM D1 vol-target", "d1", tsmom_d1),
    ("Meta-labeling (logistic)", "h1", meta_label),
    ("Clustering drift (KMeans)", "h1", cluster_drift),
    ("CUSUM event (logistic)", "h1", cusum_event),
    ("Fracdiff AR-sign", "h1", fracdiff_ar),
    ("Perm-entropy reversion", "h1", pe_reversion),
]
