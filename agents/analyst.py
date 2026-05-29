import json
from datetime import datetime, timezone
from pathlib import Path
from langchain_anthropic import ChatAnthropic
from config import ANTHROPIC_API_KEY
from agents.news_cache import get_news_context
from agents.schemas import AnalystOutput
from loguru import logger

_llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=ANTHROPIC_API_KEY,
    max_tokens=300,
    temperature=0,
).with_structured_output(AnalystOutput)

SYSTEM_PROMPT = json.dumps(
    json.loads(Path("agents/prompts/analyst.json").read_text(encoding="utf-8")),
    separators=(",", ":"),
)

_last_usage = None   # set after each API call — read by accountant


def _build_market_context(chart_data: dict) -> str:
    """สร้าง query string สำหรับ vector search จาก chart context"""
    signal = chart_data.get("signal", "")
    trend  = chart_data.get("trend", "")
    zone   = chart_data.get("sr_zone", "")
    conf   = chart_data.get("confidence", 0)
    return f"{signal} signal {trend} trend {zone} zone confidence {conf}%"


def analyze_sentiment(news_data: dict, chart_data: dict | None = None) -> dict:
    logger.info("Agent 3 (ผู้วิเคราะห์): กำลังวิเคราะห์ sentiment...")

    tweets   = news_data.get("tweets",       [])
    calendar = news_data.get("calendar",     [])
    articles = news_data.get("web_articles", [])

    has_any = tweets or calendar or articles
    if not has_any:
        logger.warning("ไม่มีข้อมูลข่าวเลย")
        return {"sentiment": "NEUTRAL", "confidence": 0, "summary": "ไม่มีข้อมูลข่าว"}

    # ── News Cache: Haiku summary + vector search ──────────────
    market_ctx   = _build_market_context(chart_data) if chart_data else ""
    news_context = get_news_context(news_data, market_context=market_ctx)

    summary       = news_context["summary"]
    relevant      = news_context["relevant_items"]
    from_cache    = news_context["from_cache"]
    token_est     = news_context["token_estimate"]

    logger.info(
        f"News context: {'cache HIT' if from_cache else 'cache MISS'} | "
        f"~{token_est} tokens | {len(relevant)} relevant items"
    )

    # ── ForexFactory Calendar — ยังส่งตรงเพราะเป็น hard data (สั้น) ──
    if calendar:
        cal_lines = "\n".join(
            f"  [{ev['time']}] {ev['currency']} — {ev['title']} | "
            f"Forecast: {ev.get('forecast','?')} | Actual: {ev.get('actual','pending')}"
            for ev in calendar[:8]
        )
        cal_section = f"=== ForexFactory Calendar ===\n{cal_lines}"
    else:
        cal_section = "=== ForexFactory Calendar ===\nไม่มี high-impact event ใน 24h"

    # ── Relevant items จาก vector search ─────────────────────
    relevant_section = ""
    if relevant:
        relevant_section = "\n=== Most Relevant News (vector search) ===\n" + \
            "\n".join(f"  - {r[:200]}" for r in relevant)

    user_message = f"""วิเคราะห์ sentiment XAUUSD จากข้อมูลต่อไปนี้:

=== News Summary (AI-compressed) ===
{summary}
{relevant_section}

{cal_section}

หมายเหตุ: ให้น้ำหนัก ForexFactory calendar สูงสุด (hard data) → News Summary → Relevant items"""

    global _last_usage
    _last_usage = None
    messages = [
        {"role": "system", "content": [
            {"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}
        ]},
        {"role": "user", "content": user_message},
    ]
    try:
        parsed: AnalystOutput = _llm.invoke(messages)
        logger.info(f"Sentiment Analysis: {parsed.sentiment} ({parsed.confidence}%)")
        result = {
            "sentiment":   parsed.sentiment,
            "confidence":  parsed.confidence,
            "summary":     parsed.summary,
            "bias":        parsed.bias,
            "tweet_count": len(tweets),
        }
    except Exception as e:
        logger.error(f"Analyst structured output failed: {e} — defaulting NEUTRAL")
        result = {"sentiment": "NEUTRAL", "confidence": 0, "summary": "", "bias": "NEUTRAL", "tweet_count": len(tweets)}

    # ── คำนวณ event ที่ยังไม่เกิด (actual = pending) ────────────
    now = datetime.now(timezone.utc)
    pending_events = []
    nearest_minutes = 9999
    for ev in calendar:
        if str(ev.get("actual", "")).lower() not in ("pending", "—", ""):
            continue   # event ผ่านไปแล้ว (มี actual)
        ts = ev.get("timestamp_iso", "")
        if not ts:
            continue
        try:
            event_dt = datetime.fromisoformat(ts)
            mins = int((event_dt - now).total_seconds() / 60)
            if mins < 0:
                continue   # ผ่านไปแล้ว
            pending_events.append({**ev, "minutes_ahead": mins})
            nearest_minutes = min(nearest_minutes, mins)
        except Exception:
            pass

    result["upcoming_events"]       = pending_events[:5]
    result["has_upcoming_event"]    = len(pending_events) > 0
    result["nearest_event_minutes"] = nearest_minutes if pending_events else 9999

    if pending_events:
        logger.info(
            f"Upcoming high-impact event in {nearest_minutes}min: "
            f"{pending_events[0]['currency']} {pending_events[0]['title']}"
        )

    return result
