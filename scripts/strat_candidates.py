#!/usr/bin/env python
"""strat_candidates.py — generator ของกลยุทธ์ผู้สมัคร (จาก persona brainstorm) สำหรับ strategy_search.

แต่ละ gen(D) รับ dict {ts,o,h,l,c,v arrays} คืน list ของ signal {i,dir,sl_pips,tp_pips}.
gate เรียงตาม cost (ถูก→แพง) เพื่อความเร็ว. ⚠️ harness ใช้ fixed MAX_HOLD/SL-TP exit = SCREEN
(ตัวที่ผ่านค่อย validate time-stop จริงต่อ). ทุกตัวออกแบบต่างจาก momentum/fade/cross-lead ที่ disprove แล้ว.
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


def _px_sl_tp(entry, sl_price, tp_price):
    return max(1, round(abs(entry - sl_price) / POINT)), max(1, round(abs(entry - tp_price) / POINT))


# ── S-OU: OU mean-reversion gated by Hurst<0.45 ∧ ADF<−2.9 ∧ half-life∈[4,40] (consensus Math/ML/Quant) ──
def ou_reversion(D, W=100, Z=1.5, COOL=5):
    c, h, l = D["c"], D["h"], D["l"]; logp = np.log(c); n = len(c); out = []; last = -10 ** 9
    for i in range(W, n - 1):
        if i - last < COOL:
            continue
        fit = S.ou_fit(logp[i - W:i + 1])                 # ถูกสุดก่อน
        if not fit:
            continue
        mu, hl, sig, z, b = fit
        if not (3 <= hl <= 60) or abs(z) < Z:
            continue
        seg = logp[i - W:i + 1]
        if S.adf_tstat(seg) > -2.7:                       # แพงขึ้น เช็คทีหลัง
            continue
        if S.hurst(c[i - W:i + 1]) >= 0.50:
            continue
        d = "SELL" if z > 0 else "BUY"
        sl_price = np.exp(mu + np.sign(z) * 3.5 * sig); tp_price = np.exp(mu)
        slp, tpp = _px_sl_tp(c[i], sl_price, tp_price)
        out.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


# ── S-VR: Variance-ratio reversion (Lo-MacKinlay ψ*<−1.96 = negative autocorr) ──
def varratio_reversion(D, W=250, q=4, COOL=6):
    c = D["c"]; logr = np.diff(np.log(c)); ema = S.ema(c, 20); atr = _atr(D)
    n = len(c); out = []; last = -10 ** 9
    for i in range(W, n - 1):
        if i - last < COOL:
            continue
        z = S.variance_ratio_z(logr[i - W:i], q)
        if z >= -1.3:                                     # negative autocorr (ผ่อนให้ถึง min-N)
            continue
        sig1 = np.std(logr[i - W:i]) * c[i]               # ~pip band
        band = 1.0 * sig1 * np.sqrt(q)
        dev = c[i] - ema[i]
        if abs(dev) < band:
            continue
        d = "SELL" if dev > 0 else "BUY"; sign = 1.0 if d == "BUY" else -1.0
        sl_price = c[i] - sign * 2.5 * sig1 * np.sqrt(q); tp_price = ema[i]
        slp, tpp = _px_sl_tp(c[i], sl_price, tp_price)
        out.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


# ── S-RATIO: Gold-Silver ratio relative-value reversion (ML S6/Quant S8) ──
def ratio_rv(D, W=200, Z=2.0, COOL=12):
    xau = D
    xag = np.array(json.load(open(os.path.join(_BASE, "data", "drv_xag_h1.json"))), dtype=float)
    xag_map = {int(xag[k, 0]): float(xag[k, 4]) for k in range(len(xag))}
    ts, c, h, l = xau["ts"], xau["c"], xau["h"], xau["l"]; atr = _atr(D)
    # สร้าง ratio series align (ใช้ silver close ที่ ts ตรงกัน; ถ้าไม่มี = nan)
    sil = np.array([xag_map.get(int(t), np.nan) for t in ts])
    # forward-fill silver (sparse 27% ของบาร์) → กัน window เต็มไปด้วย nan
    for k in range(1, len(sil)):
        if np.isnan(sil[k]):
            sil[k] = sil[k - 1]
    ratio = c / sil
    out = []; last = -10 ** 9
    for i in range(W, len(c) - 1):
        if i - last < COOL:
            continue
        seg = ratio[i - W:i + 1]
        if np.isnan(seg).any():
            continue
        m, sd = seg[:-1].mean(), seg[:-1].std()
        if sd <= 0:
            continue
        zr = (ratio[i] - m) / sd
        if abs(zr) < Z:
            continue
        # displacement: ขาทองเป็นตัวเบี่ยง (|z_gold| > |z_silver|)
        cg = c[i - W:i + 1]; cs = sil[i - W:i + 1]
        zg = (c[i] - cg[:-1].mean()) / (cg[:-1].std() + 1e-9)
        zs = (sil[i] - cs[:-1].mean()) / (cs[:-1].std() + 1e-9)
        if abs(zg) <= abs(zs):
            continue
        d = "SELL" if zr > 0 else "BUY"                    # ratio สูง=ทองแพง→short
        a = float(atr[i])
        if a <= 0:
            continue
        sign = 1.0 if d == "BUY" else -1.0
        slp = max(1, round(2.0 * a / POINT)); tpp = max(1, round(2.0 * a / POINT))
        out.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


# ── S-NR7: Volatility-compression expansion (Quant S3 — vol clustering) ──
def vol_compression(D, COOL=6):
    h, l, c = D["h"], D["l"], D["c"]; atr = _atr(D); n = len(c); out = []; last = -10 ** 9
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    tr = np.concatenate([[h[0] - l[0]], tr])
    for i in range(20, n - 1):
        if i - last < COOL:
            continue
        if tr[i] != tr[i - 6:i + 1].min():                # NR7: TR ต่ำสุดใน 7 บาร์
            continue
        coil_h = h[i - 6:i + 1].max(); coil_l = l[i - 6:i + 1].min()
        a = float(atr[i]); w = coil_h - coil_l
        if a <= 0 or w <= 0:
            continue
        for j in range(i + 1, min(i + 7, n)):             # break ภายใน 6 บาร์
            if c[j] > coil_h + 0.15 * a:
                d = "BUY"; break
            if c[j] < coil_l - 0.15 * a:
                d = "SELL"; break
        else:
            continue
        sign = 1.0 if d == "BUY" else -1.0
        sl_price = coil_l if d == "BUY" else coil_h; tp_price = c[j] + sign * 2.0 * w
        slp, tpp = _px_sl_tp(c[j], sl_price, tp_price)
        out.append({"i": j, "dir": d, "sl_pips": slp, "tp_pips": tpp}); last = j
    return out


# ── S-OVR: Single-bar overreaction reversion (Quant S4/ML S5 — liquidity vacuum) ──
def overreaction(D, COOL=3):
    h, l, c, o = D["h"], D["l"], D["c"], D["o"]; atr = _atr(D); vp = R.vol_percentile(c); n = len(c)
    out = []; last = -10 ** 9
    for i in range(20, n - 1):
        if i - last < COOL:
            continue
        a = float(atr[i]); rng = h[i] - l[i]
        if a <= 0 or rng < 3.0 * a:                       # บาร์ใหญ่ >3ATR
            continue
        clv = (2 * c[i] - h[i] - l[i]) / rng              # close location −1..+1
        if abs(clv) < 0.5:
            continue
        if not (vp[i] < 0.60):                            # spike บนพื้น vol ปกติ (น่าจะ noise ไม่ใช่ repricing)
            continue
        d = "BUY" if clv < 0 else "SELL"                  # ปิดปลายล่าง(spike ลง)→long
        sign = 1.0 if d == "BUY" else -1.0
        ext = l[i] if d == "BUY" else h[i]
        sl_price = ext - sign * 0.3 * a; tp_price = c[i] + sign * 0.5 * rng
        slp, tpp = _px_sl_tp(c[i], sl_price, tp_price)
        out.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


# ── S-GAP: Overnight/session gap reversion (Quant S5 — never tested) ──
def gap_reversion(D, COOL=4):
    o, c, h, l = D["o"], D["c"], D["h"], D["l"]; atr = _atr(D); ts = D["ts"]; n = len(c)
    out = []; last = -10 ** 9
    for i in range(20, n - 1):
        if i - last < COOL:
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        gap = o[i] - c[i - 1]; gatr = gap / a
        if not (0.5 <= abs(gatr) <= 2.5):
            continue
        # ไม่ทะลุ prior range เกิน 0.3ATR (ตัด breakaway)
        if gap > 0 and o[i] > h[i - 1] + 0.3 * a:
            continue
        if gap < 0 and o[i] < l[i - 1] - 0.3 * a:
            continue
        d = "SELL" if gap > 0 else "BUY"                  # gap up→short (เติมลง)
        sign = 1.0 if d == "BUY" else -1.0
        sl_price = o[i] + sign * 1.0 * a if d == "SELL" else o[i] - 1.0 * a
        sl_price = o[i] - sign * 1.0 * a
        tp_price = c[i - 1] + 0.5 * gap                   # fill 50% gap
        slp, tpp = _px_sl_tp(c[i], sl_price, tp_price)
        out.append({"i": i, "dir": d, "sl_pips": slp, "tp_pips": tpp}); last = i
    return out


# ── S-SEA: Hour-of-day seasonality drift (Math S7/Quant S6, IS-fit → OOS-tested by harness) ──
def seasonality_hour(D, H=6):
    ts, c = D["ts"], D["c"]; atr = _atr(D); n = len(c)
    hours = ((ts // 3600) % 24).astype(int)
    fwd = np.full(n, np.nan)
    fwd[:n - H] = np.log(c[H:] / c[:n - H])               # forward H-bar return
    split = int(n * 0.6)                                  # fit bucket บน IS เท่านั้น
    dir_by_hour = {}
    for hr in range(24):
        m = (hours[:split] == hr) & ~np.isnan(fwd[:split])
        if m.sum() < 100:
            continue
        r = fwd[:split][m]; t = r.mean() / (r.std() / np.sqrt(len(r)) + 1e-12)
        if abs(t) > 2.0:                                  # bucket มีนัย (IS)
            dir_by_hour[hr] = "BUY" if r.mean() > 0 else "SELL"
    out = []
    for i in range(20, n - 1):
        hr = hours[i]
        if hr not in dir_by_hour:
            continue
        a = float(atr[i])
        if a <= 0:
            continue
        slp = max(1, round(1.5 * a / POINT)); tpp = max(1, round(1.5 * a / POINT))
        out.append({"i": i, "dir": dir_by_hour[hr], "sl_pips": slp, "tp_pips": tpp})
    return out


ALL = [
    ("OU-reversion (Hurst+ADF+HL)", "h1", ou_reversion),
    ("Variance-ratio reversion", "h1", varratio_reversion),
    ("Gold-Silver ratio RV", "h1", ratio_rv),
    ("Vol-compression NR7", "h1", vol_compression),
    ("Single-bar overreaction", "h1", overreaction),
    ("Gap reversion", "h1", gap_reversion),
    ("Hour seasonality (IS→OOS)", "h1", seasonality_hour),
]
