import anthropic
from pathlib import Path
from config import ANTHROPIC_API_KEY
from agents.reporter import get_trade_history_summary
from loguru import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
SYSTEM_PROMPT = Path("agents/prompts/market_advisor.md").read_text(encoding="utf-8")

_last_usage = None   # set after each API call — read by accountant


def analyze_market_regime(chart_data: dict) -> dict:
    logger.info("Agent 2.5 (Market Advisor): กำลังวิเคราะห์ market regime...")

    ind    = chart_data.get("indicators", {})
    h4     = ind.get("h4", {})
    h1     = ind.get("h1", {})
    m15    = ind.get("m15", {})
    h4_sr  = chart_data.get("sr_zones", {})

    price     = h4.get("close", 0)
    ema20_h4  = h4.get("ema20", 0)
    ema50_h4  = h4.get("ema50", 0)
    ema200_h4 = h4.get("ema200", 0)
    atr_h4    = h4.get("atr", 0)
    ema20_h1  = h1.get("ema20", 0)
    ema20_m15 = m15.get("ema20", 0)

    res_levels = h4_sr.get("resistance", [])
    sup_levels = h4_sr.get("support", [])

    history = get_trade_history_summary()
    entry_perf = history.get("entry_perf_text", "  No data yet")

    user_message = f"""วิเคราะห์ market regime สำหรับ XAUUSD จากข้อมูลต่อไปนี้:

=== Current Price ===
Price: {price:.2f}

=== EMA Structure (H4) ===
EMA20:  {ema20_h4:.2f}  | Price vs EMA20: {"ABOVE" if price > ema20_h4 else "BELOW"}
EMA50:  {ema50_h4:.2f}  | EMA20 vs EMA50: {"ABOVE" if ema20_h4 > ema50_h4 else "BELOW"}
EMA200: {ema200_h4:.2f} | EMA20 vs EMA200: {"ABOVE" if ema20_h4 > ema200_h4 else "BELOW"}
ATR:    {atr_h4:.2f}

=== EMA Structure (H1 + M15) ===
H1  EMA20: {ema20_h1:.2f}  | Price: {"ABOVE" if price > ema20_h1 else "BELOW"}
M15 EMA20: {ema20_m15:.2f} | Price: {"ABOVE" if price > ema20_m15 else "BELOW"}

=== S/R Zones (H4) ===
Resistance: {", ".join(f"{r:.2f}" for r in res_levels[:4]) or "—"}
Support:    {", ".join(f"{s:.2f}" for s in sup_levels[:4]) or "—"}

=== Price Action Signal (Agent 1) ===
Signal:     {chart_data.get("signal", "NO_TRADE")}
Confidence: {chart_data.get("confidence", 0)}%
Trend:      {chart_data.get("trend", "—")}
SR Zone:    {chart_data.get("sr_zone", "—")} / {chart_data.get("sr_strength", "—")}
Entry Type: {chart_data.get("entry_type", "—")}

=== Historical Entry Performance (from real trades) ===
{entry_perf}
Reply in the exact output format only. No extra text."""

    global _last_usage
    _last_usage = None
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=700,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )
        _last_usage = response.usage
        text = response.content[0].text
        logger.info(f"Market Advisor:\n{text}")
        return _parse_response(text)
    except Exception as e:
        logger.error(f"Market Advisor error: {e}")
        return _default()


def _parse_response(text: str) -> dict:
    result = _default()
    result["raw"] = text

    section = None
    section_data: dict[str, list] = {
        "INTRADAY_STRUCTURE": [],
        "REGIME_NOTE":        [],
        "ADVISOR_NOTE":       [],
    }
    SECTION_KEYS = set(section_data.keys())

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue

        header = s.rstrip(":")
        if header in SECTION_KEYS and s.endswith(":"):
            section = header
            continue

        if s.startswith("REGIME:") and "CONFIDENCE" not in s and "NOTE" not in s:
            result["regime"] = s.split(":", 1)[1].strip()
            section = None
        elif s.startswith("REGIME_CONFIDENCE:"):
            try:
                result["regime_confidence"] = int(s.split(":", 1)[1].strip().replace("%", ""))
            except Exception:
                pass
            section = None
        elif s.startswith("BIAS:"):
            result["bias"] = s.split(":", 1)[1].strip()
            section = None
        elif s.startswith("VOLATILITY:"):
            result["volatility"] = s.split(":", 1)[1].strip()
            section = None
        elif s.startswith("TP_STYLE:"):
            result["tp_style"] = s.split(":", 1)[1].strip()
            section = None
        elif s.startswith("TOP_SETUP:"):
            result["top_setup"] = s.split(":", 1)[1].strip()
            section = None
        elif s.startswith("BEST_INDICATORS:"):
            result["best_indicators"] = [x.strip() for x in s.split(":", 1)[1].split(",") if x.strip()]
            section = None
        elif section and s.startswith("- "):
            section_data[section].append(s[2:])

    for item in section_data["INTRADAY_STRUCTURE"]:
        if item.startswith("H4:"):
            result["intraday_h4"] = item.split(":", 1)[1].strip()
        elif item.startswith("H1:"):
            result["intraday_h1"] = item.split(":", 1)[1].strip()
        elif item.startswith("M15:"):
            result["intraday_m15"] = item.split(":", 1)[1].strip()

    result["regime_note"]  = " ".join(section_data["REGIME_NOTE"])
    result["advisor_note"] = " ".join(section_data["ADVISOR_NOTE"])
    return result


def _default() -> dict:
    return {
        "regime":            "SIDEWAYS",
        "regime_confidence": 0,
        "bias":              "NEUTRAL",
        "volatility":        "NORMAL",
        "tp_style":          "NORMAL",
        "top_setup":         "NO_DATA",
        "best_indicators":   [],
        "intraday_h4":       "—",
        "intraday_h1":       "—",
        "intraday_m15":      "—",
        "regime_note":       "",
        "advisor_note":      "",
        "raw":               "",
    }
