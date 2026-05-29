import json
from pathlib import Path
from langchain_anthropic import ChatAnthropic
from config import ANTHROPIC_API_KEY
from agents.reporter import get_trade_history_summary
from agents.schemas import MarketAdvisorOutput
from loguru import logger

_llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=ANTHROPIC_API_KEY,
    max_tokens=450,
    temperature=0,
).with_structured_output(MarketAdvisorOutput)

SYSTEM_PROMPT = json.dumps(
    json.loads(Path("agents/prompts/market_advisor.json").read_text(encoding="utf-8")),
    separators=(",", ":"),
)

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

    history    = get_trade_history_summary()
    entry_perf = history.get("entry_perf_text", "  No data yet")

    user_message = f"""XAUUSD market regime analysis:

Price:{price:.2f} EMA20_H4:{ema20_h4:.2f} EMA50_H4:{ema50_h4:.2f} EMA200_H4:{ema200_h4:.2f} ATR_H4:{atr_h4:.2f}
H1_EMA20:{ema20_h1:.2f} M15_EMA20:{ema20_m15:.2f}
Resistance:{",".join(f"{r:.2f}" for r in res_levels[:4]) or "none"}
Support:{",".join(f"{s:.2f}" for s in sup_levels[:4]) or "none"}
Signal:{chart_data.get("signal","NO_TRADE")} Conf:{chart_data.get("confidence",0)}% Trend:{chart_data.get("trend","—")} SR:{chart_data.get("sr_zone","—")}/{chart_data.get("sr_strength","—")} Entry:{chart_data.get("entry_type","—")}
Historical performance:
{entry_perf}"""

    global _last_usage
    _last_usage = None
    try:
        messages = [
            {"role": "system", "content": [
                {"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}
            ]},
            {"role": "user", "content": user_message},
        ]
        result: MarketAdvisorOutput = _llm.invoke(messages)
        logger.info(f"Market Advisor: {result.regime} ({result.regime_confidence}%) Bias:{result.bias}")
        return {
            "regime":            result.regime,
            "regime_confidence": result.regime_confidence,
            "bias":              result.bias,
            "volatility":        result.volatility,
            "tp_style":          result.tp_style,
            "top_setup":         result.top_setup,
            "best_indicators":   result.best_indicators,
            "intraday_h4":       result.intraday_structure.h4,
            "intraday_h1":       result.intraday_structure.h1,
            "intraday_m15":      result.intraday_structure.m15,
            "advisor_note":      result.advisor_note,
        }
    except Exception as e:
        logger.error(f"Market Advisor error: {e}")
        return _default()


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
        "advisor_note":      "",
    }
