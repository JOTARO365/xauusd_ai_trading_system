#!/usr/bin/env python
"""
build_counterfactual_dataset.py — OFFLINE counterfactual labeled dataset (ไม่แตะ live)

เร่ง Phase 1 (ROADMAP): label ทั้ง (ก) ไม้ที่ถูก "บล็อก" ด้วย forward-price counterfactual
(ไม้ที่ confidence-gate โยนทิ้ง — negative class ที่ trades.json ไม่มี) + (ข) ไม้ที่ "เข้า" จริง
(outcome จาก pnl) → dataset เดียวสำหรับ fit multi-feature model + **probe พิสูจน์ว่า structural
features (trend/zone/strength) discriminate ชนะ confidence** (ที่ WR แบน 33-54% = ไร้ค่า).

feature ที่ครบ 100% ทั้ง blocked+taken: conf / trend / sr_zone / sr_strength / direction.
(mom/fast_move ใน gate_blocks มีแค่ ~9% เพราะ log ทีหลัง → ไม่ใช้ใน probe; ครบ F1-F7 รอ decision_snapshots)

⚠️ CAVEATS: blocked labels = spot-proxy (จาก gate_blocks price series, ไม่ใช่ OHLCV → เอียง WIN,
มองไม่เห็น wick ชน SL); taken labels = real pnl แต่ selection-biased. probe รายงาน CV-AUC (ไม่ใช่
in-sample) แต่ยังเป็น first pass — validate เต็มตาม docs/VALIDATION_CHECKLIST.md ก่อนใช้จริง.

รัน: & $PY scripts\\build_counterfactual_dataset.py
"""
import json
import os
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATES   = os.path.join(_BASE, "logs", "gate_blocks.jsonl")
TRADES  = os.path.join(_BASE, "logs", "trades.json")
OUT     = os.path.join(_BASE, "data", "counterfactual_dataset.jsonl")

SL_PIPS, RR, PIP, EXPIRY_H = 2000, 2.0, 0.01, 24


def _epoch(s):
    try:
        s = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d).timestamp()
    except (ValueError, TypeError):
        return None


def _rows(path):
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try: out.append(json.loads(ln))
            except json.JSONDecodeError: pass
    return out


# ── categorical → numeric (shared feature encoding) ──
def _enc(r):
    tr = {"BULLISH": 1, "BEARISH": -1}.get((r.get("trend") or "").upper(), 0)
    sz = {"SUPPORT": 1, "RESISTANCE": -1}.get((r.get("sr_zone") or "").upper(), 0)
    ss = {"STRONG": 1, "WEAK": -1}.get((r.get("sr_strength") or "").upper(), 0)
    dr = {"BUY": 1, "SELL": -1}.get((r.get("_dir") or "").upper(), 0)
    conf = r.get("_conf")
    return [float(conf), tr, sz, ss, dr] if conf is not None else None


def _label_forward(entry, t0, direction, timeline):
    """WIN/LOSS/None — forward spot timeline (first-touch). direction: BUY/SELL."""
    sign = 1 if direction == "BUY" else -1
    sl = entry - sign * SL_PIPS * PIP
    tp = entry + sign * RR * SL_PIPS * PIP
    for t, px in timeline:
        if t <= t0: continue
        if t > t0 + EXPIRY_H * 3600: break
        # BUY: WIN if px>=tp, LOSS if px<=sl ; SELL: กลับด้าน
        if direction == "BUY":
            if px <= sl: return 0
            if px >= tp: return 1
        else:
            if px >= sl: return 0
            if px <= tp: return 1
    return None


def main():
    gates = _rows(GATES)
    timeline = sorted((_epoch(r["at"]), float(r["price"]))
                      for r in gates if _epoch(r.get("at")) and isinstance(r.get("price"), (int, float)) and r["price"] > 0)

    dataset = []

    # ── (ก) blocked candidates — forward counterfactual label ──
    for r in gates:
        d, t0, px = r.get("signal"), _epoch(r.get("at")), r.get("price")
        if d not in ("BUY", "SELL") or t0 is None or not isinstance(px, (int, float)) or px <= 0:
            continue
        lbl = _label_forward(float(px), t0, d, timeline)
        if lbl is None:
            continue
        row = {"src": "blocked", "at": r.get("at"), "_dir": d, "_conf": r.get("conf"),
               "trend": r.get("trend"), "sr_zone": r.get("sr_zone"), "sr_strength": r.get("sr_strength"),
               "gate": r.get("gate"), "label": lbl, "label_src": "forward_spot_proxy"}
        dataset.append(row)

    # ── (ข) taken trades — real outcome ──
    try:
        td = json.load(open(TRADES, encoding="utf-8"))
        trades = td if isinstance(td, list) else td.get("trades", [])
    except (OSError, json.JSONDecodeError):
        trades = []
    for t in trades:
        if str(t.get("source")) != "SYSTEM" or t.get("status") != "CLOSED":
            continue
        c, p = t.get("technical_confidence"), t.get("pnl")
        if c is None or p is None:
            continue
        dataset.append({"src": "taken", "at": t.get("timestamp"), "_dir": t.get("direction"), "_conf": c,
                        "trend": t.get("trend"), "sr_zone": t.get("sr_zone"), "sr_strength": t.get("sr_strength"),
                        "entry_type": t.get("entry_type"), "label": 1 if float(p) > 0 else 0, "label_src": "real_pnl"})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for row in dataset:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ── discrimination probe: multi-feature vs confidence-only (CV-AUC, ไม่ใช่ in-sample) ──
    def auc(rows, feats_multi):
        Xy = [( _enc(r), r["label"]) for r in rows]
        Xy = [(x, y) for x, y in Xy if x is not None]
        if len({y for _, y in Xy}) < 2 or len(Xy) < 40:
            return None, None, len(Xy)
        X = np.array([x for x, _ in Xy]); y = np.array([y for _, y in Xy])
        cv = min(5, int(min(np.bincount(y))))   # กัน fold ที่ไม่มี class
        if cv < 2: return None, None, len(Xy)
        a_conf = cross_val_score(LogisticRegression(max_iter=1000), X[:, :1], y, cv=cv, scoring="roc_auc").mean()
        cols = list(range(X.shape[1])) if feats_multi else [0]
        a_multi = cross_val_score(LogisticRegression(max_iter=1000), X[:, cols], y, cv=cv, scoring="roc_auc").mean()
        return float(a_conf), float(a_multi), len(Xy)

    def report(name, rows):
        wr = np.mean([r["label"] for r in rows]) if rows else 0
        ac, am, n = auc(rows, True)
        print(f"\n[{name}] n={len(rows)} (labelable {n}) WR={wr*100:.0f}%")
        if ac is None:
            print("  (sample/class ไม่พอทำ AUC)")
        else:
            print(f"  CV-AUC conf-only  : {ac:.3f}  {'(≈0.5 = ไร้ค่า ตรงกับ finding)' if abs(ac-0.5)<0.03 else ''}")
            print(f"  CV-AUC multi-feat : {am:.3f}  (conf+trend+sr_zone+sr_strength+direction)")
            print(f"  → structural ชนะ conf: {am-ac:+.3f}  {'✅ มี signal' if am-ac>0.03 else '≈ ไม่ต่าง'}")

    blocked = [r for r in dataset if r["src"] == "blocked"]
    taken   = [r for r in dataset if r["src"] == "taken"]
    print("=" * 64)
    print(f"COUNTERFACTUAL DATASET — {len(dataset)} rows (blocked {len(blocked)} + taken {len(taken)})")
    print("=" * 64)
    report("blocked (forward spot-proxy)", blocked)
    report("taken (real pnl)", taken)
    report("combined", dataset)
    print(f"\nเขียน: {OUT}")
    print("⚠️ blocked=spot-proxy(เอียง WIN) + taken=selection-biased; feature=5 shared (ยังไม่ครบ F1-F7).")
    print("   ใช้ probe ว่า approach เวิร์คมั้ย — fit จริงต้องผ่าน VALIDATION_CHECKLIST (purge/PBO/DSR/cost) + F1-F7 จาก snapshots.")


if __name__ == "__main__":
    main()
