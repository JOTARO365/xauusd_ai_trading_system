"""
Lesson Learner — RAG-based Lesson Retrieval (v2)
วิเคราะห์ trade ที่ hit SL ด้วย Haiku → extract mistake_type + pattern
→ store พร้อม direction/trend/market_regime สำหรับ hybrid search
"""
import os
import json
from loguru import logger
import anthropic

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You are a trading mistake analyzer. Given a closed trade that hit Stop Loss, identify:
1. PRIMARY mistake type — MUST be exactly ONE of:
   COUNTER_TREND, NO_SR_ZONE, OVERCONFIDENCE, LOW_CONFIDENCE_ENTRY,
   NEWS_TIMING, WIDE_SL, PENDING_WRONG_LEVEL, OTHER
2. SHORT pattern (max 110 chars) — explain WHY this specific trade lost.
   Be specific: include direction, trend, key condition that caused the loss.
   Future Claude will read this to avoid the same mistake.

Respond in JSON only — no markdown, no extra text:
{"mistake_type": "...", "pattern": "..."}"""


def learn_from_loss(trade: dict) -> bool:
    """
    วิเคราะห์ trade ที่ hit SL แล้วบันทึก lesson
    Returns True ถ้าบันทึกสำเร็จ
    """
    if os.getenv("LESSON_LEARNING", "true").lower() == "false":
        return False
    if (trade.get("pnl") or 0) >= 0:
        return False
    if trade.get("source") == "MANUAL":
        return False

    trade_summary = _build_trade_summary(trade)
    raw = ""

    try:
        resp = _client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=150,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Analyze this losing trade:\n{trade_summary}"}],
        )
        raw = resp.content[0].text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())

        mistake_type = result.get("mistake_type", "OTHER")
        pattern      = result.get("pattern", "")

        if not pattern:
            logger.warning("lesson_learner: Haiku returned empty pattern")
            return False

        # ── context ครบ — ใช้ใน hybrid search pre-filter ──────────────────
        context = {
            "direction":     trade.get("direction", ""),
            "trend":         trade.get("trend", ""),
            "market_regime": _infer_regime(trade),
            "sr_zone":       trade.get("sr_zone"),
            "sr_strength":   trade.get("sr_strength"),
            "confidence":    trade.get("technical_confidence"),
            "entry_type":    trade.get("entry_type"),
            "pa_action":     trade.get("pa_action"),
            "pnl":           trade.get("pnl"),
            "ticket":        trade.get("ticket"),
        }

        from db.lesson_store import store_lesson
        return store_lesson(mistake_type, pattern, context)

    except json.JSONDecodeError as e:
        logger.warning(f"lesson_learner: JSON parse error: {e} | raw={raw[:100]}")
        return False
    except Exception as e:
        logger.warning(f"lesson_learner: error: {e}")
        return False


def _infer_regime(trade: dict) -> str:
    """สรุป market regime จาก trade context"""
    trend = (trade.get("trend") or "").upper()
    sr    = (trade.get("sr_zone") or "NONE").upper()
    if trend in ("BULLISH", "BEARISH"):
        return "TRENDING"
    if trend == "SIDEWAYS" or sr != "NONE":
        return "RANGING"
    return ""


def _build_trade_summary(trade: dict) -> str:
    return (
        f"Direction: {trade.get('direction')}\n"
        f"Entry type: {trade.get('entry_type')}\n"
        f"Trend (H4): {trade.get('trend')}\n"
        f"SR Zone: {trade.get('sr_zone')} ({trade.get('sr_strength')})\n"
        f"Confidence: {trade.get('technical_confidence')}%\n"
        f"PA Action: {trade.get('pa_action')} @ {trade.get('pa_level')}\n"
        f"PA Patterns: {trade.get('pa_patterns')}\n"
        f"Sentiment: {trade.get('sentiment')}\n"
        f"P&L: {trade.get('pnl')}\n"
        f"Analysis: {str(trade.get('analysis',''))[:300]}"
    )
