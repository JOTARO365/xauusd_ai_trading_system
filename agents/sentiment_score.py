"""agents/sentiment_score.py — LLM sentiment score (−100..+100) for gold, cached.

The algo entry path is pure price/momentum and does not read sentiment, so it can
keep selling into news that argues the other way. This module has an LLM read the
current *gold-specific* picture (macro-regime note + recent news + calendar) and
distil it to ONE number: −100 = strongly bearish for gold, +100 = strongly bullish,
0 = neutral/unclear. `agents/sentiment_bias` turns that number into a soft directional
bias on entries (counter-sentiment trades need a stronger break + smaller lot).

Design guards:
- Gold reaction is regime-dependent (the same headline is bullish in one phase, bearish
  in another) — the prompt asks for gold's *actual* expected reaction, not a naive
  "tension = up" mapping, and leans on macro_regime.md for the current phase.
- Cached to data/sentiment_score.json with a TTL (SENTIMENT_REFRESH_MIN) so it is at
  most one LLM call per window, never per cycle/tick.
- Fail-soft: any error → score 0 (neutral) so a down LLM never blocks or skews trading.

Import-safe (LLM client built lazily). Read via get_score(); flag = config.SENTIMENT_BIAS.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

_BASE = Path(__file__).resolve().parent.parent
_CACHE = _BASE / "data" / "sentiment_score.json"
_llm = None                       # lazy — สร้างตอนใช้ครั้งแรก (import-safe เมื่อไม่มี API key)


def _schema():
    from pydantic import BaseModel, Field

    class SentimentScore(BaseModel):
        score: int = Field(description="Gold sentiment now: -100 = strongly bearish for XAUUSD, "
                                       "+100 = strongly bullish, 0 = neutral/unclear. Reflect gold's "
                                       "ACTUAL expected reaction for the current macro phase, not a naive "
                                       "risk-on/off mapping.")
        reason: str = Field(description="เหตุผลสั้นหนึ่งบรรทัด (ภาษาไทย) ว่าทำไมได้คะแนนนี้")
    return SentimentScore


def _get_llm():
    global _llm
    if _llm is None:
        import config as _cfg
        from langchain_anthropic import ChatAnthropic
        from config import ANTHROPIC_API_KEY
        _llm = ChatAnthropic(
            model=getattr(_cfg, "SENTIMENT_MODEL", "claude-sonnet-4-6"),
            api_key=ANTHROPIC_API_KEY, max_tokens=400, temperature=0,
            timeout=45, max_retries=2,
        ).with_structured_output(_schema(), include_raw=True)
    return _llm


def _read_cache():
    try:
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(d):
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _regime_age_days():
    """อายุ (วัน) ของ macro_regime.md จากบรรทัด 'UPDATED: YYYY-MM-DD' ล่าสุด — บอก LLM ว่า background เก่าแค่ไหน."""
    try:
        import re
        from datetime import date
        txt = (_BASE / "agents" / "prompts" / "macro_regime.md").read_text(encoding="utf-8")
        ms = re.findall(r"UPDATED:\s*(\d{4})-(\d{2})-(\d{2})", txt)
        if ms:
            y, m, d = map(int, ms[-1])
            return (date.today() - date(y, m, d)).days
    except Exception:
        pass
    return None


def _context():
    """บริบทให้ LLM. ลำดับความสำคัญ: ข่าว/เหตุการณ์**สด** (worldmonitor/news_impact/calendar) = PRIMARY —
    macro_regime.md = background ที่ **อาจล้าสมัย** (อัปเดตมือ) ใช้แค่ธีมโครงสร้างช้าๆ ห้าม cap สัญญาณสดที่แรง."""
    parts = []
    # 1) ข่าว/เหตุการณ์สด = PRIMARY (bot อัปเดตไฟล์พวกนี้ทุก cycle)
    for fn, label in (("worldmonitor.json", "WORLD MONITOR (สด)"),
                      ("news_impact.json", "NEWS IMPACT (สด)"),
                      ("ff_calendar_raw.json", "ECON CALENDAR (สด)")):
        try:
            with open(_BASE / "data" / fn, encoding="utf-8") as f:
                raw = json.load(f)
            txt = json.dumps(raw, ensure_ascii=False)[:1500]
            parts.append(f"=== {label} — PRIMARY, weight มากสุด ===\n{txt}")
        except Exception:
            pass
    # 1.5) ตัวเลขเศรษฐกิจ**จริงที่ log ไว้** (release actuals + DXY/yields/real-yield + COT) = ประเมินทิศจากเลข ไม่ใช่กราฟ
    for fn, label in (("macro_actuals.json", "ECON ACTUALS — release จริง (CPI/NFP/unemp/Fed/retail)"),
                      ("macro_strip.json", "MACRO STRIP — DXY / 10Y / real-yield"),
                      ("cot.json", "COT — positioning")):
        try:
            with open(_BASE / "data" / fn, encoding="utf-8") as f:
                raw = json.load(f)
            txt = json.dumps(raw, ensure_ascii=False)[:900]
            parts.append(f"=== {label} — PRIMARY (ตัวเลขจริง) ===\n{txt}")
        except Exception:
            pass
    # 2) macro_regime.md = background (แจ้งอายุ; อาจ lag → ห้ามใช้ cap สัญญาณสด)
    try:
        from agents.analyst import _regime_context
        rc = _regime_context()
        if rc:
            age = _regime_age_days()
            age_txt = f" (อัปเดตมือเมื่อ ~{age} วันก่อน — อาจล้าสมัย)" if age is not None else ""
            parts.append(f"=== MACRO REGIME BACKGROUND{age_txt} — SECONDARY: ใช้เฉพาะธีมโครงสร้างช้าๆ "
                         f"ถ้าข่าวสดขัดกับไฟล์นี้ ให้เชื่อข่าวสด ห้ามลดคะแนนเพราะไฟล์นี้บอก 'modest' ===\n" + rc.strip())
    except Exception:
        pass
    return "\n\n".join(parts) if parts else "(ไม่มีบริบทข่าว/regime — ให้ตอบ 0 neutral)"


def _compute():
    from langchain_core.messages import SystemMessage, HumanMessage
    sys_msg = ("You are a gold (XAUUSD) macro strategist. Read the context and output ONE integer "
               "from -100 (strongly bearish for gold) to +100 (strongly bullish), plus a one-line Thai "
               "reason. WEIGHT THE FRESH NEWS/EVENTS (marked PRIMARY) MOST — they reflect what is driving "
               "gold RIGHT NOW. The MACRO REGIME BACKGROUND is a hand-updated note that may be weeks stale; "
               "use it only for slow structural themes and NEVER let it cap a strong fresh signal. Judge "
               "gold's ACTUAL expected direction; the same headline can be bullish or bearish by regime. "
               "Reason from the ACTUAL ECONOMIC NUMBERS provided (real yield, CPI, NFP, unemployment, DXY, "
               "10Y, COT positioning) — not just news vibes: e.g. positive/rising real yield + strong jobs = "
               "gold headwind; falling real yield + weak jobs + soft CPI = tailwind. Weigh news + these numbers "
               "TOGETHER. When today's drivers are strong and one-sided, use a strong number (±60..±90) — do not "
               "default to a timid mid value. Only stay near 0 if the fresh signals are genuinely mixed/weak.")
    ctx = _context()
    raw = _get_llm().invoke([SystemMessage(content=sys_msg),
                             HumanMessage(content=f"บริบทปัจจุบัน:\n{ctx}\n\nให้คะแนน sentiment ทองตอนนี้")])
    parsed = raw.get("parsed")
    if parsed is None:
        raise ValueError("structured parse returned None")
    score = max(-100, min(100, int(parsed.score)))
    usage = (getattr(raw.get("raw"), "response_metadata", None) or {}).get("usage", {})
    out = {"ok": True, "score": score, "reason": (parsed.reason or "").strip(),
           "asof": datetime.now(timezone.utc).isoformat()[:16] + "Z",
           "ts": time.time(), "model": getattr(__import__("config"), "SENTIMENT_MODEL", "?"),
           "tokens_in": usage.get("input_tokens"), "tokens_out": usage.get("output_tokens")}
    _write_cache(out)
    logger.info(f"[sentiment] score={score} · {out['reason']} (in={out['tokens_in']} out={out['tokens_out']})")
    return out


def get_score(force=False):
    """คืน {ok, score −100..+100, reason, asof, ...}. cache TTL = SENTIMENT_REFRESH_MIN นาที.
    fail-soft → score 0 (neutral). ไม่ยิง LLM ถ้า cache สด."""
    import config as _cfg
    ttl = float(getattr(_cfg, "SENTIMENT_REFRESH_MIN", 30)) * 60
    cache = _read_cache()
    if not force and cache and (time.time() - float(cache.get("ts", 0))) < ttl:
        return cache
    try:
        return _compute()
    except Exception as e:
        logger.warning(f"[sentiment] compute fail ({type(e).__name__}: {e}) — คืน cache/neutral")
        return cache or {"ok": False, "score": 0, "reason": "ยังไม่มีข้อมูล sentiment",
                         "asof": None, "ts": 0}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(get_score(force=True))
