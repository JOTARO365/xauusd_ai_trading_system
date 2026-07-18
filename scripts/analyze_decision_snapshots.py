#!/usr/bin/env python
"""
analyze_decision_snapshots.py — วิเคราะห์ logs/decision_snapshots.jsonl (P1b) แบบมีวินัย (OFFLINE)

lead เดียวที่เหลือหลังปิด offline-backtest: decision_snapshots = ระบบจริง (รวม LLM decision) + F1-F7
(ที่ dataset เก่าไม่มี — gate_blocks มีแค่ 5 coarse feature ที่ AUC ~0.50). สคริปต์นี้ **พร้อมยิง**
เมื่อ data สะสมพอ; รันตอน data น้อย = รายงานสถานะ + "เก็บต่ออีกเท่าไหร่" (ไม่ fit มั่ว).

ทำอะไร:
  1) forward-label ทุก snapshot (ที่มี direction+price+SL/TP) ด้วย xau_m15 (GOLD#) จริง —
     **intrabar M15 H/L fill (SL-priority) + net cost** (บทเรียน close-path artifact) → net-R
  2) per-feature discrimination: F5 bounce_pct / F1 news / F4 momentum / F3 reversal / F6 fast_move /
     F7 vol_tilt — ตัวไหนแยก WIN/LOSS (WR ต่อ bucket) ชนะ base rate
  3) multi-feature CV-AUC + Deflated-Sharpe gauntlet — **gate ที่ MIN_N** (ต่ำกว่า = ไม่ fit, รายงานเฉยๆ)

⚠️ label = forward-price counterfactual (วัด EV ของ "signal ณ decision" ไม่ว่าบอทเข้าจริงมั้ย) — uniform
   ทั้ง EXECUTE+SKIP. selection/look ระวัง: snapshot ต้องมี direction (post-fix). ต้องมี xau_m15 ครอบเวลา snapshot.

รัน: & $PY scripts\\analyze_decision_snapshots.py            (spread 30pt)
     & $PY scripts\\analyze_decision_snapshots.py 40
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

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.environ.get("SNAP_FILE") or os.path.join(_BASE, "logs", "decision_snapshots.jsonl")
M15 = os.path.join(_BASE, "data", "xau_m15.json")
POINT = 0.01
TIME_STOP = 192
SPREAD_PIPS = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
MIN_N = 150          # ต่ำกว่านี้ = ยังไม่ fit/สรุป (skill §6 min-N)
MIN_BUCKET = 25      # ต่อ bucket ต้อง ≥ นี้ถึงรายงาน WR


def _epoch(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d).timestamp()
    except (ValueError, TypeError):
        return None


def load_snaps():
    out = []
    if not os.path.exists(SNAP):
        return out
    for ln in open(SNAP, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try: out.append(json.loads(ln))
            except json.JSONDecodeError: pass
    return out


def load_m15():
    if not os.path.exists(M15):
        return None
    rows = json.load(open(M15))          # [t,o,h,l,c,v]
    t = np.array([r[0] for r in rows], dtype=np.int64)
    return {"t": t, "o": [r[1] for r in rows], "h": [r[2] for r in rows],
            "l": [r[3] for r in rows], "c": [r[4] for r in rows]}


def forward_label(m15, at_epoch, direction, sl_pips, tp_pips, spread):
    """intrabar M15 fill: เข้า open แท่งถัดจาก at → SL/TP first-touch → net-R (net cost)."""
    if not sl_pips or sl_pips <= 0 or not tp_pips:
        return None
    idx = int(np.searchsorted(m15["t"], at_epoch, side="right"))   # แท่งแรกหลัง decision
    if idx >= len(m15["t"]) - 2:
        return None
    entry = m15["o"][idx]
    sign = 1 if direction == "BUY" else -1
    risk = sl_pips * POINT
    sl_px = entry - sign * risk
    tp_px = entry + sign * tp_pips * POINT
    exit_px = None
    for j in range(idx, min(idx + TIME_STOP, len(m15["t"]))):
        hi, lo = m15["h"][j], m15["l"][j]
        if direction == "BUY":
            if lo <= sl_px: exit_px = sl_px; break
            if hi >= tp_px: exit_px = tp_px; break
        else:
            if hi >= sl_px: exit_px = sl_px; break
            if lo <= tp_px: exit_px = tp_px; break
    if exit_px is None:
        j = min(idx + TIME_STOP, len(m15["t"]) - 1); exit_px = m15["c"][j]
    gross = sign * (exit_px - entry) / risk
    return gross - spread / sl_pips


def _bucket_feat(s):
    """ดึง feature จาก snapshot → dict ค่า numeric/label สำหรับ discrimination."""
    z = s.get("f5_zone") or {}
    return {
        "F5_bounce_pct": z.get("bounce_pct"),
        "F5_grade": z.get("grade"),
        "F1_news": s.get("f1_news_score"),
        "F3_reversal": s.get("f3_reversal"),
        "F4_mom_m15": s.get("f4_mom_m15"),
        "F6_fast_move": s.get("f6_fast_move"),
        "F7_vol_tilt": s.get("f7_vol_tilt"),
        "F8_risk_regime": s.get("f8_risk_regime"),
        "sr_strength": s.get("sr_strength"),
    }


def report_feature(name, pairs):
    """pairs = list ของ (value, win_bool). แบ่ง bucket → WR ต่อ bucket (numeric=quartile, cat=ค่า)."""
    vals = [(v, w) for v, w in pairs if v not in (None, "", [])]
    if len(vals) < MIN_BUCKET:
        return
    numeric = all(isinstance(v, (int, float)) for v, _ in vals)
    print(f"  [{name}] n={len(vals)}")
    if numeric:
        arr = np.array([v for v, _ in vals], float)
        qs = np.quantile(arr, [0, .25, .5, .75, 1.0])
        for a, b in zip(qs[:-1], qs[1:]):
            grp = [w for v, w in vals if a <= v <= b] if b == qs[-1] else [w for v, w in vals if a <= v < b]
            if len(grp) >= MIN_BUCKET:
                print(f"     [{a:6.1f},{b:6.1f}) n={len(grp):>4} WR={np.mean(grp)*100:4.0f}%")
    else:
        from collections import Counter
        cnt = Counter(str(v) for v, _ in vals)
        for cat, _ in cnt.most_common():
            grp = [w for v, w in vals if str(v) == cat]
            if len(grp) >= MIN_BUCKET:
                print(f"     {cat:14} n={len(grp):>4} WR={np.mean(grp)*100:4.0f}%")


def main():
    snaps = load_snaps()
    m15 = load_m15()
    print("=" * 72)
    print(f"DECISION_SNAPSHOTS ANALYSIS — {len(snaps)} snapshots | spread {SPREAD_PIPS}pt | intrabar fill")
    print("=" * 72)
    if not snaps:
        print("ไม่มี snapshot — รันบอทเพื่อเก็บก่อน"); return
    if m15 is None:
        print("ไม่มี data/xau_m15.json — รัน scripts/export_xau_history.py GOLD# ก่อน (ใช้ label)"); return

    # breakdown action + coverage
    from collections import Counter
    acts = Counter(s.get("action") for s in snaps)
    with_dir = sum(1 for s in snaps if s.get("direction") in ("BUY", "SELL"))
    print(f"\naction: {dict(acts)}")
    print(f"มี direction (BUY/SELL, post-fix): {with_dir}/{len(snaps)}")
    if with_dir == 0:
        print("\n⚠️ direction=None ทุกอัน = data PRE-FIX (ก่อน a0a89d6) → label ไม่ได้.")
        print("   → restart บอท (fix อยู่ในโค้ดแล้ว) เพื่อเก็บ snapshot ที่มี direction+F1-F7 ครบ.")
        return

    # forward-label + drift/geometry control
    labeled = []
    skills = []
    for s in snaps:
        d = s.get("direction")
        at = _epoch(s.get("at"))
        if d not in ("BUY", "SELL") or at is None:
            continue
        sl, tp = s.get("sl_pips"), s.get("tp_pips")
        nr = forward_label(m15, at, d, sl, tp, SPREAD_PIPS)
        if nr is None:
            continue
        labeled.append((s, nr, 1 if nr > 0 else 0))
        # drift/geometry control (บทเรียน null-test): baseline = ทิศ-neutral = avg ของ BUY กับ SELL
        # จุดเดียวกัน = เก็บ drift+RR-geometry ไว้แต่ตัดข้อมูลทิศออก. skill = actual − baseline.
        rb = forward_label(m15, at, "BUY", sl, tp, SPREAD_PIPS)
        rs = forward_label(m15, at, "SELL", sl, tp, SPREAD_PIPS)
        skills.append(nr - (rb + rs) / 2.0 if (rb is not None and rs is not None) else 0.0)
    n = len(labeled)
    print(f"\nlabelable: {n}/{len(snaps)}  (ต้องมี direction+SL/TP + xau_m15 ครอบเวลา snapshot)")
    if n == 0:
        print("   → xau_m15 ไม่ครอบเวลา snapshot? re-export หรือรอ data ใหม่."); return

    nets = np.array([nr for _, nr, _ in labeled])
    wr = float(np.mean([w for _, _, w in labeled]) * 100)
    print(f"\n── EV รวม RAW (forward-label intrabar, net {SPREAD_PIPS}pt) ──")
    print(f"  net {nets.sum():+.1f}R  avg {nets.mean():+.4f}R/ไม้  WR {wr:.0f}%")
    print(f"  ⚠️ raw net-R มี DRIFT-BIAS (null-test พิสูจน์แล้ว: harness ทำเงินจาก uptrend ทองแม้ไม่มี edge) → ดูตัวล่าง")

    # ── 🔬 DRIFT-CONTROLLED: หัก direction-neutral baseline (drift+geometry) = ตัวชี้ขาดจริง ──
    sk = np.array(skills)
    print(f"\n── 🔬 DRIFT-CONTROLLED (skill = actual − ทิศ-neutral baseline) ──")
    print(f"  skill net {sk.sum():+.1f}R  avg {sk.mean():+.4f}R/ไม้  → "
          f"{'ทิศ (F1-F7 selection) มี edge เหนือ drift ✅' if sk.mean() > 0.005 else 'ทิศไม่เพิ่ม edge เหนือ drift ❌ (raw net = drift artifact)'}")
    print(f"  ← ตัวนี้ + AUC (ด้านล่าง) คือตัวชี้ขาด ไม่ใช่ raw net (drift-invariant ทั้งคู่)")

    if n < MIN_N:
        print(f"\n⚠️ N={n} < MIN_N={MIN_N} → **ยังไม่สรุป/ไม่ fit** (skill §6 min-N — ต่ำกว่านี้ = noise มี weight).")
        print(f"   เก็บต่ออีก ~{MIN_N - n} decisions (บอทรัน). ด้านล่าง = peek หยาบ ห้ามใช้ตัดสิน:")

    # per-feature discrimination (F1-F7)
    print(f"\n── per-feature discrimination (WR ต่อ bucket, base rate {wr:.0f}%) ──")
    feats = {}
    for s, nr, w in labeled:
        for k, v in _bucket_feat(s).items():
            feats.setdefault(k, []).append((v, w))
    for k, pairs in feats.items():
        report_feature(k, pairs)

    if n >= MIN_N:
        # multi-feature CV-AUC (เฉพาะเมื่อ N พอ) — F5 bounce_pct + F1 news + momentum + ...
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import cross_val_score
            X, y = [], []
            for s, nr, w in labeled:
                f = _bucket_feat(s)
                bp = f["F5_bounce_pct"]; nw = f["F1_news"]; fm = f["F6_fast_move"]
                mom = {"UP": 1, "DOWN": -1}.get(str(f["F4_mom_m15"]).upper(), 0)
                rev = 1 if f["F3_reversal"] else 0
                if bp is None:
                    continue
                X.append([float(bp), float(nw or 0), float(fm or 0), mom, rev]); y.append(w)
            if len(set(y)) == 2 and len(y) >= MIN_N:
                X, y = np.array(X), np.array(y)
                cv = min(5, int(min(np.bincount(y))))
                auc = cross_val_score(LogisticRegression(max_iter=1000), X, y, cv=cv, scoring="roc_auc").mean()
                print(f"\n── multi-feature CV-AUC (F5_bounce+F1_news+F6_fast+F4_mom+F3_rev) ──")
                print(f"  AUC {auc:.3f}  {'✅ discriminate ได้' if auc > 0.55 else '≈0.5 ไม่ discriminate ❌'}")
        except ImportError:
            print("  (ไม่มี sklearn — ข้าม multi-feature AUC)")

    print("\n" + "=" * 72)
    print("🔑 VERDICT ยึด: (1) DRIFT-CONTROLLED skill net-R + (2) per-feature AUC — ทั้งคู่ drift-invariant.")
    print("   **อย่าใช้ raw net-R ตัดสิน** (null-test พิสูจน์ว่ามี drift-bias). F5 bounce_pct = สมมติฐานหลัก.")
    print("⚠️ forward-label counterfactual + intrabar + net cost. gate ที่ MIN_N. ต้องผ่าน gauntlet เต็ม")
    print("   (DSR/PBO/holdout + null-test) ก่อนใช้จริง — นี่คือขั้นสำรวจ.")


if __name__ == "__main__":
    main()
