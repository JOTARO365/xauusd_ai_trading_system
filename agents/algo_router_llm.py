"""agents/algo_router_llm.py — LLM auto-swap algo router (user 08-08).

CORE INVARIANT: AI เลือก *algo* เท่านั้น ไม่ตัดสิน entry (data ยัง trigger เอง). LLM ดูภาพรวม →
สลับว่าคู่/algo ไหนควร LIVE/SHADOW ให้เหมาะสภาพตอนนี้ (regime + ข่าว + performance + backtest +EV).

trigger (คุม token — ไม่เรียกทุก cycle):
  - loss-streak ≥ LOSS_STREAK_RECHECK ต่อ (algo,คู่)  หรือ
  - periodic ทุก ALGO_ROUTER_EVERY_HRS ชม.
input LLM: regime/คู่ · algo แพ้ติด · sentiment(score+reason) · event ใกล้ · backtest matrix (+EV/−EV)
output (structured): [{algo, pair, action LIVE/SHADOW, reason}]
apply: shadow-log ก่อน (ALGO_ROUTER_LIVE=false → log อย่างเดียว ไม่แตะ switch). cache/TTL. fail-soft.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

_BASE = Path(__file__).resolve().parent.parent
_STATE = _BASE / "data" / "algo_router_state.json"
_JOURNAL = _BASE / "data" / "algo_router_journal.jsonl"
_llm = None


def _cfg(n, d):
    import config as _c
    return getattr(_c, n, d)


def _schema():
    from pydantic import BaseModel, Field
    from typing import List

    class Swap(BaseModel):
        algo: str = Field(description="algo_id เช่น macro_momentum, confluence_15m, tsmom_d1, regime_momentum")
        pair: str = Field(description="คู่ เช่น XAUUSD, BTCUSD")
        action: str = Field(description="LIVE หรือ SHADOW")
        reason: str = Field(description="เหตุผลสั้น ภาษาไทย")

    class Decision(BaseModel):
        swaps: List[Swap] = Field(description="รายการ algo:pair ที่ควรเปลี่ยนสถานะ (เฉพาะที่ควรเปลี่ยน ไม่ต้องลิสต์ทั้งหมด)")
        summary: str = Field(description="สรุปเหตุผลรวม 1-2 ประโยค ภาษาไทย")
    return Decision


def _get_llm():
    global _llm
    if _llm is None:
        import config as _cfg
        from langchain_anthropic import ChatAnthropic
        from config import ANTHROPIC_API_KEY
        _llm = ChatAnthropic(model=getattr(_cfg, "ALGO_ROUTER_MODEL", "claude-sonnet-4-6"),
                             api_key=ANTHROPIC_API_KEY, max_tokens=700, temperature=0, timeout=60, max_retries=2
                             ).with_structured_output(_schema(), include_raw=True)
    return _llm


def _context():
    """รวมสภาพปัจจุบันเป็น text ให้ LLM. 0 extra token (อ่านไฟล์/คำนวณ)."""
    parts = []
    # 1) backtest matrix (+EV/−EV) = domain ของแต่ละ algo
    try:
        bt = json.loads((_BASE / "data" / "backtest_results.json").read_text(encoding="utf-8"))
        rows = [f"{r['algo']}:{r['pair']} {r['group']} exp_R={r.get('exp_R')} (live={r.get('live')})"
                for r in bt.get("results", []) if r.get("n")]
        parts.append("=== BACKTEST (+EV=ควรใช้ · −EV=เลี่ยง) ===\n" + "\n".join(rows[:40]))
    except Exception:
        pass
    # 2) algo แพ้ติด (loss-streak)
    try:
        from agents.loss_adaptive import _streaks
        sk = [f"{a}:{s} แพ้ {v['streak']} ติด (ทิศล่าสุด {v['last_dir']})"
              for (a, s), v in _streaks().items() if v["streak"] >= 2]
        parts.append("=== LOSS STREAK (แพ้ติด = พิจารณา SHADOW/สลับ) ===\n" + ("\n".join(sk) if sk else "(ไม่มี)"))
    except Exception:
        pass
    # 3) regime ต่อคู่หลัก
    try:
        import MetaTrader5 as mt5, sys as _sys
        _sys.path.insert(0, str(_BASE / "scripts"))
        import regime_lib as R
        from connectors.pair_collector import _broker_map
        bm = _broker_map() or {}
        reg = []
        for lg in ("XAUUSD", "BTCUSD", "XAGUSD", "WTIUSD"):
            brk = bm.get(lg, lg)
            rr = mt5.copy_rates_from_pos(brk, mt5.TIMEFRAME_H1, 0, 600)
            if rr is None or len(rr) < 300:
                continue
            c = rr["close"].astype(float); h = rr["high"].astype(float); l = rr["low"].astype(float); i = len(c) - 2
            reg.append(f"{lg} H1 regime={R.detect_regime(R.efficiency_ratio(c)[i], R.adx(h,l,c)[i], R.vol_percentile(c)[i])}")
        parts.append("=== REGIME ปัจจุบัน (momentum เข้า TREND · fade เข้า RANGE) ===\n" + "\n".join(reg))
    except Exception:
        pass
    # 4) sentiment + event
    try:
        from agents.sentiment_score import get_score
        s = get_score() or {}
        parts.append(f"=== SENTIMENT ทอง === score={s.get('score')} · {s.get('reason','')}")
    except Exception:
        pass
    try:
        from agents.event_engine import snapshot as _es
        st = _es().get("state", {})
        if st.get("phase") in ("PRE", "POST"):
            parts.append(f"=== EVENT === {st}")
    except Exception:
        pass
    return "\n\n".join(parts)


def _decide(ctx):
    from langchain_core.messages import SystemMessage, HumanMessage
    sysmsg = ("คุณเป็น algo-router ของระบบเทรดทอง/หลายคู่. หน้าที่: ดูสภาพตลาด (regime, ข่าว/sentiment, event) + "
              "ผล backtest (+EV/−EV) + algo ที่กำลังแพ้ติด → ตัดสินว่าควรเปลี่ยน algo:คู่ ไหนเป็น LIVE/SHADOW. "
              "กฎ: (1) เปิด LIVE เฉพาะ +EV ที่เข้าสภาพ regime ตอนนี้ (momentum→TREND, fade→RANGE). "
              "(2) −EV = SHADOW เสมอ. (3) algo แพ้ติดหลายไม้ทั้งที่ +EV → SHADOW ชั่วคราว (ผิดจังหวะ/regime เปลี่ยน). "
              "(4) ห้ามเปิดตัวที่ backtest −EV เด็ดขาด. ตอบเฉพาะ algo:คู่ ที่ควร*เปลี่ยน* + เหตุผลสั้น.")
    raw = _get_llm().invoke([SystemMessage(content=sysmsg),
                             HumanMessage(content=f"สภาพปัจจุบัน:\n{ctx}\n\nควรสลับ algo อะไรบ้าง?")])
    parsed = raw.get("parsed")
    if parsed is None:
        raise ValueError("router parse None")
    usage = (getattr(raw.get("raw"), "response_metadata", None) or {}).get("usage", {})
    return parsed, usage


def _journal(rec):
    try:
        with open(_JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _should_run(state):
    """trigger: loss-streak ≥ N หรือ พ้น periodic. คืน (run, reason)."""
    now = time.time()
    every = float(_cfg("ALGO_ROUTER_EVERY_HRS", 6)) * 3600
    if now - float(state.get("last_run", 0)) >= every:
        return True, "periodic"
    try:
        from agents.loss_adaptive import _streaks
        n = int(_cfg("LOSS_STREAK_RECHECK", 3))
        if any(v["streak"] >= n for v in _streaks().values()):
            if now - float(state.get("last_run", 0)) >= float(_cfg("ALGO_ROUTER_MIN_GAP_MIN", 60)) * 60:
                return True, "loss-streak"
    except Exception:
        pass
    return False, None


def tick():
    """เรียกทุก cycle. รัน LLM เฉพาะเมื่อ trigger (คุม token). shadow-log ถ้า ALGO_ROUTER_LIVE=false. fail-soft."""
    try:
        if not _cfg("ALGO_ROUTER_ENABLE", False):             # master switch (แม้ shadow ต้องเปิดถึงจะรัน LLM)
            return None
        state = json.loads(_STATE.read_text(encoding="utf-8")) if _STATE.exists() else {}
        run, why = _should_run(state)
        if not run:
            return None
        state["last_run"] = time.time()
        ctx = _context()
        parsed, usage = _decide(ctx)
        live = bool(_cfg("ALGO_ROUTER_LIVE", False))
        applied = []
        for sw_ in parsed.swaps:
            act = (sw_.action or "").upper()
            if act not in ("LIVE", "SHADOW"):
                continue
            rec = {"algo": sw_.algo, "pair": sw_.pair, "action": act, "reason": sw_.reason, "live": live, "trigger": why}
            if live:
                try:
                    from agents import shadow_switches as swm
                    swm.set_state(sw_.algo, sw_.pair, act)
                except Exception:
                    pass
            _journal(rec); applied.append(rec)
        state["summary"] = parsed.summary
        state["at"] = datetime.now(timezone.utc).isoformat()
        _STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[ALGO-ROUTER] (%s) %s → %d swaps%s · in=%s out=%s" % (
            why, parsed.summary[:80], len(applied), "" if live else " (shadow)",
            usage.get("input_tokens"), usage.get("output_tokens")))
        return {"summary": parsed.summary, "swaps": applied}
    except Exception as e:
        logger.debug("[ALGO-ROUTER] fail-soft: %s" % e)
        return None


def snapshot():
    try:
        st = json.loads(_STATE.read_text(encoding="utf-8")) if _STATE.exists() else {}
        return {"ok": True, "enable": bool(_cfg("ALGO_ROUTER_ENABLE", False)),
                "live": bool(_cfg("ALGO_ROUTER_LIVE", False)),
                "summary": st.get("summary"), "at": st.get("at")}
    except Exception:
        return {"ok": False}
