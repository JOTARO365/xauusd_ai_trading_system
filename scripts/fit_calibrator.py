#!/usr/bin/env python
"""
fit_calibrator.py — Phase 1 calibration fitter (OFFLINE, read-only — ไม่แตะ live/decision)

fit calibrator: raw LLM confidence (0-100) -> calibrated P(win) (0-1) จาก trade history.
เป้า Phase 1 (ROADMAP_quant_entry_migration): แก้ปัญหา LLM overconfident (conf 70 แต่ WR จริง 44%)
ก่อนให้ P ขับ EV-gate/Kelly (docs/DESIGN_evidence_based_entry §2, skill quant-systematic-trading).

Source (first pass): logs/trades.json (closed SYSTEM trades: technical_confidence -> pnl>0=win).
Output: data/calibrator_fit.json (isotonic map + platt + reliability + Brier/ECE) — agents/calibrator.py โหลด.

⚠️ CAVEATS (บังคับรู้):
  - SELECTION BIAS: taken trades เท่านั้น -> เรียนรู้ P(win|เข้าไม้) ไม่ใช่ P(win|candidate ใดๆ).
    unbiased version ต้องรอ decision_snapshots.jsonl (label ไม้ที่ถูกบล็อกด้วย). ใช้ตัวนี้เป็น first pass.
  - feature = confidence ตัวเดียว. multi-feature model (F1-F7) = คนละเรื่อง (evidence entry).
  - data span หลาย gate-era/strategy_version -> calibration อาจ drift.

รัน: & $PY scripts\\fit_calibrator.py
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES  = os.path.join(_BASE, "logs", "trades.json")
SNAPS   = os.path.join(_BASE, "logs", "decision_snapshots.jsonl")
OUT     = os.path.join(_BASE, "data", "calibrator_fit.json")

MIN_N = 100   # ต่ำกว่านี้ = "noise with weights" (skill min-N gate) -> ไม่ควรใช้จริง


def load_pairs() -> tuple[np.ndarray, np.ndarray, str]:
    """(conf, win) จาก closed SYSTEM trades — รวม DB (source of truth) + trades.json, dedup by ticket.
    win = pnl > 0."""
    all_trades, src = [], []
    # 1) DB ก่อน (source of truth; get_trades คืน None ถ้าต่อไม่ได้ = fail-soft)
    try:
        if _BASE not in sys.path:
            sys.path.insert(0, _BASE)
        from db.reader import get_trades
        db = get_trades()
        if db:
            all_trades += db
            src.append(f"DB:{len(db)}")
        else:
            src.append("DB:none")
    except Exception:
        src.append("DB:err")
    # 2) trades.json (เสริม/fallback)
    try:
        data = json.load(open(TRADES, encoding="utf-8"))
        js = data if isinstance(data, list) else data.get("trades", [])
        all_trades += js
        src.append(f"json:{len(js)}")
    except (OSError, json.JSONDecodeError):
        src.append("json:err")
    # 3) merge/dedup by ticket (DB มาก่อน = ชนะ), filter closed SYSTEM + มี conf/pnl
    seen, X, y = set(), [], []
    for t in all_trades:
        tk = t.get("ticket")
        if tk is not None and tk in seen:
            continue
        if str(t.get("source")) != "SYSTEM" or t.get("status") != "CLOSED":
            continue
        c, p = t.get("technical_confidence"), t.get("pnl")
        if c is None or p is None:
            continue
        if tk is not None:
            seen.add(tk)
        X.append(float(c))
        y.append(1 if float(p) > 0 else 0)

    # 4) fallback/supplement: data/calibration.json = reliability bins ของ dataset เต็ม (บอทคำนวณ
    #    ด้วย DB access). ถ้า raw pairs (DB ต่อไม่ได้ + json บาง) น้อยกว่า → ใช้ bins expand เป็น
    #    pseudo-pairs (conf=midpoint, win/loss ตาม wr×n) = ตัวแทน full dataset โดยไม่ต้องต่อ DB.
    bx, by, bn = _bin_pairs()
    if bn > len(X):
        src.append(f"calibration.json:bins({bn})→ใช้แทน raw({len(X)})")
        return np.array(bx, dtype=float), np.array(by, dtype=float), " + ".join(src)
    return np.array(X, dtype=float), np.array(y, dtype=float), " + ".join(src)


def _bin_pairs() -> tuple[list, list, int]:
    """expand data/calibration.json reliability bins → pseudo (conf, win) pairs (ตัวแทน full dataset)."""
    path = os.path.join(_BASE, "data", "calibration.json")
    try:
        bins = json.load(open(path, encoding="utf-8")).get("bins", [])
    except (OSError, json.JSONDecodeError):
        return [], [], 0
    X, y = [], []
    for b in bins:
        lo, hi, nn, wr = b.get("conf_lo"), b.get("conf_hi"), b.get("n"), b.get("wr")
        if None in (lo, hi, nn, wr):
            continue
        mid = (lo + hi) / 2.0
        wins = round(nn * wr)
        X += [mid] * wins + [mid] * (nn - wins)
        y += [1] * wins + [0] * (nn - wins)
    return X, y, len(X)


def brier(P: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((P - y) ** 2))


def ece(P: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected Calibration Error."""
    edges, e = np.linspace(0, 1, bins + 1), 0.0
    for i in range(bins):
        hi_incl = i == bins - 1
        m = (P >= edges[i]) & ((P <= edges[i + 1]) if hi_incl else (P < edges[i + 1]))
        if m.sum():
            e += abs(P[m].mean() - y[m].mean()) * m.sum() / len(P)
    return float(e)


def reliability(X: np.ndarray, y: np.ndarray) -> list[dict]:
    out = []
    for lo, hi in [(55, 59), (60, 64), (65, 69), (70, 74), (75, 79), (80, 84), (85, 100)]:
        m = (X >= lo) & (X <= hi)
        if m.sum():
            out.append({"conf_lo": lo, "conf_hi": hi, "n": int(m.sum()), "wr": round(float(y[m].mean()), 4)})
    return out


def main():
    X, y, src = load_pairs()
    n = len(X)
    if n == 0:
        print(f"❌ ไม่มี trade ที่ใช้ได้ (technical_confidence + pnl). source: {src}")
        return
    raw = X / 100.0   # naive interpretation: conf% = P(win)

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(X, y)
    P_iso = iso.predict(X)
    platt = LogisticRegression().fit(X.reshape(-1, 1), y)
    P_platt = platt.predict_proba(X.reshape(-1, 1))[:, 1]

    result = {
        "ok": True, "n": n, "overall_wr": round(float(y.mean()), 4),
        "min_n_ok": n >= MIN_N,
        "reliability": reliability(X, y),
        "brier": {"raw_conf": round(brier(raw, y), 4), "isotonic": round(brier(P_iso, y), 4),
                  "platt": round(brier(P_platt, y), 4)},
        "ece": {"raw_conf": round(ece(raw, y), 4), "isotonic": round(ece(P_iso, y), 4),
                "platt": round(ece(P_platt, y), 4)},
        "isotonic_map": {"x": [round(float(v), 2) for v in iso.X_thresholds_],
                         "y": [round(float(v), 4) for v in iso.y_thresholds_]},
        "platt": {"coef": round(float(platt.coef_[0][0]), 6), "intercept": round(float(platt.intercept_[0]), 6)},
        "source": f"DB + logs/trades.json (taken SYSTEM trades, deduped) [{src}]",
        "caveats": "SELECTION BIAS (taken trades only); feature=confidence only; unbiased+multi-feature ต้องรอ decision_snapshots",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("=" * 62)
    print(f"CALIBRATION FIT (Phase 1, first pass) — n={n}, overall WR={y.mean()*100:.1f}%")
    print("=" * 62)
    if n < MIN_N:
        print(f"⚠️  n={n} < {MIN_N} (min-N) — first pass เท่านั้น, ยังไม่ควร enable จริง\n")
    print("Reliability — conf ที่ระบบให้ vs WR จริง:")
    for b in result["reliability"]:
        naive = (b["conf_lo"] + b["conf_hi"]) / 2
        gap = b["wr"] * 100 - naive
        flag = " ⚠️OVERCONF" if gap < -8 else ""
        print(f"  conf {b['conf_lo']:>2}-{b['conf_hi']:<3}: WR จริง {b['wr']*100:>4.0f}%  "
              f"(ถ้าเชื่อ conf ตรงๆ~{naive:.0f}%, ห่าง {gap:+.0f}){flag}  n={b['n']}")
    print(f"\nBrier (ต่ำ=ดี):  raw_conf {result['brier']['raw_conf']}  |  "
          f"isotonic {result['brier']['isotonic']}  |  platt {result['brier']['platt']}")
    print(f"ECE   (ต่ำ=ดี):  raw_conf {result['ece']['raw_conf']}  |  "
          f"isotonic {result['ece']['isotonic']}  |  platt {result['ece']['platt']}")
    improved = result['ece']['raw_conf'] - min(result['ece']['isotonic'], result['ece']['platt'])
    print(f"\n→ calibration ลด ECE ได้ {improved:+.3f} (raw confidence miscalibrated แค่ไหน = ช่องว่างนี้)")
    print(f"เขียน: {OUT}")
    print("⚠️  selection bias + confidence-only = first pass. unbiased/multi-feature ต้องรอ decision_snapshots สะสม.")


if __name__ == "__main__":
    main()
