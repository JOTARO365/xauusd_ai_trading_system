"""
decision_snapshot.py — P1b SHADOW snapshot logging (ADD-ONLY, 0 behavior change)

บันทึก feature vector (F1..F7 ตาม docs/DESIGN_evidence_based_entry.md §2) + outcome ของ
ทุก decision (EXECUTE / SKIP / blocked) → logs/decision_snapshots.jsonl เพื่อสะสม labeled
data ให้ evidence-based entry model. ปิดช่องว่าง P1 (feature หลัก 4 ตัว coverage 0% ใน log เดิม).

⚠️ SHADOW-ONLY: log อย่างเดียว — ไม่แตะ decision/gate/order/money ใดๆ. เรียก fail-soft:
error ใด ๆ = ไม่ทำอะไร, cycle เดินต่อปกติ. ปิดได้ด้วย env DECISION_SNAPSHOT=false.

label (WIN/LOSS) ทำ offline ทีหลังด้วย forward price (scripts/build_entry_dataset.py).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

import config as _cfg

_SNAP = Path("logs") / "decision_snapshots.jsonl"


def _news_score() -> dict:
    """F1/F2 — news_impact aggregate ณ ตอน decision (อ่านไฟล์เดียวกับ NEWS_GATE)."""
    try:
        p = Path(__file__).resolve().parent.parent / "data" / "news_impact.json"
        with open(p, encoding="utf-8") as f:
            snap = json.load(f)
        agg = snap.get("aggregate") or {}
        return {"score": agg.get("score"), "n": agg.get("n_scored"), "updated": snap.get("updated")}
    except Exception:
        return {"score": None, "n": None, "updated": None}


def _risk_regime():
    """F8 — cross-asset HMM risk regime (RISK-ON/NEUTRAL/RISK-OFF) ณ ตอน decision.
    อ่าน data/risk_regime_now.json (scripts/fetch_risk_regime.py, รายวัน). fail-soft → None.
    = validated vol/risk context (ทำนาย forward vol) — ไม่ใช่ directional signal. เก็บไว้ validate."""
    try:
        p = Path(__file__).resolve().parent.parent / "data" / "risk_regime_now.json"
        with open(p, encoding="utf-8") as f:
            return (json.load(f) or {}).get("regime")
    except Exception:
        return None


def _nearest_zone(chart_data: dict, price, direction: str) -> dict:
    """F5 — sr_meta zone ที่ใกล้ราคาสุดฝั่งที่เกี่ยว (BUY→Support / SELL→Resistance).
    ดึง bounce_pct/break_pct/n_tests/grade เป็น empirical prior."""
    srm = chart_data.get("sr_meta") or []
    side = "S" if direction == "BUY" else "R"
    cands = [m for m in srm if m.get("side") == side and m.get("level") and price]
    if not cands:
        return {}
    m = min(cands, key=lambda z: abs(z["level"] - price))
    return {"level": m.get("level"), "bounce_pct": m.get("bounce_pct"), "break_pct": m.get("break_pct"),
            "n_tests": m.get("n_tests"), "grade": m.get("grade"), "score": m.get("score"),
            "bars_since_touch": m.get("bars_since_touch")}


def log_decision_snapshot(chart_data: dict, sentiment_data: dict | None,
                          decision_result: dict | None) -> None:
    """Append 1 snapshot/decision. fail-soft — ห้าม raise ออกไปกระทบ cycle."""
    try:
        if not getattr(_cfg, "DECISION_SNAPSHOT", True):
            return
        cd = chart_data or {}
        dr = decision_result or {}
        mom = cd.get("momentum_tf") or {}
        plan = cd.get("plan") or {}
        px = ((cd.get("price_info") or {}).get("bid")
              or cd.get("current_price")
              or ((cd.get("indicators") or {}).get("h1") or {}).get("close"))
        # candidate direction: บนไม้ที่ถูกบล็อก decision ไม่มี direction → ใช้ chart_watcher signal (top-level)
        direction = dr.get("direction") or cd.get("direction") or cd.get("signal")
        news = _news_score()
        rec = {
            "at": datetime.now(timezone.utc).isoformat(),
            # ── outcome ของ decision (label WIN/LOSS ทีหลัง offline ด้วย forward price) ──
            "action": dr.get("action"), "decision": dr.get("decision"),
            "direction": direction, "entry_type": dr.get("entry_type") or cd.get("entry_type"),
            "reason": (dr.get("reason") or "")[:200], "price": px,
            "sl_pips": (plan.get("sell_sl_pips") if direction == "SELL" else plan.get("buy_sl_pips")) or cd.get("sl_pips"),
            "tp_pips": plan.get("tp_pips") or cd.get("tp_pips"),
            # ── features F1..F7 (design §2) ──
            "f1_news_score": news["score"], "f1_news_n": news["n"], "f2_news_updated": news["updated"],
            "f3_reversal": cd.get("reversal_confirm") or (cd.get("signals") or {}).get("reversal_confirm"),
            "f4_mom_m15": (mom.get("m15") or {}).get("direction"),
            "f4_mom_m15_str": (mom.get("m15") or {}).get("strength"),
            "f4_mom_h1": (mom.get("h1") or {}).get("direction"),
            "f5_zone": _nearest_zone(cd, px, direction),
            "f6_fast_move": cd.get("fast_move_pips"),
            "f7_vol_tilt": (cd.get("volume_profile") or {}).get("tilt"),
            "f8_risk_regime": _risk_regime(),   # cross-asset HMM regime (add-only, validate ก่อน wire จริง)
            # ── context ──
            "sr_zone": cd.get("sr_zone"), "sr_strength": cd.get("sr_strength"),
            "trend": cd.get("trend"), "d1_trend": cd.get("d1_trend"), "conf": cd.get("confidence"),
            "sentiment": (sentiment_data or {}).get("sentiment"),
            "sent_conf": (sentiment_data or {}).get("confidence"),
        }
        _SNAP.parent.mkdir(parents=True, exist_ok=True)
        with _SNAP.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[SNAPSHOT] fail-soft: {e}")
