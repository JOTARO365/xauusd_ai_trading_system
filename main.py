import argparse
import asyncio
import sys
import time
from datetime import date as _date
from loguru import logger
from connectors.price_feed import connect_mt5, disconnect_mt5, is_mt5_connected
from connectors.mt5_connector import get_open_positions, manage_breakeven, manage_dynamic_tp, manage_post_event_tp, count_protected_slots, is_hedge_active, check_open_slot
from agents.chart_watcher import analyze_chart
from agents.market_advisor import analyze_market_regime
from agents.news_gatherer import gather_news
from agents.analyst import analyze_sentiment
from agents.decision_maker import make_decision
from agents.reporter import log_trade, print_summary, scan_manual_orders
from agents.pending_manager import auto_place_pending_orders, place_weekly_calendar_pending, manage_range_pending, manage_sl_reentry
import agents.chart_watcher  as _cw_mod
import agents.market_advisor as _ma_mod
import agents.analyst        as _an_mod
import agents.decision_maker as _dm_mod
import agents.reporter       as _rp_mod
from agents.accountant import record_cycle
from utils.display import (
    console, print_header, print_cycle_start, print_cycle_end,
    print_step, print_signal_box, print_advisor_box,
    print_sentiment_box, print_decision_box, print_warning, print_error,
)
from utils.market_clock import next_interval, market_sleep_status
import config
from config import MONEY_MANAGEMENT

DEFAULT_INTERVAL  = 300
STATUS_INTERVAL   = 60
_cycle            = 0
_last_chart_data:     dict = {}
_last_sentiment_data: dict = {}
_last_weekly_pending_date: "_date | None" = None


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
                    help="Max open trades (default 2)")
    mm.add_argument("--sl",          type=int,   metavar="PIPS",
                    help="Default SL pips (default 1000)")
    mm.add_argument("--tp",          type=int,   metavar="PIPS",
                    help="Default TP pips (default 1500)")
    mm.add_argument("--rr",          type=float, metavar="RATIO",
                    help="Min Risk/Reward ratio (default 1.5)")

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
                        help="Confidence ขั้นต่ำเมื่อติด streak (default 75)")

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



async def run_status_cycle() -> None:
    """Lightweight cycle เมื่อ slots เต็ม — ข้าม AI agents"""
    config.reload_config()
    global _cycle
    _cycle += 1
    print_cycle_start(_cycle)

    open_pos  = get_open_positions()
    hedge     = is_hedge_active()
    can_buy,  rb = check_open_slot("BUY")
    can_sell, rs = check_open_slot("SELL")

    buy_count  = sum(1 for p in open_pos if p.get("direction") == "BUY")
    sell_count = sum(1 for p in open_pos if p.get("direction") == "SELL")
    max_dir    = MONEY_MANAGEMENT["max_open_trades"]

    buy_pnl  = sum(p.get("profit", 0) for p in open_pos if p.get("direction") == "BUY")
    sell_pnl = sum(p.get("profit", 0) for p in open_pos if p.get("direction") == "SELL")

    buy_tag  = f"[green]BUY {buy_count}/{max_dir}  P&L:{buy_pnl:+.2f}[/green]" if can_buy  \
               else f"[dim]BUY {buy_count}/{max_dir}  P&L:{buy_pnl:+.2f}  ✗[/dim]"
    sell_tag = f"[green]SELL {sell_count}/{max_dir}  P&L:{sell_pnl:+.2f}[/green]" if can_sell \
               else f"[dim]SELL {sell_count}/{max_dir}  P&L:{sell_pnl:+.2f}  ✗[/dim]"

    hedge_tag = f"  [bold cyan]⇄ Hedge[/bold cyan]" if hedge else ""

    console.print(
        f"  [bold yellow]⏸[/bold yellow]  "
        f"{buy_tag}   {sell_tag}{hedge_tag}  — skip AI\n"
    )

    print_step(5, "running", "กำลังตรวจสอบ positions...")
    try:
        be = manage_breakeven()
        if be:
            print_warning(f"Breakeven: ขยับ SL หน้าทุน {be} position")
        dtp = manage_dynamic_tp()
        if dtp:
            print_warning(f"Dynamic TP: ขยับ TP ออก {dtp} position (momentum แรง)")
        ptp = manage_post_event_tp(_last_chart_data)
        if ptp:
            print_warning(f"Post-event TP: ตั้ง TP {ptp} position (momentum สงบแล้ว)")
        n = scan_manual_orders(_last_chart_data or None)
        detail = "done" + (f"  +{n} manual" if n else "")
        print_step(5, "done", detail)
        if n:
            print_warning(f"พบ manual order {n} รายการ — บันทึก context แล้ว")
        # Range pending — ตรวจและยกเลิก stale orders แม้ในรอบ status
        try:
            rp = manage_range_pending(_last_chart_data or {})
            if rp:
                print_warning(f"Range pending: วาง {rp} order ที่กรอบ sideways")
        except Exception as rpe:
            logger.error(f"Range pending error: {rpe}")
        # Post-SL re-entry — หาจุดเข้าใหม่ที่ safe zone หลัง SL hit
        try:
            sr = manage_sl_reentry(_last_chart_data or {})
            if sr:
                print_warning(f"Post-SL: วาง {sr} re-entry order ที่ safe zone")
        except Exception as sre:
            logger.error(f"Post-SL re-entry error: {sre}")
        print_summary()
    except Exception as e:
        print_step(5, "error", str(e)[:60])
        logger.error(f"Status cycle error: {e}")


async def run_cycle() -> tuple[dict, dict]:
    """รัน 1 รอบ คืน (chart_data, sentiment_data) สำหรับคำนวณ interval"""
    config.reload_config()
    global _cycle, _last_chart_data, _last_sentiment_data
    _cycle += 1
    print_cycle_start(_cycle)

    _lat_cw = _lat_ma = _lat_an = _lat_dm = 0   # latencies (ms)

    # ── Step 1: Chart Watcher ──────────────────────────────────────
    print_step(0, "running", "กำลังดึงข้อมูลกราฟ...")
    try:
        _t = time.monotonic()
        chart_data = analyze_chart()
        _lat_cw = int((time.monotonic() - _t) * 1000)
        _last_chart_data = chart_data
        signal = chart_data.get("signal", "NO_TRADE")
        conf   = chart_data.get("confidence", 0)
        print_step(0, "done", f"{signal}  ({conf}%)")
        print_signal_box(chart_data)
    except Exception as e:
        print_step(0, "error", str(e)[:60])
        logger.error(f"Chart Watcher error: {e}")
        chart_data = {"signal": "NO_TRADE", "confidence": 0,
                      "sl_pips": 1000, "tp_pips": 1500}

    # ── Step 2: Market Advisor ─────────────────────────────────────
    print_step(1, "running", "กำลังวิเคราะห์ market regime...")
    try:
        _t = time.monotonic()
        advisor_data = analyze_market_regime(chart_data)
        _lat_ma = int((time.monotonic() - _t) * 1000)
        regime = advisor_data.get("regime", "—")
        conf   = advisor_data.get("regime_confidence", 0)
        bias   = advisor_data.get("bias", "—")
        print_step(1, "done", f"{regime}  ({conf}%)  Bias: {bias}")
        print_advisor_box(advisor_data)
    except Exception as e:
        print_step(1, "error", str(e)[:60])
        logger.error(f"Market Advisor error: {e}")
        advisor_data = {}

    # ── Step 3: News Gatherer ──────────────────────────────────────
    print_step(2, "running", "กำลังดึงข่าว Twitter/X...")
    try:
        news_data = await gather_news()
        print_step(2, "done", f"{news_data.get('count', 0)} tweet")
    except Exception as e:
        print_step(2, "error", str(e)[:60])
        logger.error(f"News Gatherer error: {e}")
        news_data = {"tweets": [], "count": 0}

    # ── Step 4: Sentiment Analyst ──────────────────────────────────
    print_step(3, "running", "กำลังวิเคราะห์ sentiment...")
    try:
        _t = time.monotonic()
        sentiment_data = analyze_sentiment(news_data, chart_data)
        _lat_an = int((time.monotonic() - _t) * 1000)
        sent  = sentiment_data.get("sentiment", "NEUTRAL")
        sconf = sentiment_data.get("confidence", 0)
        sentiment_data["news_count"] = news_data.get("count", 0)
        _last_sentiment_data = sentiment_data
        print_step(3, "done", f"{sent}  ({sconf}%)")
        print_sentiment_box(sentiment_data)
    except Exception as e:
        print_step(3, "error", str(e)[:60])
        logger.error(f"Sentiment error: {e}")
        sentiment_data = {"sentiment": "NEUTRAL", "confidence": 0,
                          "summary": "", "tweet_count": 0}

    # ── Step 5: Decision Maker ─────────────────────────────────────
    print_step(4, "running", "กำลังตัดสินใจ...")
    try:
        _t = time.monotonic()
        decision = make_decision(chart_data, sentiment_data, advisor_data)
        _lat_dm = int((time.monotonic() - _t) * 1000)
        action = decision.get("action", "SKIP")
        step_detail = f"EXECUTE {decision.get('direction','')}" if action == "EXECUTE" else "SKIP"
        step_status = "done" if action == "EXECUTE" else "skip"
        print_step(4, step_status, step_detail)
        print_decision_box(decision)
    except Exception as e:
        print_step(4, "error", str(e)[:60])
        logger.error(f"Decision Maker error: {e}")
        decision = {"action": "SKIP", "reason": str(e)}

    # ── Step 6: Reporter ───────────────────────────────────────────
    print_step(5, "running", "กำลังบันทึกผล...")
    try:
        be = manage_breakeven()
        if be:
            print_warning(f"Breakeven: ขยับ SL หน้าทุน {be} position")
        dtp = manage_dynamic_tp()
        if dtp:
            print_warning(f"Dynamic TP: ขยับ TP ออก {dtp} position (momentum แรง)")
        ptp = manage_post_event_tp(chart_data)
        if ptp:
            print_warning(f"Post-event TP: ตั้ง TP {ptp} position (momentum สงบแล้ว)")
        log_trade(decision)
        n = scan_manual_orders(chart_data)
        detail = "done" + (f" (+{n} manual)" if n else "")
        print_step(5, "done", detail)
        if n:
            print_warning(f"พบ manual order {n} รายการ — บันทึก context ทาง technical แล้ว")
        # ── Auto-pending: วาง limit orders ที่ key S/R (H4 + Daily) ──
        try:
            p = auto_place_pending_orders(chart_data, sentiment_data)
            if p:
                print_warning(f"Auto-pending: วาง {p} order ที่ key S/R levels (H4+Daily)")
        except Exception as pe:
            logger.error(f"Auto-pending error: {pe}")
        # ── Range pending: sideways กรอบอัตโนมัติ (แยกจาก weekly+auto) ──
        try:
            rp = manage_range_pending(chart_data)
            if rp:
                print_warning(f"Range pending: วาง {rp} order ที่กรอบ sideways")
        except Exception as rpe:
            logger.error(f"Range pending error: {rpe}")
        # ── Post-SL re-entry: หาจุดเข้าใหม่ที่ safe zone หลัง SL hit ──
        try:
            sr = manage_sl_reentry(chart_data)
            if sr:
                print_warning(f"Post-SL: วาง {sr} re-entry order ที่ safe zone")
        except Exception as sre:
            logger.error(f"Post-SL re-entry error: {sre}")
        print_summary()
    except Exception as e:
        print_step(5, "error", str(e)[:60])
        logger.error(f"Reporter error: {e}")

    # ── Accounting ─────────────────────────────────────────────────
    try:
        _ticket = (
            decision.get("order", {}).get("ticket")
            if decision.get("action") == "EXECUTE" else None
        )
        record_cycle(
            symbol       = config.SYMBOL,
            agent_usages = {
                "chart_watcher":  ("claude-sonnet-4-6", _cw_mod._last_usage),
                "market_advisor": ("claude-sonnet-4-6", _ma_mod._last_usage),
                "analyst":        ("claude-sonnet-4-6", _an_mod._last_usage),
                "decision_maker": ("claude-sonnet-4-6", _dm_mod._last_usage),
                "reporter":       ("claude-haiku-4-5-20251001", _rp_mod._last_usage),
            },
            ticket       = _ticket,
            latencies_ms = {
                "chart_watcher":  _lat_cw,
                "market_advisor": _lat_ma,
                "analyst":        _lat_an,
                "decision_maker": _lat_dm,
            },
        )
    except Exception as e:
        logger.error(f"Accounting error: {e}")

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

    # ── DB connectivity check ──────────────────────────────────
    from db.connection import is_available, get_url
    if is_available():
        console.print(f"  [green]✓[/green]  Database: {get_url()}\n")
        # sync MT5 history → DB ตอน startup (เฉพาะ trades ที่ยังไม่มีใน DB)
        from db.sync import sync_mt5_history_to_db
        n = sync_mt5_history_to_db(days=365)
        if n:
            console.print(f"  [green]✓[/green]  Synced {n} trade(s) from MT5 → Database\n")
    else:
        console.print(f"  [yellow]⚠[/yellow]  Database ต่อไม่ได้ ({get_url()}) — บันทึกลง JSON อย่างเดียว\n")

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
                interval, reason = next_interval(chart_data, sentiment_data)
                logger.info(f"Next interval: {interval}s — {reason}")

            # ── Weekly calendar pending (จันทร์เช้า) — รันเสมอไม่ขึ้นกับ slots ──
            global _last_weekly_pending_date
            today = _date.today()
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
        disconnect_mt5()


if __name__ == "__main__":
    asyncio.run(main())
