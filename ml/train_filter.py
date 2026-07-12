"""
train_filter.py — Learned trade filter v2 (offline, phase 0-1)

เทรน logistic regression ทำนาย win/loss ของ trade จาก feature ที่ "รู้ตอนเข้าไม้"
(ไม่ใช่ outcome — กัน leakage) เพื่อแทน gate มือ (EMA_PULLBACK SL/conf) ด้วยโมเดลที่
เรียนจาก data จริง. รัน: python ml/train_filter.py

OFFLINE เท่านั้น — ไม่แตะ pipeline เทรด. ถ้า CV AUC ไม่ชนะ 0.5 อย่างมีนัย → ไม่ ship.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
from db.connection import get_client

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix
import joblib

SEP = "=" * 64
# ⚠️ sl_pips จาก DB `sl` ถูกตัดออก — มัน LEAK outcome: breakeven/trailing เลื่อน SL
# ของไม้กำไรมาใกล้ entry (sl_pips เล็ก) แต่ไม้ขาดทุน SL อยู่เดิม (กว้าง) → win median 100
# vs loss 1000 (10×). ใส่แล้ว AUC พุ่งปลอมเป็น 0.87; ตัดออกได้ AUC จริง ~0.55.
# ถ้าจะใช้ SL ต้องเป็น "planned SL ตอนเข้าไม้" (จาก chart_watcher) ที่ยังไม่ถูกขยับ.
# UPDATE 2026-07-12 (B12): planned_sl_pips ถูก log แยกใน DB แล้ว (writer.py) = leakage-free —
# เพิ่มเป็น NUM_FEAT ได้เมื่อ closed-trade ที่มีคอลัมน์นี้สะสมพอ (ดู sample count + AUC gate ล่าง).
# ยังไม่บังคับใส่ตอนนี้เพื่อไม่ให้ sample หด (แถวเก่าก่อนเพิ่มคอลัมน์ = NULL → ต้องตัดทิ้ง).
NUM_FEATS = ["confidence", "hour"]
CAT_FEATS = ["entry_type", "direction", "trend", "sr_zone", "sr_strength", "sentiment", "pa_action"]


def _trend_clean(v: str) -> str:
    """trend มี free-text ('BEARISH (H4) / BULLISH (M15)') → เอา token หลักตัวแรก."""
    if not v:
        return "UNKNOWN"
    m = re.search(r"BULLISH|BEARISH|SIDEWAYS", str(v).upper())
    return m.group(0) if m else "OTHER"


def load_dataframe() -> pd.DataFrame:
    c = get_client()
    rows = c.table("trades").select(
        "entry_type,technical_confidence,trend,sr_zone,sr_strength,pa_action,sentiment,"
        "direction,sl,entry_price,opened_at,pnl"
    ).eq("status", "CLOSED").limit(5000).execute().data

    recs = []
    for t in rows:
        if t.get("pnl") is None:
            continue
        et = (t.get("entry_type") or "")
        if et.upper().startswith("MANUAL"):          # AI trades only (segment!)
            continue
        e, sl = float(t.get("entry_price") or 0), float(t.get("sl") or 0)
        if not (et and t.get("technical_confidence") is not None and e and sl):
            continue                                  # ต้องมี feature ครบ (346 ไม้)
        hour = 0
        try:
            from datetime import datetime
            hour = datetime.fromisoformat(t["opened_at"].replace("Z", "+00:00")).hour
        except Exception:
            pass
        recs.append({
            # NB: ไม่ใส่ sl_pips = abs(e-sl) — leaky (final SL ถูก trailing/BE ขยับ, ดูคอมเมนต์บนสุด).
            # e/sl ยังใช้เป็น presence-guard ด้านบนเท่านั้น. ใช้ planned_sl_pips (DB) แทนเมื่อ coverage พอ
            "confidence":  float(t["technical_confidence"]),
            "hour":        hour,
            "entry_type":  et.strip().upper(),
            "direction":   (t.get("direction") or "?").upper(),
            "trend":       _trend_clean(t.get("trend")),
            "sr_zone":     (t.get("sr_zone") or "NONE").upper(),
            "sr_strength": (t.get("sr_strength") or "NONE").upper(),
            "sentiment":   (t.get("sentiment") or "NONE").upper()[:12],
            "pa_action":   (t.get("pa_action") or "NONE").upper()[:16],
            "win":         1 if float(t["pnl"]) > 0 else 0,
        })
    return pd.DataFrame(recs)


def build_pipeline() -> Pipeline:
    pre = ColumnTransformer([
        ("num", StandardScaler(), NUM_FEATS),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=8), CAT_FEATS),
    ])
    # L2-regularized logistic (small data → ต้อง regularize), balanced สำหรับ class
    clf = LogisticRegression(max_iter=2000, C=0.5, class_weight="balanced")
    return Pipeline([("pre", pre), ("clf", clf)])


def main():
    df = load_dataframe()
    print(SEP); print("  LEARNED TRADE FILTER v2 — training report"); print(SEP)
    print(f"\nsamples: {len(df)}  | win {df.win.sum()} / loss {(df.win==0).sum()} "
          f"({df.win.mean()*100:.0f}% win baseline)")

    X, y = df[NUM_FEATS + CAT_FEATS], df["win"]
    pipe = build_pipeline()

    # ── 5-fold stratified CV (honest, out-of-sample) ──────────────────────
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc = cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc")
    acc = cross_val_score(pipe, X, y, cv=cv, scoring="accuracy")
    print(f"\n[5-fold CV — out-of-sample]")
    print(f"  ROC-AUC : {auc.mean():.3f} ± {auc.std():.3f}   (0.50 = no skill)")
    print(f"  Accuracy: {acc.mean():.3f} ± {acc.std():.3f}   (baseline {max(df.win.mean(),1-df.win.mean()):.3f})")

    # ── held-out split for confusion + report ─────────────────────────────
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=42)
    pipe.fit(Xtr, ytr)
    proba = pipe.predict_proba(Xte)[:, 1]
    print(f"\n[held-out 25% — AUC {roc_auc_score(yte, proba):.3f}]")
    print(classification_report(yte, (proba >= 0.5).astype(int), target_names=["loss", "win"], digits=2))

    # ── feature importance (coef on the fitted full model) ────────────────
    pipe.fit(X, y)
    names = (NUM_FEATS +
             list(pipe.named_steps["pre"].named_transformers_["cat"].get_feature_names_out(CAT_FEATS)))
    coef = pipe.named_steps["clf"].coef_[0]
    imp = sorted(zip(names, coef), key=lambda x: -abs(x[1]))[:12]
    print("[top features (coef → win when +, loss when −)]")
    for n, c in imp:
        print(f"  {c:+.2f}  {n}")

    # ── verdict + save ────────────────────────────────────────────────────
    print(f"\n{SEP}\n  VERDICT")
    if auc.mean() >= 0.58:
        joblib.dump(pipe, os.path.join(os.path.dirname(__file__), "trade_filter.joblib"))
        print(f"  ✅ AUC {auc.mean():.3f} ≥ 0.58 — มี edge พอควร, saved model → ml/trade_filter.joblib")
        print(f"     ต่อ: phase 2 backtest (replay เป็น filter) ก่อนตัดสินใจ deploy")
    elif auc.mean() >= 0.54:
        print(f"  ⚠️  AUC {auc.mean():.3f} — edge อ่อน. รอ data เพิ่ม / feature ดีขึ้น ก่อน ship")
    else:
        print(f"  ❌ AUC {auc.mean():.3f} — แทบไม่มี edge. อย่า ship; gate มือยังดีกว่า")
    print(SEP)


if __name__ == "__main__":
    main()
