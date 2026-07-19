"""
LangGraph pipeline — แทน sequential pipeline ใน run_cycle()

Graph flow:
  _entry → (skip_ai?) → position_mgmt → END
         → chart → advisor → (net_degraded?) → accounting → END
                           → news → analyst → decision → position_mgmt → reporter → accounting → END
"""
import time
from typing import TypedDict
from langgraph.graph import StateGraph, END
from loguru import logger


def _to_native(obj):
    """Recursively convert numpy/special types to msgpack-safe Python natives."""
    try:
        import math
        import numpy as np
        if isinstance(obj, dict):
            return {k: _to_native(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_to_native(v) for v in obj]
        if isinstance(obj, np.floating):
            v = float(obj)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, (np.str_, np.bytes_)):
            return str(obj)
        if isinstance(obj, np.ndarray):
            return _to_native(obj.tolist())
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
    except ImportError:
        pass
    return obj

# ── State ──────────────────────────────────────────────────────────────────────
class TradingState(TypedDict):
    skip_ai:        bool
    skip_reason:    str
    chart_data:     dict
    advisor_data:   dict
    news_data:      dict
    sentiment_data: dict
    decision:       dict
    net_degraded:   bool
    latencies:      dict
    error_steps:    list

GRAPH_CONFIG = {"configurable": {"thread_id": "xauusd_main"}}

EMPTY_STATE: TradingState = {
    "skip_ai":        False,
    "skip_reason":    "",
    "chart_data":     {},
    "advisor_data":   {},
    "news_data":      {"tweets": [], "count": 0},
    "sentiment_data": {"sentiment": "NEUTRAL", "confidence": 0, "summary": "", "tweet_count": 0},
    "decision":       {"action": "SKIP", "reason": ""},
    "net_degraded":   False,
    "latencies":      {},
    "error_steps":    [],
}


# ── Nodes ──────────────────────────────────────────────────────────────────────

def node_entry(state: TradingState) -> dict:
    return {}


def node_chart(state: TradingState) -> dict:
    from agents.chart_watcher import analyze_chart
    from utils.display import print_step, print_signal_box
    print_step(0, "running", "กำลังดึงข้อมูลกราฟ...")
    t = time.monotonic()
    try:
        data = _to_native(analyze_chart())
        lat  = int((time.monotonic() - t) * 1000)
        sig  = data.get("signal", "NO_TRADE")
        conf = data.get("confidence", 0)
        print_step(0, "done", f"{sig}  ({conf}%)")
        print_signal_box(data)
        return {
            "chart_data": data,
            "latencies":  {**state.get("latencies", {}), "chart_watcher": lat},
        }
    except Exception as e:
        print_step(0, "error", str(e)[:60])
        logger.error(f"[GRAPH:chart] {e}")
        return {
            "chart_data":  {"signal": "NO_TRADE", "confidence": 0, "sl_pips": 1000, "tp_pips": 1500},
            "error_steps": state.get("error_steps", []) + ["chart_watcher"],
        }


def node_advisor(state: TradingState) -> dict:
    import config as _cfg
    if getattr(_cfg, "REGIME_LIVE", False):
        # near-0 token: algo หา regime เอง (ER/ADX/vol จาก MT5) → ข้าม market_advisor LLM
        return {"advisor_data": {}, "net_degraded": False}
    from agents.market_advisor import analyze_market_regime
    from utils.display import print_step, print_advisor_box
    print_step(1, "running", "กำลังวิเคราะห์ market regime...")
    t = time.monotonic()
    try:
        data   = _to_native(analyze_market_regime(state["chart_data"]))
        lat    = int((time.monotonic() - t) * 1000)
        regime = data.get("regime", "—")
        conf   = data.get("regime_confidence", 0)
        bias   = data.get("bias", "—")
        print_step(1, "done", f"{regime}  ({conf}%)  Bias: {bias}")
        print_advisor_box(data)
        return {
            "advisor_data": data,
            "net_degraded": False,
            "latencies":    {**state.get("latencies", {}), "market_advisor": lat},
        }
    except Exception as e:
        print_step(1, "error", str(e)[:60])
        logger.error(f"[GRAPH:advisor] {e}")
        cw_failed = "chart_watcher" in state.get("error_steps", [])
        return {
            "advisor_data": {},
            "net_degraded": cw_failed,
            "error_steps":  state.get("error_steps", []) + ["market_advisor"],
        }


async def node_news(state: TradingState) -> dict:
    from agents.news_gatherer import gather_news
    from utils.display import print_step
    print_step(2, "running", "กำลังดึงข่าว Twitter/X...")
    try:
        data  = await gather_news()
        count = data.get("count", 0)
        print_step(2, "done", f"{count} tweet")
        # --- M1 measurement: news_impact pre-filter (observe-only, fail-soft) ---
        try:
            from agents import news_impact as _ni
            _posts = _ni.normalize_posts(data)
            _kept, _stats = _ni.prefilter_and_dedupe(_posts)
            logger.info("[news_impact] filter %s", _stats)
        except Exception as _ni_err:
            logger.warning("[news_impact] prefilter skipped: %s", _ni_err)
        # -----------------------------------------------------------------------
        return {"news_data": data}
    except Exception as e:
        print_step(2, "error", str(e)[:60])
        logger.error(f"[GRAPH:news] {e}")
        return {"news_data": {"tweets": [], "count": 0}}


_last_news_sig = None       # event-driven analyst: ยิง LLM เฉพาะมีข่าว/โพสใหม่ (vision owner)
_last_sentiment = None


def _news_sig(news_data: dict):
    tweets = (news_data or {}).get("tweets", []) or []
    keys = tuple(sorted(str((t.get("id") if isinstance(t, dict) else None) or
                            (t.get("text") if isinstance(t, dict) else t))[:80] for t in tweets))
    return hash(keys)


def node_analyst(state: TradingState) -> dict:
    from agents.analyst import analyze_sentiment
    from utils.display import print_step, print_sentiment_box
    global _last_news_sig, _last_sentiment
    # event-driven: ไม่มีข่าวใหม่ → reuse sentiment (ข้าม Claude call) = near-0 token
    sig = _news_sig(state.get("news_data") or {})
    if sig == _last_news_sig and _last_sentiment is not None:
        print_step(3, "done", f"{_last_sentiment.get('sentiment','NEUTRAL')} (cached — ไม่มีข่าวใหม่)")
        return {"sentiment_data": {**_last_sentiment, "cached": True}}
    print_step(3, "running", "กำลังวิเคราะห์ sentiment...")
    t = time.monotonic()
    try:
        data  = _to_native(analyze_sentiment(state["news_data"], state["chart_data"]))
        data["news_count"] = state["news_data"].get("count", 0)
        _last_news_sig = sig
        _last_sentiment = data
        lat   = int((time.monotonic() - t) * 1000)
        sent  = data.get("sentiment", "NEUTRAL")
        sconf = data.get("confidence", 0)
        print_step(3, "done", f"{sent}  ({sconf}%)")
        print_sentiment_box(data)
        return {
            "sentiment_data": data,
            "latencies":      {**state.get("latencies", {}), "analyst": lat},
        }
    except Exception as e:
        print_step(3, "error", str(e)[:60])
        logger.error(f"[GRAPH:analyst] {e}")
        return {
            "sentiment_data": {"sentiment": "NEUTRAL", "confidence": 0, "summary": "", "tweet_count": 0}
        }


def node_decision(state: TradingState) -> dict:
    from agents.decision_maker import make_decision
    from utils.display import print_step, print_decision_box
    print_step(4, "running", "กำลังตัดสินใจ...")
    t = time.monotonic()
    try:
        data   = make_decision(state["chart_data"], state["sentiment_data"], state["advisor_data"])
        # P1b shadow snapshot (add-only, fail-soft, 0 behavior change) — สะสม labeled data
        try:
            from agents.decision_snapshot import log_decision_snapshot
            log_decision_snapshot(state["chart_data"], state["sentiment_data"], data)
        except Exception as _snap_e:
            logger.debug(f"[SNAPSHOT] hook fail-soft: {_snap_e}")
        lat    = int((time.monotonic() - t) * 1000)
        action = data.get("action", "SKIP")
        detail = f"EXECUTE {data.get('direction','')}" if action == "EXECUTE" else "SKIP"
        status = "done" if action == "EXECUTE" else "skip"
        print_step(4, status, detail)
        print_decision_box(data)
        return {
            "decision": data,
            "latencies": {**state.get("latencies", {}), "decision_maker": lat},
        }
    except Exception as e:
        print_step(4, "error", str(e)[:60])
        logger.error(f"[GRAPH:decision] {e}")
        return {"decision": {"action": "SKIP", "reason": str(e)}}


def node_position_mgmt(state: TradingState) -> dict:
    """รัน position management ทุก cycle — ทั้ง skip_ai และ full path"""
    from connectors.mt5_connector import (
        manage_momentum_exit, manage_zone_break_close, manage_partial_close,
        manage_breakeven, manage_dynamic_tp, manage_post_event_tp, manage_trailing_stop,
        ensure_sl_protection,
    )
    from agents.swing_manager import manage_swing_campaign   # inert จน SWING_ENABLED=true + equity≥min
    from agents.reporter import scan_manual_orders
    from utils.display import print_warning
    import config as _cfg
    chart = state.get("chart_data") or {}
    # scan manual orders every cycle (including skip_ai) so they're never missed
    try:
        scan_manual_orders(chart or None)
    except Exception as e:
        logger.error(f"[GRAPH:position_mgmt] scan_manual_orders: {e}")
    # แต่ละ management แยก try/except — failure ตัวเดียวต้องไม่ข้าม protective ตัวที่เหลือในรอบนั้น
    # (เดิม try ก้อนเดียว: NameError/exception ที่ momentum_exit จะข้าม breakeven/zone-break/trailing หมด
    #  พอดีจังหวะที่ราคาวิ่งสวนแรง = ตอนที่ protective สำคัญที่สุด). ลำดับคงเดิม: momentum-exit ก่อน
    _mgmt = (
        (ensure_sl_protection,   (),        "AUTO-SL: ตั้ง SL ให้ {} ไม้ที่ไม่มี SL (อุดรู no-SL)"),
        (manage_momentum_exit,   (),        "Momentum Exit: ปิดเร็ว {} position (momentum สวนทางแรง)"),
        (manage_zone_break_close, (chart,),  "Zone Break: ปิด/re-enter {} position (HTF zone ถูกทะลุ)"),
        (manage_partial_close,   (),        "Partial close: scale out {} position(s)"),
        (manage_breakeven,       (),        "Breakeven: ขยับ SL หน้าทุน {} position"),
        (manage_dynamic_tp,      (),        "Dynamic TP: ขยับ TP ออก {} position (momentum แรง)"),
        (manage_post_event_tp,   (chart,),  "Post-event TP: ตั้ง TP {} position (momentum สงบแล้ว)"),
        (manage_trailing_stop,   (),        "Trailing Stop: ขยับ SL {} position"),
        (manage_swing_campaign,  (chart,),  "SWING: {} action(s) (long-term campaign)"),
    )
    if getattr(_cfg, "REGIME_LIVE", False):   # algo mode: ปิด swing entry (algo วาง order เอง) — protective ที่เหลือคงไว้
        _mgmt = tuple(m for m in _mgmt if m[0].__name__ != "manage_swing_campaign")
    for _fn, _args, _msg in _mgmt:
        try:
            _n = _fn(*_args)
            if _n:
                print_warning(_msg.format(_n))
        except Exception as e:
            logger.error(f"[GRAPH:position_mgmt] {_fn.__name__}: {e}")
    # P1c shadow excursion sampling (add-only, fail-soft, 0 behavior change) — สะสม MFE/MAE
    try:
        from agents.trade_excursion import log_excursions
        log_excursions()
    except Exception as _exc_e:
        logger.debug(f"[EXCURSION] hook fail-soft: {_exc_e}")
    # REGIME_LIVE: algo entry executor — วาง order จริงจาก momentum breakout (deterministic). รันทุก cycle. fail-soft.
    try:
        from agents.regime_executor import run_regime_executor
        _r = run_regime_executor()
        if _r and isinstance(_r.get("order"), dict) and _r["order"].get("success"):
            print_warning(f"[ALGO] เข้า {_r['signal']['dir']} momentum breakout "
                          f"SL={_r['signal']['sl_pips']}p TP={_r['signal']['tp_pips']}p")
    except Exception as _ae:
        logger.error(f"[GRAPH:regime_executor] {_ae}")
    # REGIME_PENDING: algo วาง pending straddle ล่วงหน้า (safety cancel + MAX_OPEN guard ในตัว). fail-soft.
    try:
        from agents.regime_pending import manage_algo_pending
        _p = manage_algo_pending()
        if _p:
            print_warning(f"[ALGO-PENDING] วาง {_p} pending straddle ที่ Donchian level")
    except Exception as _pe:
        logger.error(f"[GRAPH:regime_pending] {_pe}")
    return {}


def node_reporter(state: TradingState) -> dict:
    from agents.reporter import log_trade, print_summary, scan_manual_orders
    from agents.pending_manager import auto_place_pending_orders, manage_range_pending, manage_sl_reentry, cancel_pending_on_breakdown, manage_zone_reentry
    from utils.display import print_step, print_warning
    import config as _cfg
    print_step(5, "running", "กำลังบันทึกผล...")
    chart     = state.get("chart_data") or {}
    decision  = state.get("decision") or {}
    sentiment = state.get("sentiment_data") or {}
    try:
        log_trade(decision)
        n = scan_manual_orders(chart or None)
        print_step(5, "done", "done" + (f" (+{n} manual)" if n else ""))
        if n: print_warning(f"พบ manual order {n} รายการ — บันทึก context แล้ว")
        try:
            cb = cancel_pending_on_breakdown(chart)   # cancel = safety รันเสมอ
            if cb: print_warning(f"Breakdown: ยกเลิก {cb} AP pending ที่จะ fill สวน momentum")
        except Exception as e:
            logger.error(f"Cancel-pending error: {e}")
        if not getattr(_cfg, "REGIME_LIVE", False):   # REGIME_LIVE: algo วาง order เอง → ปิด pending/reentry/ZRE ทั้งหมด
            try:
                p = auto_place_pending_orders(chart, sentiment)
                if p: print_warning(f"Auto-pending: วาง {p} order ที่ key S/R levels (H4+Daily)")
            except Exception as e:
                logger.error(f"Auto-pending error: {e}")
            try:
                rp = manage_range_pending(chart)
                if rp: print_warning(f"Range pending: วาง {rp} order ที่กรอบ sideways")
            except Exception as e:
                logger.error(f"Range pending error: {e}")
            try:
                sr = manage_sl_reentry(chart)
                if sr: print_warning(f"Post-SL: วาง {sr} re-entry order ที่ safe zone")
            except Exception as e:
                logger.error(f"Post-SL re-entry error: {e}")
            try:
                zr = manage_zone_reentry(chart)
                if zr: print_warning(f"ZRE: วาง {zr} zone re-entry order ที่โซนเกรดสูง (RR≥2)")
            except Exception as e:
                logger.error(f"ZRE error: {e}")
        print_summary()
    except Exception as e:
        print_step(5, "error", str(e)[:60])
        logger.error(f"[GRAPH:reporter] {e}")
    return {}


def node_accounting(state: TradingState) -> dict:
    import agents.chart_watcher  as _cw
    import agents.market_advisor as _ma
    import agents.analyst        as _an
    import agents.decision_maker as _dm
    import agents.reporter       as _rp
    import config
    from agents.accountant import record_cycle
    from agents.llm_models import model_for   # single source of truth: agent -> model
    try:
        ticket = (
            state.get("decision", {}).get("order", {}).get("ticket")
            if state.get("decision", {}).get("action") == "EXECUTE" else None
        )
        record_cycle(
            symbol=config.SYMBOL,
            agent_usages={
                "chart_watcher":  (model_for("chart_watcher"),  _cw._last_usage),
                "market_advisor": (model_for("market_advisor"), _ma._last_usage),
                "analyst":        (model_for("analyst"),        _an._last_usage),
                "decision_maker": (model_for("decision_maker"), _dm._last_usage),
                "reporter":       (model_for("reporter"),       _rp._last_usage),
            },
            ticket=ticket,
            latencies_ms=state.get("latencies", {}),
        )
    except Exception as e:
        logger.error(f"[GRAPH:accounting] {e}")
    return {}


# ── Specialist node (Layer-A, flag-gated) ───────────────────────────────────────

def _append_spec_shadow(cd: dict, zm: dict, spec: dict, current: float) -> None:
    """Append-only capture of the FULL specialist input contract → logs/spec_shadow.jsonl, so an
    offline replay can later answer trigger-rate / cap / win-rate. Pure file write, 0 tokens.
    Whitelisted fields (drops the big `raw`/`scan`) keep the log replay-sufficient without bloat."""
    from datetime import datetime, timezone
    import json as _json
    rec = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "current":     current,
        "trend":       cd.get("trend"),        "d1_trend":   cd.get("d1_trend"),
        "momentum_tf": cd.get("momentum_tf"),  "candle_pat": cd.get("candle_pat"),
        "sr_actions":  cd.get("sr_actions"),   "sr_meta":    cd.get("sr_meta"),
        "sr_zones":    cd.get("sr_zones"),     "key_levels": cd.get("key_levels"),
        "htf_zone":    cd.get("htf_zone"),     "indicators": cd.get("indicators"),
        "zone_map":    zm,                     "spec_route": spec,
    }
    with open("logs/spec_shadow.jsonl", "a", encoding="utf-8") as f:
        f.write(_json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def node_specialist(state: TradingState) -> dict:
    """Build zone_map + route specialist candidates.
      SPECIALIST_SHADOW=true  => compute + append-only capture to logs/spec_shadow.jsonl, but DO NOT
                                 influence the decision (data-collection mode; 0 tokens, 0 behavior change).
      SPECIALIST_ENABLED=true => also enrich chart_data (advisory to decision_maker; gates + cap decide).
      both false (default)    => passthrough {}, ZERO change."""
    import config as _cfg
    enabled = getattr(_cfg, "SPECIALIST_ENABLED", False)
    shadow  = getattr(_cfg, "SPECIALIST_SHADOW", False)
    if not (enabled or shadow):
        return {}
    try:
        from agents.zone_mapper import build_zone_map
        from agents.specialist_router import route
        cd  = state.get("chart_data") or {}
        ind = cd.get("indicators") or {}
        current = (ind.get("m15") or {}).get("close") or (ind.get("h1") or {}).get("close")
        if not current:
            return {}
        zm   = build_zone_map(cd, current)
        spec = route(cd, zm)
        logger.info(spec["log"])
        if shadow:
            try:
                _append_spec_shadow(cd, zm, spec, current)
            except Exception as _se:
                logger.error(f"[GRAPH:specialist] shadow capture failed: {_se}")
        # shadow-only mode captures but must NOT change the decision → return {}
        return {"chart_data": {**cd, "zone_map": zm, "spec_route": spec}} if enabled else {}
    except Exception as e:
        logger.error(f"[GRAPH:specialist] {e}")
        return {}


def node_regime_shadow(state: TradingState) -> dict:
    """Minimal-AI regime router — SHADOW capture (flag REGIME_SHADOW). fetch H1 bars เอง
    (regime engine ต้องการ OHLC arrays ไม่ใช่ chart_data) → regime_lib.route() → log ว่า "จะเข้าไม้ไหน".
    0 LLM, 0 order, return {} (ไม่แตะ decision). flag OFF (default) = passthrough. ดู docs/DESIGN_regime_shadow.md."""
    import config as _cfg
    if not getattr(_cfg, "REGIME_SHADOW", False):
        return {}
    try:
        from agents.regime_shadow import run_regime_shadow
        rec = run_regime_shadow()
        if rec:
            logger.info(f"[REGIME-SHADOW] {rec['regime']} sig={rec.get('signal')}")
    except Exception as e:
        logger.error(f"[GRAPH:regime_shadow] {e}")
    return {}


# ── Routing ────────────────────────────────────────────────────────────────────

def route_entry(state: TradingState) -> str:
    if state.get("skip_ai"):
        return "position_mgmt"
    return "chart"


def route_after_advisor(state: TradingState) -> str:
    if state.get("net_degraded"):
        # เดิมข้ามไป accounting เลย = cycle นี้ไม่มี BE/trailing/momentum-exit/AUTO-SL ดูแลไม้
        # แล้ว main loop รอต่ออีก 600s — จังหวะ API ล่มคือจังหวะที่ protective สำคัญที่สุด
        logger.warning("[GRAPH] Network degraded (CW+MA fail) — รัน position_mgmt ก่อนจบ cycle")
        return "position_mgmt"
    return "news"


def route_after_position_mgmt(state: TradingState) -> str:
    if state.get("skip_ai"):
        return "done"        # skip_ai path: position mgmt only → END
    if state.get("net_degraded"):
        return "accounting"  # degraded: ไม่วิ่ง reporter/pending ด้วยข้อมูลพัง แต่ยังบันทึก usage
    return "reporter"


# ── Build Graph ────────────────────────────────────────────────────────────────

def build_trading_graph():
    g = StateGraph(TradingState)

    g.add_node("_entry",        node_entry)
    g.add_node("chart",         node_chart)
    g.add_node("specialist",    node_specialist)
    g.add_node("regime_shadow", node_regime_shadow)
    g.add_node("advisor",       node_advisor)
    g.add_node("news",          node_news)
    g.add_node("analyst",       node_analyst)
    g.add_node("decision",      node_decision)
    g.add_node("position_mgmt", node_position_mgmt)
    g.add_node("reporter",      node_reporter)
    g.add_node("accounting",    node_accounting)

    g.set_entry_point("_entry")
    g.add_conditional_edges("_entry", route_entry, {
        "chart":         "chart",
        "position_mgmt": "position_mgmt",
    })
    g.add_edge("chart",         "specialist")
    g.add_edge("specialist",    "regime_shadow")
    g.add_edge("regime_shadow", "advisor")
    g.add_conditional_edges("advisor", route_after_advisor, {
        "news":          "news",
        "position_mgmt": "position_mgmt",   # net_degraded: ยังต้องดูแลไม้ก่อนจบ cycle
    })
    g.add_edge("news",     "analyst")
    g.add_edge("analyst",  "decision")
    g.add_edge("decision", "position_mgmt")
    g.add_conditional_edges("position_mgmt", route_after_position_mgmt, {
        "reporter":   "reporter",
        "accounting": "accounting",         # net_degraded path
        "done":       END,
    })
    g.add_edge("reporter",   "accounting")
    g.add_edge("accounting", END)

    return g.compile()  # stateless per cycle — no checkpoint bleed between cycles


# Singleton — compile once at import time
TRADING_APP = build_trading_graph()
