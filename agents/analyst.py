import anthropic
from datetime import datetime, timezone
from pathlib import Path
from config import ANTHROPIC_API_KEY
from loguru import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = Path("agents/prompts/analyst.md").read_text(encoding="utf-8")

_last_usage = None   # set after each API call — read by accountant


def analyze_sentiment(news_data: dict) -> dict:
    logger.info("Agent 3 (ผู้วิเคราะห์): กำลังวิเคราะห์ sentiment...")

    tweets   = news_data.get("tweets",       [])
    calendar = news_data.get("calendar",     [])
    articles = news_data.get("web_articles", [])

    has_any = tweets or calendar or articles
    if not has_any:
        logger.warning("ไม่มีข้อมูลข่าวเลย")
        return {"sentiment": "NEUTRAL", "confidence": 0, "summary": "ไม่มีข้อมูลข่าว"}

    # ── Twitter/X ─────────────────────────────────────────────
    tweet_section = ""
    if tweets:
        tweet_texts   = "\n".join(f"- @{t['user']}: {t['text'][:200]}" for t in tweets[:20])
        tweet_section = f"=== Twitter/X ({len(tweets)} tweets) ===\n{tweet_texts}"
    else:
        tweet_section = "=== Twitter/X ===\nไม่มี tweet"

    # ── ForexFactory Economic Calendar ────────────────────────
    if calendar:
        cal_lines = "\n".join(
            f"  [{ev['time']}] {ev['currency']} — {ev['title']} | "
            f"Forecast: {ev['forecast']} | Prev: {ev['previous']} | Actual: {ev['actual']}"
            for ev in calendar
        )
        cal_section = f"=== ForexFactory Calendar (high-impact, next 24h) ===\n{cal_lines}"
    else:
        cal_section = "=== ForexFactory Calendar ===\nไม่มี high-impact event ใน 24h"

    # ── Investing.com Headlines ────────────────────────────────
    if articles:
        art_lines = "\n".join(
            f"  [{a['pub']}] {a['title']} — {a['summary']}"
            for a in articles
        )
        art_section = f"=== Investing.com Headlines ===\n{art_lines}"
    else:
        art_section = "=== Investing.com Headlines ===\nไม่มีข่าว"

    user_message = f"""วิเคราะห์ sentiment จากข้อมูลต่อไปนี้และตอบในรูปแบบที่กำหนด:

{tweet_section}

{cal_section}

{art_section}

หมายเหตุ: ให้น้ำหนัก ForexFactory calendar สูงสุด (เป็น hard data) รองลงมาคือ Investing.com แล้วค่อย Twitter/X"""

    global _last_usage
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    _last_usage = response.usage

    analysis_text = response.content[0].text
    logger.info(f"Sentiment Analysis:\n{analysis_text}")

    result = {
        "raw":        analysis_text,
        "sentiment":  "NEUTRAL",
        "confidence": 0,
        "summary":    "",
        "bias":       "NEUTRAL",
        "tweet_count": len(tweets),
    }

    for line in analysis_text.splitlines():
        if line.startswith("SENTIMENT:"):
            result["sentiment"] = line.split(":", 1)[1].strip()
        elif line.startswith("CONFIDENCE:"):
            try:
                raw_conf = line.split(":", 1)[1].strip().replace("%", "").strip()
                result["confidence"] = int(raw_conf)
            except Exception:
                pass
        elif line.startswith("SUMMARY:"):
            result["summary"] = line.split(":", 1)[1].strip()
        elif line.startswith("BIAS:"):
            result["bias"] = line.split(":", 1)[1].strip()

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
