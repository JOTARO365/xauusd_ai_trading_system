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
        return {"news_data": data}
    except Exception as e:
        print_step(2, "error", str(e)[:60])
        logger.error(f"[GRAPH:news] {e}")
        return {"news_data": {"tweets": [], "count": 0}}


def node_analyst(state: TradingState) -> dict:
    from agents.analyst import analyze_sentiment
    from utils.display import print_step, print_sentiment_box
    print_step(3, "running", "กำลังวิเคราะห์ sentiment...")
    t = time.monotonic()
    try:
        data  = _to_native(analyze_sentiment(state["news_data"], state["chart_data"]))
        data["news_count"] = state["news_data"].get("count", 0)
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
    for _fn, _args, _msg in _mgmt:
        try:
            _n = _fn(*_args)
            if _n:
                print_warning(_msg.format(_n))
        except Exception as e:
            logger.error(f"[GRAPH:position_mgmt] {_fn.__name__}: {e}")
    return {}


def node_reporter(state: TradingState) -> dict:
    from agents.reporter import log_trade, print_summary, scan_manual_orders
    from agents.pending_manager import auto_place_pending_orders, manage_range_pending, manage_sl_reentry, cancel_pending_on_breakdown
    from utils.display import print_step, print_warning
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
            cb = cancel_pending_on_breakdown(chart)
            if cb: print_warning(f"Breakdown: ยกเลิก {cb} AP pending ที่จะ fill สวน momentum")
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


# ── Routing ────────────────────────────────────────────────────────────────────

def route_entry(state: TradingState) -> str:
    if state.get("skip_ai"):
        return "position_mgmt"
    return "chart"


def route_after_advisor(state: TradingState) -> str:
    if state.get("net_degraded"):
        logger.warning("[GRAPH] Network degraded (CW+MA fail) — skip to accounting")
        return "accounting"
    return "news"


def route_after_position_mgmt(state: TradingState) -> str:
    if state.get("skip_ai"):
        return "done"   # skip_ai path: position mgmt only → END
    return "reporter"


# ── Build Graph ────────────────────────────────────────────────────────────────

def build_trading_graph():
    g = StateGraph(TradingState)

    g.add_node("_entry",        node_entry)
    g.add_node("chart",         node_chart)
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
    g.add_edge("chart",    "advisor")
    g.add_conditional_edges("advisor", route_after_advisor, {
        "news":       "news",
        "accounting": "accounting",
    })
    g.add_edge("news",     "analyst")
    g.add_edge("analyst",  "decision")
    g.add_edge("decision", "position_mgmt")
    g.add_conditional_edges("position_mgmt", route_after_position_mgmt, {
        "reporter": "reporter",
        "done":     END,
    })
    g.add_edge("reporter",   "accounting")
    g.add_edge("accounting", END)

    return g.compile()  # stateless per cycle — no checkpoint bleed between cycles


# Singleton — compile once at import time
TRADING_APP = build_trading_graph()
