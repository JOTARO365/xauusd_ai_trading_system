import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date as _date, datetime as _dt, timezone as _timezone
from loguru import logger
from connectors.price_feed import connect_mt5, disconnect_mt5, is_mt5_connected, recent_movement, get_account_info
from connectors.mt5_connector import get_open_positions, get_current_price, is_hedge_active, check_open_slot, is_algo_trading_enabled
from agents.chart_watcher import analyze_m5_pa
from agents.pending_manager import (
    place_weekly_calendar_pending,
    # 3 ตัวล่างถูกเรียกใน slots-full branch (main loop) — เดิมไม่ได้ import ที่นี่
    # (มีแค่ใน trading_graph.node_reporter) → NameError โดน except กลืนทุกรอบที่ slots เต็ม
    auto_place_pending_orders, manage_range_pending, manage_sl_reentry,
)
from agents.trading_graph import TRADING_APP, GRAPH_CONFIG, EMPTY_STATE, TradingState
from utils.display import (
    console, print_header, print_cycle_start, print_cycle_end,
    print_warning, print_error, print_ready_mode_banner,
)
from utils.market_clock import next_interval, market_sleep_status
import config
from config import MONEY_MANAGEMENT

DEFAULT_INTERVAL   = 300
STATUS_INTERVAL    = 60
NET_ERROR_INTERVAL = 600   # รอ 10 นาทีเมื่อ network degraded
READY_INTERVAL     = 120   # 2 min — fast-poll เมื่ออยู่ที่ HTF zone
READY_MAX_MISS     = 2     # ออก Ready Mode ถ้า zone หายไป N รอบติดกัน
READY_MAX_CYCLES   = 15    # ออก Ready Mode หลัง N รอบ (~30 min ที่ 120s)
_cycle            = 0

# ── AI Skip Gate — ประหยัด token เมื่อตลาดไม่ขยับ ──────────────
AI_MIN_INTERVAL_SECS  = 900   # ไม่เรียก AI บ่อยกว่า 15 นาที (= 1 M15 candle)
AI_POS_INTERVAL_SECS  = 300   # มี open position → AI ทุก 5 นาที
AI_NEWS_INTERVAL_SECS = 180   # ช่วงข่าว scheduled → AI ทุก 3 นาที
AI_SPIKE_PIPS         = 500   # ราคาเด้งเกินนี้ → run AI ทันที (ข่าวด่วน/unscheduled)
AI_SR_PROXIMITY_PCT   = 0.1   # ราคาห่าง HTF major zone ภายใน % นี้ → พิจารณารัน AI
                              # (เดิม 0.3% เช็คทุก h4/h1 level → true เกือบตลอด = token รั่ว)
READY_AI_MIN_SECS     = 300   # Ready Mode / near-HTF: ไม่ยิง AI ถี่กว่านี้ (throttle)
                              # (เดิม never-skip → ยิง 4-agent Sonnet ทุก 120s = ตัวกิน token หลัก)
# default true (07-03 Track-1 cost): ตลาดเงียบจริง + ไม่มีไม้บอท → ยืดเป็น 30 นาที
AI_IDLE_GATE          = os.getenv("AI_IDLE_GATE", "true").lower() != "false"
AI_QUIET_INTERVAL_SECS= int(os.getenv("AI_QUIET_INTERVAL_SECS") or 1800)  # idle + เงียบจริง → ยืด throttle (default 30 นาที)
# MIN_AI_EQUITY ย้ายไป config.py (live-reload ได้) — อ่านผ่าน config.MIN_AI_EQUITY
_last_ai_mono:  float = 0.0   # monotonic time ของ AI cycle ล่าสุด
_last_ai_price: float = 0.0   # bid price ตอน AI cycle ล่าสุด

# ── Ready Mode state ──────────────────────────────────────────
_ready_state: dict = {
    "active":    False,
    "zone":      None,    # htf_zone dict ที่ trigger
    "since":     None,    # datetime เข้า ready mode
    "pa_watch":  0,       # จำนวน cycle ที่ดู PA แล้ว
    "miss_count": 0,      # cycle ที่ zone หายไปต่อเนื่อง
}
_last_chart_data:     dict = {}
_last_sentiment_data: dict = {}
_last_weekly_pending_date: "_date | None" = None
_net_degraded: bool = False   # True เมื่อ ChartWatcher + MarketAdvisor ทั้งคู่ fail

_BOT_STATUS_FILE = os.path.join(os.path.dirname(__file__), "logs", "bot_status.json")


def _write_bot_status(chart_data: dict, sentiment_data: dict, decision: dict, skip_ai: bool = False) -> None:
    """Write logs/bot_status.json each cycle — read by /api/monitor in dashboard."""
    try:
        from connectors.price_feed import get_current_price
        import MetaTrader5 as _mt5
        tick = _mt5.symbol_info_tick(config.SYMBOL)
        if tick:
            prev_close = chart_data.get("indicators", {}).get("h1", {}).get("prev_close") or tick.bid
            change_pct = round((tick.bid - prev_close) / prev_close * 100, 3) if prev_close else 0
            price_info = {
                "bid":        round(float(tick.bid), 2),
                "ask":        round(float(tick.ask), 2),
                "spread":     round(float(tick.ask - tick.bid), 2),
                "change_pct": change_pct,
            }
        else:
            price_info = None

        ready = _ready_state
        ready_mode = {
            "active":  ready.get("active", False),
            "zone":    ready.get("zone"),
            "set_at":  ready.get("since").isoformat() if ready.get("since") else None,
        }

        # ── UHAS-style panels (07-03): zone/verdict data ที่ chart_watcher คำนวณอยู่แล้ว ──
        _mom_raw = chart_data.get("momentum_tf") or {}
        market = {
            "trend":          chart_data.get("trend"),
            "d1_trend":       chart_data.get("d1_trend"),
            "fast_move_pips": chart_data.get("fast_move_pips"),
            "momentum_tf": {
                tf: {"direction": (m or {}).get("direction"), "strength": (m or {}).get("strength")}
                for tf, m in _mom_raw.items()
            },
        }
        _sr = chart_data.get("sr_zones") or {}
        zones = {
            "htf_zone":   chart_data.get("htf_zone"),
            "resistance": (_sr.get("resistance") or [])[:6],
            "support":    (_sr.get("support") or [])[:6],
            "sr_meta":    (chart_data.get("sr_meta") or [])[:16],
            "key_levels": chart_data.get("key_levels"),
            "setups": [
                {k: s.get(k) for k in ("type", "tf", "direction", "score", "level")}
                for s in ((chart_data.get("scan") or {}).get("setups") or [])[:8]
            ],
        }
        plan = {
            "buy_sl_pips":  chart_data.get("buy_sl_pips"),
            "sell_sl_pips": chart_data.get("sell_sl_pips"),
            "tp_pips":      chart_data.get("tp_pips"),
        }

        status = {
            "updated_at":   _dt.now().isoformat(timespec="seconds"),
            "cycle":        _cycle,
            "skip_ai":      skip_ai,
            "decision":     decision.get("action", "SKIP"),
            "last_signal": {
                "time":       _dt.now().isoformat(timespec="seconds"),
                "direction":  chart_data.get("signal", ""),
                "confidence": chart_data.get("confidence", 0),
                "action":     decision.get("action", "SKIP"),
                "entry_type": chart_data.get("entry_type", ""),
                "trend":      chart_data.get("trend", ""),
                "sr_zone":    chart_data.get("sr_zone", ""),
                "reason":     decision.get("reason", ""),
            },
            "sentiment":    sentiment_data.get("sentiment", "NEUTRAL"),
            "sent_conf":    sentiment_data.get("confidence", 0),
            "sent_bias":    sentiment_data.get("bias", "NEUTRAL"),        # SELECTION layer: LLM อ่านข่าว X+ตัวเลข
            "sent_summary": sentiment_data.get("summary", ""),           # เหตุผล/บทวิเคราะห์ (display-only 0-token)
            "sent_tweets":  sentiment_data.get("tweet_count", 0),
            "price_info":   price_info,
            "ready_mode":   ready_mode,
            "market":       market,
            "zones":        zones,
            "plan":         plan,
            "signals": {    # เทคนิคจากคลิป (display-only 0-token): retrace-entry / market-structure / reversal-confirm
                "retrace_entry":    chart_data.get("retrace_entry"),
                "market_structure": chart_data.get("market_structure"),
                "reversal_confirm": chart_data.get("reversal_confirm"),
                "fvg":              chart_data.get("fvg"),               # A UHAS
                "double_pattern":   chart_data.get("double_pattern"),    # C UHAS
            },
            # FIX: dashboard renderVolume/renderLiquidity อ่าน bs.volume_profile/liquidity_pools top-level
            # แต่เดิมไม่เคยเขียนลง bot_status → panel UHAS #1/#3 ว่างเปล่า. เขียนให้ (chart_watcher คำนวณแล้ว)
            "volume_profile":  chart_data.get("volume_profile"),
            "liquidity_pools": chart_data.get("liquidity_pools"),
        }
        with open(_BOT_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"bot_status.json write error: {e}")


def _parse_args():
    p = argparse.ArgumentParser(
        prog="main.py",
        description="XAUUSD AI Trading System",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # ── Money Management ──────────────────────────────────────
    mm = p.add_argument_group("Money Management")
    mm.add_argument("--risk",        type=float, metavar="PCT",
                    help="Risk per trade %% (e.g. 0.5 = 50%%)")
    mm.add_argument("--max-loss",    type=float, metavar="PCT",
                    help="Max daily loss %% (e.g. 0.5 = 50%%)")
    mm.add_argument("--max-trades",  type=int,   metavar="N",
                    help="Max open trades (default 4)")
    mm.add_argument("--sl",          type=int,   metavar="PIPS",
                    help="Default SL pips (default 2000)")
    mm.add_argument("--tp",          type=int,   metavar="PIPS",
                    help="Default TP pips (default 5000)")
    mm.add_argument("--rr",          type=float, metavar="RATIO",
                    help="Min Risk/Reward ratio (default 2.0)")

    # ── Lot Size ──────────────────────────────────────────────
    lot = p.add_argument_group("Lot Size")
    lot.add_argument("--lot-mode",   choices=["auto", "fixed"],
                     help="Lot calculation mode")
    lot.add_argument("--fixed-lot",  type=float, metavar="LOT",
                     help="Fixed lot size (used when --lot-mode=fixed)")
    lot.add_argument("--min-lot",    type=float, metavar="LOT",
                     help="Minimum lot size")
    lot.add_argument("--max-lot",    type=float, metavar="LOT",
                     help="Maximum lot size")

    # ── Losing Streak ─────────────────────────────────────────
    streak = p.add_argument_group("Losing Streak Protection")
    streak.add_argument("--max-streak",  type=int, metavar="N",
                        help="แพ้ติดกันกี่ครั้งถึงเพิ่ม threshold (default 5)")
    streak.add_argument("--streak-conf", type=int, metavar="PCT",
                        help="Confidence ขั้นต่ำเมื่อติด streak (default 62)")

    # ── Portfolio Protection ───────────────────────────────────
    prot = p.add_argument_group("Portfolio Protection")
    prot.add_argument("--protection",    dest="protection", action="store_true",
                      default=None, help="เปิด portfolio protection")
    prot.add_argument("--no-protection", dest="protection", action="store_false",
                      help="ปิด portfolio protection (scalping / ทุนน้อย)")
    prot.add_argument("--streak-protect",    dest="streak_protection", action="store_true",
                      default=None, help="เปิด losing streak protection")
    prot.add_argument("--no-streak-protect", dest="streak_protection", action="store_false",
                      help="ปิด losing streak protection (เข้า order ตามสัญญาณปกติ)")

    # ── Symbol ────────────────────────────────────────────────
    p.add_argument("--symbol", type=str, metavar="SYM",
                   help="Trading symbol (default XAUUSD)")

    return p.parse_args()


def _apply_args(args):
    """Override config ด้วยค่าจาก command line (ถ้ามี)"""
    mm = config.MONEY_MANAGEMENT

    if args.risk        is not None: mm["risk_per_trade"]        = args.risk
    if args.max_loss    is not None: mm["max_daily_loss"]         = args.max_loss
    if args.max_trades  is not None: mm["max_open_trades"]        = args.max_trades
    if args.sl          is not None: mm["default_sl_pips"]        = args.sl
    if args.tp          is not None: mm["default_tp_pips"]        = args.tp
    if args.rr          is not None: mm["min_rr_ratio"]           = args.rr
    if args.max_streak  is not None: mm["max_losing_streak"]      = args.max_streak
    if args.streak_conf is not None: mm["streak_min_confidence"]  = args.streak_conf

    if args.lot_mode    is not None: config.LOT_MODE   = args.lot_mode
    if args.fixed_lot   is not None: config.FIXED_LOT  = args.fixed_lot
    if args.min_lot     is not None: config.MIN_LOT     = args.min_lot
    if args.max_lot     is not None: config.MAX_LOT     = args.max_lot
    if args.symbol             is not None: config.SYMBOL               = args.symbol
    if args.protection         is not None: config.PORTFOLIO_PROTECTION  = args.protection
    if args.streak_protection  is not None: config.STREAK_PROTECTION     = args.streak_protection

    # สรุปค่าที่ถูก override
    overrides = {k: v for k, v in vars(args).items() if v is not None}
    if overrides:
        logger.info(f"CLI overrides: {overrides}")


def _setup_logger():
    logger.remove()
    logger.add(
        "logs/system.log",
        rotation="1 day",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        encoding="utf-8",
        enqueue=True,
    )
    # Terminal: เฉพาะ WARNING ขึ้นไป (ข้อความสำคัญ) ผ่าน rich
    logger.add(
        lambda msg: print_warning(msg) if "WARNING" in msg else None,
        level="WARNING",
        format="{message}",
        filter=lambda r: r["level"].name in ("WARNING",),
    )



def _should_skip_ai() -> tuple[bool, str]:
    """
    คืน (skip, reason)
    True  = ข้าม AI agents รอบนี้ (แค่รัน position management)
    False = รัน AI ตามปกติ

    Priority (เช็คตามลำดับ):
      0. Cycle แรก                   → ไม่ skip เสมอ
      1. Price spike ≥ AI_SPIKE_PIPS → ไม่ skip (ข่าวด่วน/unscheduled, override ทุกอย่าง)
      2. Ready Mode active           → throttle: ไม่ยิง AI ถี่กว่า READY_AI_MIN_SECS
      3. Near HTF major zone (0.1%)  → throttle เช่นเดียวกับ Ready Mode
      4. Scheduled news hour UTC     → threshold 3 นาที
      5. มี open position             → threshold 5 นาที
      6. ไม่มี position (ปกติ)        → threshold 15 นาที
    """
    from utils.market_clock import HIGH_IMPACT_HOURS_UTC
    from datetime import datetime, timezone as _tz

    since = time.monotonic() - _last_ai_mono

    # 0. Capital floor — ทุนต่ำกว่าเกณฑ์ → ไม่รัน AI เลย (override ทุกอย่าง รวม spike/first cycle)
    #    pos mgmt ยังทำงานผ่าน graph; ประหยัด token ตอนพอร์ตเล็กเกินกว่าจะเทรดมีความหมาย
    if config.MIN_AI_EQUITY > 0:
        try:
            _eq = get_account_info().get("equity")
            if _eq is not None and _eq < config.MIN_AI_EQUITY:
                return True, f"capital floor: equity {_eq:.0f} < {config.MIN_AI_EQUITY:.0f} — ข้าม AI"
        except Exception:
            pass

    # 0b. First cycle — รัน AI เสมอ
    if _last_ai_mono == 0.0:
        return False, "first cycle"

    # 1. Price spike — ข่าวด่วน flash crash/surprise → รัน AI ทันที (override Ready Mode throttle)
    cur = 0.0
    try:
        cur = get_current_price()
        if cur > 0 and _last_ai_price > 0:
            spike = abs(cur - _last_ai_price) / 0.01   # XAUUSD point = 0.01
            if spike >= AI_SPIKE_PIPS:
                return False, f"price spike {spike:.0f}p ≥ {AI_SPIKE_PIPS}p — ข่าวด่วน!"
    except Exception:
        pass

    # 2. Ready Mode — ยังให้ความสำคัญ แต่ throttle: ไม่ยิง AI ถี่กว่า READY_AI_MIN_SECS
    #    (เดิม never-skip → ยิง 4-agent Sonnet ทุก 120s = ตัวกิน token หลัก)
    if _ready_state.get("active"):
        if since < READY_AI_MIN_SECS:
            return True, f"Ready Mode throttle: {since:.0f}s < {READY_AI_MIN_SECS}s"
        return False, f"Ready Mode active ({since:.0f}s ≥ {READY_AI_MIN_SECS}s)"

    # 3. Near MAJOR (HTF D1/W1) zone เท่านั้น + throttle
    #    (เดิมเช็คทุก h4/h1 level @0.3% → true เกือบตลอด = ตัวรั่วเงียบ)
    try:
        if cur > 0 and _last_chart_data:
            htf = _last_chart_data.get("htf_zone")
            lvl = htf.get("level") if htf else None
            if lvl and abs(cur - lvl) / cur * 100 <= AI_SR_PROXIMITY_PCT:
                if since < READY_AI_MIN_SECS:
                    return True, f"near HTF {lvl:.2f} throttle: {since:.0f}s < {READY_AI_MIN_SECS}s"
                return False, f"near HTF zone {lvl:.2f} ({abs(cur - lvl) / cur * 100:.2f}%)"
    except Exception:
        pass

    # 4. Scheduled news hour
    if datetime.now(_tz.utc).hour in HIGH_IMPACT_HOURS_UTC:
        threshold = AI_NEWS_INTERVAL_SECS
        label = "news hour"
    else:
        # 6/7. ตามจำนวน open positions — นับเฉพาะไม้ SYSTEM (ของบอทเอง)
        #    07-03 Track-1: เดิมนับทุกไม้ → user ถือไม้มือค้างทั้งวัน = AI ทุก 5 นาที 24 ชม.
        #    (burn 500-750฿/วัน ให้บัญชี 2.5k฿) ทั้งที่การคุ้มครองไม้มือ (AUTO-SL/BE)
        #    รันใน skip-path โดยไม่ใช้ AI อยู่แล้ว — ไม้มือไม่ต้องปลุก Sonnet มาเฝ้า
        try:
            _sys_open = any(p.get("source") == "SYSTEM" for p in get_open_positions())
            threshold = AI_POS_INTERVAL_SECS if _sys_open else AI_MIN_INTERVAL_SECS
            label = "open pos" if _sys_open else "normal"
        except Exception:
            threshold, label = AI_MIN_INTERVAL_SECS, "normal"

        # 8. Idle movement gate — ยืด throttle เฉพาะตอน "ตลาดเงียบจริง" (วัด realized
        #    movement สด ผ่าน recent_movement, ไม่ใช่ session/นาฬิกา — ข้อมูลชี้ว่า ชม.
        #    เงียบยังมี value tail). price-spike override (#1) ยังกันการกระชากกะทันหัน.
        if AI_IDLE_GATE and label == "normal":
            mv = recent_movement()
            if mv.get("quiet"):
                threshold = AI_QUIET_INTERVAL_SECS
                label = f"quiet ratio={mv.get('ratio', 0):.2f}"

    if since < threshold:
        return True, f"{label}: {since:.0f}s < {threshold}s (next AI in {threshold - since:.0f}s)"
    return False, f"{label}: {since:.0f}s elapsed → run AI"


async def run_status_cycle() -> None:
    """Slots เต็ม — ข้าม AI, รัน position management ผ่าน graph"""
    config.reload_config()
    global _cycle
    _cycle += 1
    print_cycle_start(_cycle)

    open_pos   = get_open_positions()
    hedge      = is_hedge_active()
    can_buy,   _  = check_open_slot("BUY")
    can_sell,  _  = check_open_slot("SELL")
    max_dir    = MONEY_MANAGEMENT["max_open_trades"]
    buy_count  = sum(1 for p in open_pos if p.get("direction") == "BUY")
    sell_count = sum(1 for p in open_pos if p.get("direction") == "SELL")
    buy_pnl    = sum(p.get("profit", 0) for p in open_pos if p.get("direction") == "BUY")
    sell_pnl   = sum(p.get("profit", 0) for p in open_pos if p.get("direction") == "SELL")
    buy_tag    = f"[green]BUY {buy_count}/{max_dir}  P&L:{buy_pnl:+.2f}[/green]" if can_buy \
                 else f"[dim]BUY {buy_count}/{max_dir}  P&L:{buy_pnl:+.2f}  x[/dim]"
    sell_tag   = f"[green]SELL {sell_count}/{max_dir}  P&L:{sell_pnl:+.2f}[/green]" if can_sell \
                 else f"[dim]SELL {sell_count}/{max_dir}  P&L:{sell_pnl:+.2f}  x[/dim]"
    hedge_tag  = "  [bold cyan]Hedge[/bold cyan]" if hedge else ""
    console.print(f"  [bold yellow]||[/bold yellow]  {buy_tag}   {sell_tag}{hedge_tag}  — skip AI\n")

    state: TradingState = {**EMPTY_STATE, "skip_ai": True, "skip_reason": "slots_full",
                           "chart_data": _last_chart_data or {}}
    await TRADING_APP.ainvoke(state, config=GRAPH_CONFIG)


async def run_cycle() -> tuple[dict, dict]:
    """รัน 1 รอบผ่าน LangGraph — คืน (chart_data, sentiment_data)"""
    config.reload_config()
    global _cycle, _last_chart_data, _last_sentiment_data, _net_degraded
    _cycle += 1
    _cycle_start_t = time.monotonic()
    print_cycle_start(_cycle)

    if config.DRY_RUN:
        logger.warning("[DRY_RUN] โหมดทดสอบ — orders จะไม่ถูกส่งไป MT5 จริง")
        print_warning("DRY_RUN MODE — ไม่มีการส่ง order จริง (ทดสอบเท่านั้น)")
    if config.NNLB_MODE:
        logger.warning("[NNLB] No-Risk-No-Lamborghini — ข้าม money management / gates ทั้งหมด")
        print_warning("NNLB MODE — ข้าม gates / MM ทั้งหมด | lot=MIN_LOT เสมอ")
    if not is_algo_trading_enabled():
        logger.warning("MT5 Algo Trading ปิดอยู่")
        print_warning("MT5 Algo Trading ปิดอยู่ — กดปุ่ม Algo Trading ใน toolbar ก่อน")

    _skip_ai, _skip_why = _should_skip_ai()
    if _skip_ai:
        logger.debug(f"[SKIP_AI] {_skip_why}")
        console.print(f"  [dim]SKIP AI: {_skip_why}[/dim]\n")

    # ── Run graph ──────────────────────────────────────────────────
    initial: TradingState = {
        **EMPTY_STATE,
        "skip_ai":        _skip_ai,
        "skip_reason":    _skip_why,
        "chart_data":     _last_chart_data or {},
        "sentiment_data": _last_sentiment_data or EMPTY_STATE["sentiment_data"],
    }
    result = await TRADING_APP.ainvoke(initial, config=GRAPH_CONFIG)

    chart_data     = result.get("chart_data")     or _last_chart_data or {}
    sentiment_data = result.get("sentiment_data") or _last_sentiment_data or EMPTY_STATE["sentiment_data"]

    if not _skip_ai:
        _last_chart_data     = chart_data
        _last_sentiment_data = sentiment_data
        _net_degraded        = result.get("net_degraded", False)
        # อัปเดต skip gate timing หลัง AI cycle จริง
        global _last_ai_mono, _last_ai_price
        _last_ai_mono  = time.monotonic()
        _last_ai_price = get_current_price()
    # เขียน bot_status ทุก cycle (07-03) — เดิมเขียนเฉพาะ cycle ที่รัน AI ทำ Monitor tab
    # ดูค้างช่วง skip; skip cycle ใช้ chart ล่าสุด + ราคาสดจาก tick (price_info ดึงใหม่เสมอ)
    try:
        _write_bot_status(chart_data, sentiment_data, result.get("decision") or {}, skip_ai=_skip_ai)
    except Exception as e:
        logger.warning(f"bot_status write error: {e}")

    _cycle_secs = time.monotonic() - _cycle_start_t
    _level = "WARNING" if _cycle_secs > 30 else "INFO"
    logger.log(_level, f"[CYCLE_TIME] รอบ #{_cycle} ใช้เวลา {_cycle_secs:.1f}s"
               + (" WARN เกิน 30s" if _cycle_secs > 30 else ""))
    return chart_data, sentiment_data


async def main():
    args = _parse_args()
    _apply_args(args)

    _setup_logger()

    console.print()
    print_header(0)

    if not connect_mt5():
        print_error("เชื่อมต่อ MT5 ไม่ได้ — หยุดระบบ")
        return

    console.print(f"  [green]✓[/green]  เชื่อมต่อ MT5 สำเร็จ\n")

    # ── Position-Guardian thread (default OFF; เปิดด้วย GUARDIAN_ENABLED=true บน VM หลังทดสอบ) ──
    from agents.position_guardian import start_guardian
    if start_guardian():
        console.print(f"  [green]✓[/green]  Position-Guardian thread: ON\n")

    # ── Regime per-tick executor thread (default OFF; REGIME_LIVE_TICK=true + REGIME_LIVE=true) ──
    from agents.regime_tick import start_regime_tick
    if start_regime_tick():
        console.print(f"  [green]✓[/green]  Regime per-tick executor: ON (algo entry realtime)\n")

    # ── DB connectivity check ──────────────────────────────────
    from db.connection import is_available, get_url
    if is_available():
        console.print(f"  [green]✓[/green]  Database: {get_url()}\n")
        # sync MT5 history → DB ตอน startup (เฉพาะ trades ที่ยังไม่มีใน DB)
        from db.sync import sync_mt5_history_to_db, reconcile_open_trades, backfill_metadata_from_logs
        n = sync_mt5_history_to_db(days=365)
        if n:
            console.print(f"  [green]✓[/green]  Synced {n} trade(s) from MT5 → Database\n")
        # ปิด orphan OPEN ของบัญชีนี้ที่ broker ปิดไปแล้ว (scope = บัญชีที่ต่ออยู่เท่านั้น)
        rc = reconcile_open_trades(dry_run=False)
        if rc.get("reconciled") or rc.get("stale"):
            console.print(f"  [green]✓[/green]  Reconciled {rc['reconciled']} closed + "
                          f"{rc['stale']} stale orphan trade(s)\n")
        # เติม decision metadata ให้ row ที่ขาด (มาจาก MT5-sync) จาก trades.json
        bf = backfill_metadata_from_logs(dry_run=False)
        if bf.get("db_missing"):
            console.print(f"  [green]✓[/green]  Metadata backfill: {bf['backfilled']}/{bf['db_missing']} "
                          f"trade(s) enriched from logs (no_log={bf['no_log']})\n")
    else:
        console.print(f"  [yellow]⚠[/yellow]  Database ต่อไม่ได้ ({get_url()}) — บันทึกลง JSON อย่างเดียว\n")

    # ── Startup: verify D1/W1 HTF data availability ───────────────
    try:
        from connectors.price_feed import get_ohlcv as _chk_ohlcv
        import MetaTrader5 as _chk_mt5
        _d1 = _chk_ohlcv(timeframe=_chk_mt5.TIMEFRAME_D1, count=5)
        _w1 = _chk_ohlcv(timeframe=_chk_mt5.TIMEFRAME_W1, count=5)
        _d1_ok = _d1 is not None and len(_d1) >= 3
        _w1_ok = _w1 is not None and len(_w1) >= 3
        if _d1_ok and _w1_ok:
            console.print(f"  [green]✓[/green]  HTF zones: D1({len(_d1)} bars) + W1({len(_w1)} bars) พร้อมใช้งาน\n")
            logger.info(f"[HTF] Startup check: D1={len(_d1)} bars, W1={len(_w1)} bars — OK")
        else:
            console.print(f"  [yellow]⚠[/yellow]  HTF zones: D1={'OK' if _d1_ok else 'ไม่มีข้อมูล'} | W1={'OK' if _w1_ok else 'ไม่มีข้อมูล'}\n")
            logger.warning(f"[HTF] Startup check: D1={'OK' if _d1_ok else 'MISSING'}, W1={'OK' if _w1_ok else 'MISSING'}")
    except Exception as _htf_e:
        console.print(f"  [yellow]⚠[/yellow]  HTF startup check error: {_htf_e}\n")
        logger.warning(f"[HTF] Startup check error: {_htf_e}")

    # รอบแรกใช้ DEFAULT เพราะยังไม่มีข้อมูล
    interval = DEFAULT_INTERVAL
    reason   = "เริ่มต้นระบบ"

    try:
        while True:
            # ── ตรวจตลาดปิด (เสาร์/อาทิตย์/daily close) ─────────────
            should_sleep, sleep_secs, sleep_reason = market_sleep_status()
            while should_sleep:
                chunk = min(1800, sleep_secs)  # รอสูงสุด 30 นาทีต่อรอบ
                mins_left = sleep_secs // 60
                console.print(f"  [dim]💤 {sleep_reason} — รอ {mins_left} นาที...[/dim]")
                await asyncio.sleep(chunk)
                should_sleep, sleep_secs, sleep_reason = market_sleep_status()

            # ── Auto-reconnect MT5 ถ้าหลุด ────────────────────────────────
            if not is_mt5_connected():
                console.print("  [yellow]⚠[/yellow]  MT5 หลุด — reconnect...\n")
                if not connect_mt5():
                    await asyncio.sleep(10)
                    continue

            open_pos = get_open_positions()
            hedge    = is_hedge_active()

            # ตรวจทั้ง 2 ทิศทาง — ถ้าทั้ง BUY และ SELL เปิดไม่ได้ ข้าม AI
            can_buy,  reason_buy  = check_open_slot("BUY")
            can_sell, reason_sell = check_open_slot("SELL")
            slots_full = (not can_buy) and (not can_sell)

            if slots_full:
                # ทั้งสองทิศทางปิดหมด — ข้าม AI ประหยัด token
                await run_status_cycle()
                interval = STATUS_INTERVAL
                reason   = f"slots full — {reason_buy} | {reason_sell}"
                if hedge:
                    reason += "  [hedge]"
                # Auto-pending รันเสมอแม้ slots จะเต็ม (pending ไม่ขึ้นกับ open slot)
                try:
                    p = auto_place_pending_orders(_last_chart_data or {}, _last_sentiment_data)
                    if p:
                        print_warning(f"Auto-pending: วาง {p} order ที่ key S/R levels (H4+Daily)")
                except Exception as pe:
                    logger.error(f"Auto-pending error: {pe}")
                # Range pending: ตรวจ stale + วาง ถ้า sideways
                try:
                    rp = manage_range_pending(_last_chart_data or {})
                    if rp:
                        print_warning(f"Range pending: วาง {rp} order ที่กรอบ sideways")
                except Exception as rpe:
                    logger.error(f"Range pending error: {rpe}")
                # Post-SL re-entry: หาจุดเข้าใหม่ที่ safe zone หลัง SL hit
                try:
                    sr = manage_sl_reentry(_last_chart_data or {})
                    if sr:
                        print_warning(f"Post-SL: วาง {sr} re-entry order ที่ safe zone")
                except Exception as sre:
                    logger.error(f"Post-SL re-entry error: {sre}")
            else:
                chart_data, sentiment_data = await run_cycle()
                if _net_degraded:
                    interval = NET_ERROR_INTERVAL
                    reason   = "Network degraded (CW+MA fail) — รอ 10 นาที"
                    logger.warning(f"Next interval: {interval}s — {reason}")
                else:
                    htf_zone = chart_data.get("htf_zone")
                    interval, reason = next_interval(chart_data, sentiment_data, htf_zone=htf_zone)

                    # ── Ready Mode: ราคาอยู่ที่ D1/W1 major zone ────────────
                    if htf_zone:
                        m5_pa = analyze_m5_pa()
                        # counter-pressure: ไม่มีข่าวสนับสนุนทิศทางที่ราคาวิ่งมา
                        sent_bias    = sentiment_data.get("bias", "NEUTRAL")
                        sent_conf    = sentiment_data.get("confidence", 0)
                        zone_type    = htf_zone["zone_type"]   # SUPPORT / RESISTANCE
                        # counter-pressure = ราคาลงแรงมา SUPPORT แต่ sentiment ไม่ bearish
                        counter_pres = (
                            (zone_type == "SUPPORT"    and sent_bias != "BEARISH") or
                            (zone_type == "RESISTANCE" and sent_bias != "BULLISH") or
                            sent_conf < 40
                        )
                        if not _ready_state["active"]:
                            _ready_state.update({
                                "active":    True,
                                "zone":      htf_zone,
                                "since":     _dt.now(),
                                "pa_watch":  0,
                                "miss_count": 0,
                            })
                            print_ready_mode_banner(htf_zone, "ENTER", m5_pa, counter_pres)
                            logger.warning(
                                f"[READY] เข้า Ready Mode: {htf_zone['tf']} "
                                f"{htf_zone['zone_type']} @ {htf_zone['level']}"
                            )
                        else:
                            _ready_state["pa_watch"]  += 1
                            _ready_state["miss_count"]  = 0
                            _ready_state["zone"]        = htf_zone
                            print_ready_mode_banner(htf_zone, "WATCHING", m5_pa, counter_pres)

                        # force fast interval
                        if interval > READY_INTERVAL:
                            interval = READY_INTERVAL
                            reason   = (f"⚡ READY MODE {htf_zone['tf']} {htf_zone['zone_type']} "
                                        f"@ {htf_zone['level']} — {reason}")

                        # auto-exit ถ้าดูนานเกินไป
                        if _ready_state["pa_watch"] >= READY_MAX_CYCLES:
                            _ready_state["active"] = False
                            _ready_state["zone"]   = None
                            print_ready_mode_banner(None, "EXIT")
                            logger.info("[READY] ออก Ready Mode — ครบ max cycles")

                    elif _ready_state["active"]:
                        # zone หายไป
                        _ready_state["miss_count"] += 1
                        if _ready_state["miss_count"] >= READY_MAX_MISS:
                            _ready_state["active"] = False
                            _ready_state["zone"]   = None
                            print_ready_mode_banner(None, "EXIT")
                            logger.info("[READY] ออก Ready Mode — zone ออกจากระยะ")

                    logger.info(f"Next interval: {interval}s — {reason}")

            # ── Weekly calendar pending (จันทร์เช้า) — รันเสมอไม่ขึ้นกับ slots ──
            global _last_weekly_pending_date
            # UTC date — every other clock in the trading path is UTC (market_clock, session
            # gates). Local date drifted the Monday straddle per host; UTC Monday is deterministic.
            today = _dt.now(_timezone.utc).date()
            if today.weekday() == 0 and today != _last_weekly_pending_date:
                _last_weekly_pending_date = today
                wkly = place_weekly_calendar_pending(_last_chart_data or {})
                if wkly:
                    print_warning(f"Weekly calendar pending: วาง {wkly} orders ตามปฏิทิน")
                else:
                    logger.info("Weekly calendar pending: ไม่วาง order (ดู system.log)")

            print_cycle_end(interval, reason)
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n  [dim]หยุดระบบโดยผู้ใช้[/dim]\n")
    finally:
        from agents.position_guardian import stop_guardian
        stop_guardian()        # หยุด guardian ก่อน disconnect MT5 (กัน guardian เรียก mt5 หลังตัด)
        from agents.regime_tick import stop_regime_tick
        stop_regime_tick()     # หยุด per-tick thread ก่อน disconnect MT5 เช่นกัน
        disconnect_mt5()


_PID_FILE = "logs/bot.pid"


def _acquire_lock() -> bool:
    """Write PID lock file. Returns False if another instance is already running."""
    os.makedirs("logs", exist_ok=True)
    if os.path.exists(_PID_FILE):
        try:
            existing_pid = int(open(_PID_FILE).read().strip())
            import psutil
            if psutil.pid_exists(existing_pid):
                try:
                    proc_name = psutil.Process(existing_pid).name().lower()
                    is_python = "python" in proc_name
                except Exception:
                    is_python = True  # assume it's ours if we can't check
                if is_python:
                    print(f"\n  ERROR: bot already running (PID {existing_pid})")
                    print(f"  Stop it first:  taskkill /F /PID {existing_pid}\n")
                    return False
        except Exception:
            pass  # stale lock — overwrite
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock():
    try:
        os.remove(_PID_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    if not _acquire_lock():
        sys.exit(1)
    try:
        asyncio.run(main())
    finally:
        _release_lock()
