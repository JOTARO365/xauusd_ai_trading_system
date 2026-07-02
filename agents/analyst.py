import json
from datetime import datetime, timezone
from pathlib import Path
from langchain_anthropic import ChatAnthropic
import config as _cfg
from config import ANTHROPIC_API_KEY
from agents.news_cache import get_news_context
from agents.schemas import AnalystOutput
from loguru import logger

_llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=ANTHROPIC_API_KEY,
    max_tokens=300,
    temperature=0,
).with_structured_output(AnalystOutput, include_raw=True)

SYSTEM_PROMPT = json.dumps(
    json.loads(Path("agents/prompts/analyst.json").read_text(encoding="utf-8")),
    separators=(",", ":"),
)

_REGIME_PATH = Path("agents/prompts/macro_regime.md")


def _regime_context() -> str:
    """Current-phase macro regime note (editable; fed by youtube-to-knowhow).

    Fundamentals are regime-dependent — the same event maps to gold differently
    across economic phases (e.g. hot inflation is bullish when the Fed is easing
    but bearish when it's fighting inflation). This file lets the analyst's
    factor interpretation change over time WITHOUT touching the cached system
    prompt. Only the text below the REGIME_START marker is used; an empty body
    (or a missing file) means the analyst falls back to the default gold_factors.
    """
    try:
        txt = _REGIME_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
    marker = "<!-- REGIME_START -->"
    if marker in txt:
        txt = txt.split(marker, 1)[1]
    # drop tooling marker lines (e.g. MACRO_AUTO_START/END) so they don't add noise
    lines = [ln for ln in txt.splitlines() if not ln.lstrip().startswith("<!--")]
    return "\n".join(lines).strip()


_last_usage = None   # set after each API call — read by accountant

# ── Event-reaction priors (Tier-1, 2026-07-02) ────────────────────────────────
# สถิติจริงจาก scripts/event_reaction_stats.py (daily gold 15 ปี) — ฉีด 1-2 บรรทัด
# เข้า calendar context เฉพาะวันที่มี event ที่เรามีสถิติ (ตอนนี้: NFP)
_EVENT_STATS_PATH = Path("data/event_stats.json")
_EVENT_TITLE_KEYS = {"NFP": ("non-farm", "nonfarm", "non farm")}


def _event_prior_lines(calendar: list) -> str:
    """คืนบรรทัด prior เชิงสถิติของ event ใน calendar ที่มีใน data/event_stats.json
    fail-open: ไฟล์ไม่มี/พัง → คืน "" (analyst ทำงานเหมือนเดิม)"""
    try:
        stats = json.loads(_EVENT_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    events = stats.get("events", {})
    seen: set[str] = set()
    lines: list[str] = []
    for ev in calendar:
        title = str(ev.get("title", "")).lower()
        for key, needles in _EVENT_TITLE_KEYS.items():
            if key in seen or key not in events:
                continue
            if any(n in title for n in needles):
                s = events[key]
                lines.append(
                    f"  {key} prior (n={s['n']} releases, daily-close 15y): "
                    f"วันประกาศ up {s['up_pct']}% / down {s['down_pct']}% / flat {s['flat_pct']}% "
                    f"(ทิศ ~ เหรียญ — direction มาจาก 'ตัวเลข vs consensus' ไม่ใช่ตัว event) | "
                    f"avg |move| {s['avg_abs_d0_pct']}% = {s.get('vs_baseline_x', '?')}x วันปกติ | "
                    f"D+2 ไปต่อทิศเดิมแค่ {s['d2_extends_pct']}% (อย่า assume follow-through)"
                )
                seen.add(key)
    return "\n".join(lines)


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
    # ราคาวิ่งแรง (≥ counter-spike threshold) = ข่าวใหม่น่าจะเป็นตัวขับราคา
    # → force summary สด ห้าม reuse cache (sentiment ต้องตามเหตุการณ์ทัน)
    _fast  = abs(float((chart_data or {}).get("fast_move_pips", 0) or 0))
    _force = _fast >= float(getattr(_cfg, "COUNTER_SPIKE_PIPS", 500) or 500)
    news_context = get_news_context(news_data, market_context=market_ctx, force_fresh=_force)

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
        _priors = _event_prior_lines(calendar)
        if _priors:
            cal_section += f"\n=== Event Priors (สถิติจริงจากราคา 15 ปี) ===\n{_priors}"
    else:
        cal_section = "=== ForexFactory Calendar ===\nไม่มี high-impact event ใน 24h"

    # ── Relevant items จาก vector search ─────────────────────
    relevant_section = ""
    if relevant:
        relevant_section = "\n=== Most Relevant News (vector search) ===\n" + \
            "\n".join(f"  - {r[:200]}" for r in relevant)

    # ── Current macro regime — conditions fundamental mapping for this phase ──
    regime = _regime_context()
    regime_section = (
        "=== CURRENT MACRO REGIME (authoritative for current phase) ===\n"
        f"{regime}\n"
        "↑ ใช้บริบทนี้กำหนดทิศของปัจจัยพื้นฐานในช่วงนี้ — ถ้าขัดกับ default ให้ยึด regime นี้\n\n"
        if regime else ""
    )

    user_message = f"""วิเคราะห์ sentiment XAUUSD จากข้อมูลต่อไปนี้:

{regime_section}=== News Summary (AI-compressed) ===
{summary}
{relevant_section}

{cal_section}

หมายเหตุ: ให้น้ำหนัก CURRENT MACRO REGIME (ถ้ามี) → ForexFactory calendar (hard data) → News Summary → Relevant items"""

    global _last_usage
    _last_usage = None
    # NB: ห้ามใส่ cache_control ที่นี่ — cycle interval ยาวกว่า TTL 5 นาทีของ ephemeral cache
    # ข้อมูลจริง 205 calls: cache_read = 0 ทุกครั้ง = จ่ายค่า write premium (1.25x) ฟรี
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    try:
        raw_out = _llm.invoke(messages)
        _raw    = raw_out.get("raw")
        _last_usage = (getattr(_raw, "response_metadata", None) or {}).get("usage")
        parsed: AnalystOutput = raw_out.get("parsed")
        if parsed is None:
            raise ValueError(raw_out.get("parsing_error") or "structured parse returned None")
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
