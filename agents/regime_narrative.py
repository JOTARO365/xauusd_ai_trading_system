"""agents/regime_narrative.py — daily-morning LLM refresh of the macro_regime.md NARRATIVE.

The narrative lines of agents/prompts/macro_regime.md (PHASE / DRIVERS / FILTER /
CATALYSTS / UPDATED) are the *authoritative* macro context fed to the analyst and to
the sentiment score. Hand-maintained they went stale, so an LLM rewrites them every
MORNING from the same fresh context weekly_outlook gathers (ForexFactory calendar +
event scenarios + news sentiment + COT + macro data + world monitor) — keeping the
background stance current so the sentiment score is accurate day to day.

Two modes (so it tracks, not just recaps):
- **Monday** → set the week's BASELINE phase + the catalysts ahead.
- **Tue–Sun** → UPDATE the standing phase with what has developed SINCE Monday (new data
  prints, geopolitics, news) — track the current situation, never recap the past week.

Guardrails (this file feeds LIVE gold entries):
- Once per day, only at/after REGIME_NARRATIVE_HOUR local (a real morning summary).
- Kill switch: config.REGIME_NARRATIVE_AUTO (default OFF).
- Writes ONLY the narrative zone — the MACRO_AUTO_START..END block (owned by
  scripts/update_regime.py) and the header comments are preserved verbatim.
- Backs up the previous file to <macro_regime>.bak and logs the swap before writing.
- Fail-soft: any error → leave the file untouched.

Trigger: regime_narrative.tick() from node_position_mgmt (fail-soft, self-dedups by day).
"""
import json
import os
import shutil
from datetime import datetime, timezone

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REGIME = os.path.join(_BASE, "agents", "prompts", "macro_regime.md")
_STATE = os.path.join(_BASE, "data", "regime_narrative_state.json")
_START = "<!-- REGIME_START -->"
_AUTO_START = "<!-- MACRO_AUTO_START"
_AUTO_END = "<!-- MACRO_AUTO_END -->"

_SYSTEM = """You maintain the authoritative macro-regime note for a gold (XAUUSD) trading bot.
Rewrite ONLY the narrative from the CURRENT real data provided. Output PLAIN TEXT in ENGLISH in
exactly this shape (these lines are read as factor directions by the bot):

PHASE: <one paragraph — the dominant macro phase for gold now (Fed stance, real rates, inflation
  path, geopolitics) and whether the tilt is bullish/bearish/two-sided, with the key risk>
DRIVERS: <ranked list of what moves gold now, most important first>
FILTER: <which fresh headlines push gold UP vs DOWN this phase>
CATALYSTS: <the upcoming HIGH-impact events this week from the calendar, with hot/cool gold direction>
RECOMMENDED ALGOS: <given the phase above, which algos to ENABLE and their direction — pick from the
  ALGO ROSTER in the context. e.g. "tsmom_d1 LONG (D1 uptrend + Fed-easing bias); regime_momentum in
  TREND; stand down mean_reversion (needs RANGE)". Say the direction mode (long/short/both) for tsmom.>
UPDATED: <YYYY-MM-DD> (auto from daily news — <one-line what changed vs a calmer baseline>)

Rules: use ONLY the real data in the context (calendar/news/macro/COT/world/roster) — never invent
numbers, events, price levels, or targets. Be concrete with real event names/figures. Keep it tight
(~180-260 words total). Do NOT add any other sections, preamble, or markdown fences."""


def _read_state():
    try:
        with open(_STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(day):
    try:
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump({"day": day, "updated": datetime.now(timezone.utc).isoformat()[:16] + "Z"}, f)
    except OSError:
        pass


def _llm_narrative(model, is_monday):
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage
    from config import ANTHROPIC_API_KEY
    from agents import weekly_outlook as _wo
    ctx = _wo._gather()                                   # reuse: calendar + news + macro + COT + world + gold_tech
    ctx_txt = json.dumps(ctx, ensure_ascii=False, default=str)[:9000]
    roster = ("\n\n=== ALGO ROSTER (แนะนำเปิดตัวไหน) ===\n"
              "- regime_momentum: momentum breakout · domain=TREND (intraday gold)\n"
              "- tsmom_d1: time-series momentum D1 · domain=TREND(D1) · mode long/short/both (SELL leg −EV → long)\n"
              "- mean_reversion: z-fade · domain=RANGE (CUT live, −EV OOS)\n"
              "- regime_momentum_fvg: momentum + FVG filter · domain=TREND\n"
              "- sweep_reversal: fade prior-day H/L · domain=RANGE/NEUTRAL")
    try:                                                  # + cell ที่ผ่าน gate จริง (algo_selector) ถ้ามี
        from agents.algo_selector import build as _asb
        elig = [f"{r['symbol']}/{r['regime']}→{r['recommend']}"
                for r in ((_asb() or {}).get("recommendations") or []) if r.get("eligible")]
        if elig:
            roster += "\n- DATA-eligible (ผ่าน gate): " + ", ".join(elig)
    except Exception:
        pass
    ctx_txt += roster
    mode = ("MODE — MONDAY BASELINE: it is the start of a new trading week. Set this week's macro "
            "PHASE and the CATALYSTS ahead (this week's high-impact events)."
            if is_monday else
            "MODE — MIDWEEK MORNING UPDATE: the week's baseline is already set. TRACK what has "
            "DEVELOPED since Monday — new economic prints/surprises, geopolitical shifts, fresh news — "
            "and update the phase/drivers/filter/catalysts to the CURRENT situation. Do NOT recap the "
            "past week; report what is new and what it means for gold now.")
    llm = ChatAnthropic(model=model, api_key=ANTHROPIC_API_KEY, max_tokens=700,
                        temperature=0, timeout=60, max_retries=1)
    out = llm.invoke([SystemMessage(content=_SYSTEM),
                      HumanMessage(content=f"{mode}\n\nCURRENT DATA (fresh):\n{ctx_txt}\n\nRewrite the macro-regime narrative.")])
    txt = (out.content if hasattr(out, "content") else str(out)).strip()
    txt = txt.replace("```", "").strip()
    if "PHASE:" not in txt or "DRIVERS:" not in txt:     # sanity: ต้องได้ format ที่ analyst อ่านได้
        raise ValueError("narrative missing required sections")
    return txt


def _write_file(narrative):
    """เขียน narrative ใหม่ = header + REGIME_START + MACRO_AUTO block (verbatim) + narrative.
    backup ไฟล์เดิม → .bak. คืน True ถ้าเขียนสำเร็จ."""
    with open(_REGIME, encoding="utf-8") as f:
        txt = f.read()
    si = txt.find(_START)
    ai = txt.find(_AUTO_START)
    ei = txt.find(_AUTO_END)
    if si < 0 or ai < 0 or ei < 0 or not (si < ai < ei):
        logger.warning("[regime_narrative] markers ไม่ครบ/ผิดลำดับ — ข้ามการเขียน (กันพัง)")
        return False
    header = txt[:si + len(_START)]
    auto_block = txt[ai:ei + len(_AUTO_END)]
    shutil.copyfile(_REGIME, _REGIME + ".bak")           # backup ก่อนเขียน (review/revert ได้)
    new_txt = header + "\n" + auto_block + "\n\n" + narrative.strip() + "\n"
    tmp = _REGIME + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_txt)
    os.replace(tmp, _REGIME)                              # atomic
    return True


def refresh(force=False):
    """สร้าง narrative ใหม่ + เขียน (ถ้า flag on). วันละครั้ง หลัง morning hour (local). fail-soft."""
    import config as _cfg
    if not force and not getattr(_cfg, "REGIME_NARRATIVE_AUTO", False):
        return None
    try:
        now = datetime.now()                             # local (โซนผู้ใช้ = เช้าตามเวลาจริง)
        day = now.strftime("%Y-%m-%d")
        if not force:
            if now.hour < int(getattr(_cfg, "REGIME_NARRATIVE_HOUR", 7)):
                return None                              # ยังไม่ถึงเช้า → รอ
            if _read_state().get("day") == day:
                return None                              # ทำวันนี้แล้ว
        is_monday = (now.weekday() == 0)
        model = getattr(_cfg, "REGIME_NARRATIVE_MODEL", "claude-sonnet-4-6")
        narrative = _llm_narrative(model, is_monday)
        if _write_file(narrative):
            _write_state(day)
            first = narrative.splitlines()[0][:120]
            mode = "MON-baseline" if is_monday else "midweek-update"
            logger.info(f"[regime_narrative] เขียน macro_regime.md ใหม่ ({day} {mode}, {model}) · {first}")
            return {"ok": True, "day": day, "monday": is_monday, "first_line": first}
    except Exception as e:
        logger.warning(f"[regime_narrative] refresh fail ({type(e).__name__}: {e}) — ไม่แตะไฟล์")
    return None


def tick():
    """เรียกทุก cycle จาก node_position_mgmt. act เฉพาะเช้าวันใหม่ + flag on. fail-soft."""
    try:
        return refresh(force=False)
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, _BASE)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    print(refresh(force=True))
