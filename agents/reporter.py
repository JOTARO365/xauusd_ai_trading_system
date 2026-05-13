import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
import anthropic
import config as _cfg
from connectors.price_feed import get_account_info
from connectors.mt5_connector import (
    get_open_positions, get_mt5_history, get_closed_deal_pnl,
    get_pending_orders, count_protected_slots,
)
from loguru import logger


def _log_file() -> str:
    sym = _cfg.SYMBOL.upper().replace("/", "")
    return "logs/trades.json" if sym == "XAUUSD" else f"logs/{sym.lower()}_trades.json"
_REPORTER_PROMPT  = Path("agents/prompts/reporter.md").read_text(encoding="utf-8")
_ANALYSIS_COOLDOWN = 900  # วิเคราะห์ใหม่ได้ทุก 15 นาที
_last_analysis_at: datetime | None = None
_last_usage = None   # set after each API call — read by accountant


def _load_log() -> dict:
    _empty = {"trades": [], "summary": {"total": 0, "win": 0, "loss": 0, "total_pnl": 0.0}}
    path = _log_file()
    if not os.path.exists(path):
        return _empty
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return _empty


def _save_log(data: dict):
    os.makedirs("logs", exist_ok=True)
    with open(_log_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _known_tickets(log: dict) -> set:
    return {str(t.get("ticket")) for t in log.get("trades", []) if t.get("ticket")}


# ─────────────────────────────────────────────────────────────
#  MANUAL ORDER SCANNER
# ─────────────────────────────────────────────────────────────

def _best_scan_setup(scan: dict, direction: str) -> dict | None:
    """คืน setup ที่ score สูงสุดในทิศทางที่ต้องการ หรือ None"""
    if not scan:
        return None
    setups = [s for s in scan.get("setups", []) if s.get("direction") == direction.upper()]
    if not setups:
        setups = scan.get("setups", [])
    return max(setups, key=lambda x: x.get("score", 0)) if setups else None


def _infer_manual_analysis(price: float, direction: str, chart_data: dict | None) -> dict:
    """
    วิเคราะห์ context ทาง technical ของ manual order จาก chart_data ปัจจุบัน
    ถ้าไม่มี chart_data คืนข้อมูลเปล่า
    """
    if not chart_data:
        return {
            "technical_signal":     "MANUAL",
            "technical_confidence": None,
            "trend":                None,
            "sr_zone":              None,
            "sr_strength":          None,
            "pa_action":            "NONE",
            "pa_zone":              "—",
            "pa_level":             None,
            "pa_patterns":          [],
            "entry_type":           "MANUAL",
            "manual_analysis":      "ไม่มีข้อมูล chart ณ เวลาที่ตรวจพบ",
        }

    ind    = chart_data.get("indicators", {})
    h4     = ind.get("h4", {})
    trend  = chart_data.get("trend", "UNKNOWN")
    sr_z   = chart_data.get("sr_zone",     "NONE")
    sr_s   = chart_data.get("sr_strength", "NORMAL")

    sr_actions  = chart_data.get("sr_actions", [])
    candle_pat  = chart_data.get("candle_pat", {})
    scan        = chart_data.get("scan", {})

    pa_patterns = candle_pat.get("patterns", [])
    if sr_actions:
        pa_action = sr_actions[0].get("action", "NONE")
        pa_zone   = sr_actions[0].get("zone",   "—")
        pa_level  = sr_actions[0].get("level",  None)
    else:
        best_setup = _best_scan_setup(scan, direction)
        if best_setup:
            pa_action = best_setup["type"]
            pa_zone   = f"{best_setup['tf']}_{best_setup['type']}"
            pa_level  = best_setup.get("level")
        else:
            pa_action = "NONE"
            pa_zone   = "—"
            pa_level  = None

    # สร้างคำอธิบาย
    notes = []
    notes.append(f"H4 Trend: {trend}")
    notes.append(f"EMA200 H4: {h4.get('ema200', '—')}")
    notes.append(f"RSI H4: {h4.get('rsi', '—')}")
    if sr_z and sr_z != "NONE":
        notes.append(f"SR Zone: {sr_z} ({sr_s})")
    if pa_action != "NONE":
        notes.append(f"PA: {pa_action} @ {pa_level}")
    if pa_patterns and pa_patterns != ["NORMAL"]:
        notes.append(f"Candle: {', '.join(pa_patterns)}")

    best_setups = [
        s for s in scan.get("setups", [])
        if s["direction"] == direction.upper()
    ]
    if best_setups:
        top = best_setups[0]
        notes.append(f"Setup: {top['type']} score={top['score']}")

    return {
        "technical_signal":     direction,
        "technical_confidence": chart_data.get("confidence"),
        "trend":                trend,
        "sr_zone":              sr_z,
        "sr_strength":          sr_s,
        "pa_action":            pa_action,
        "pa_zone":              pa_zone,
        "pa_level":             pa_level,
        "pa_patterns":          pa_patterns,
        "entry_type":           "MANUAL",
        "manual_analysis":      " | ".join(notes),
    }


def _get_close_times(days: int = 7) -> dict[str, str]:
    """ดึง close_time ของ positions ที่ปิดแล้ว → {position_id: iso_datetime}"""
    import MetaTrader5 as mt5
    from datetime import timedelta
    date_from = datetime.now() - timedelta(days=days)
    close_map: dict[str, str] = {}
    try:
        all_deals = mt5.history_deals_get(date_from, datetime.now())
        if all_deals:
            for d in all_deals:
                if d.entry == 1:  # DEAL_ENTRY_OUT
                    close_map[str(d.position_id)] = datetime.fromtimestamp(d.time).isoformat()
    except Exception:
        pass
    return close_map


def _sync_closed_trades(log: dict):
    """ตรวจ trade ที่ยัง OPEN ใน log — ถ้า MT5 ปิดไปแล้วให้อัปเดต status + PnL + close_time"""
    open_in_log = [t for t in log.get("trades", []) if t.get("status") == "OPEN" and t.get("ticket")]
    if not open_in_log:
        return

    open_tickets  = {str(p["ticket"]) for p in get_open_positions()}
    close_map     = _get_close_times()
    changed       = False

    for t in open_in_log:
        tk = str(t.get("ticket"))
        if tk in open_tickets:
            continue  # ยังเปิดอยู่

        pnl = get_closed_deal_pnl(t["ticket"])
        if pnl is None:
            continue  # ยังหาข้อมูลไม่ได้

        t["status"] = "CLOSED"
        t["pnl"]    = pnl
        if not t.get("close_time"):
            t["close_time"] = close_map.get(tk, datetime.now().isoformat())
        changed = True
        logger.info(f"Trade closed — Ticket:{t['ticket']} PnL:{pnl:+.2f}")
        _db_write_trade(t)

    if changed:
        closed = [t for t in log["trades"] if t.get("status") == "CLOSED"]
        wins   = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
        losses = sum(1 for t in closed if (t.get("pnl") or 0) < 0)
        log["summary"]["total"]     = len(closed)
        log["summary"]["win"]       = wins
        log["summary"]["loss"]      = losses
        log["summary"]["total_pnl"] = round(sum(t.get("pnl") or 0 for t in closed), 2)
        _save_log(log)


def _sync_pending_orders(log: dict):
    """
    ตรวจ PENDING trades ใน log:
    - ยังอยู่ใน MT5 pending list → ข้าม (รอ fill)
    - อยู่ใน MT5 open positions (ticket ตรงกัน) → OPEN
    - อยู่ใน deal history ว่าถูก fill แล้ว → OPEN (fallback สำหรับ broker ที่ position ticket ≠ order ticket)
    - ไม่พบที่ไหนเลย → CANCELLED
    """
    pending_in_log = [t for t in log.get("trades", [])
                      if t.get("status") == "PENDING" and t.get("ticket")]
    if not pending_in_log:
        return

    mt5_pending  = {str(p["ticket"]) for p in get_pending_orders()}
    open_pos     = get_open_positions()
    mt5_open     = {str(p["ticket"]): p for p in open_pos}
    # deal history: set of order tickets ที่ถูก fill แล้ว (entry deal)
    recent_deals = get_mt5_history(days=7)
    filled_order_tickets = {str(d["ticket"]) for d in recent_deals}

    changed = False
    for t in pending_in_log:
        tk = str(t.get("ticket"))
        if tk in mt5_pending:
            continue  # ยังรอ fill อยู่

        if tk in mt5_open:
            # position ticket == order ticket (กรณีปกติ)
            t["status"]      = "OPEN"
            t["entry_price"] = mt5_open[tk].get("open_price")
            changed = True
            logger.info(f"Pending filled → OPEN (position match): ticket={tk}")
        elif tk in filled_order_tickets:
            # filled แต่ position ticket ต่างกัน (ECN broker edge case)
            # หา open_price จาก deal history
            deal = next((d for d in recent_deals if str(d["ticket"]) == tk), None)
            t["status"]      = "OPEN"
            t["entry_price"] = deal["price"] if deal else None
            changed = True
            logger.info(f"Pending filled → OPEN (deal history): ticket={tk}")
        else:
            t["status"] = "CANCELLED"
            changed = True
            logger.info(f"Pending expired/cancelled: ticket={tk}")

    if changed:
        _save_log(log)


def count_pending_this_week() -> int:
    """นับ pending orders ที่ยังเปิดอยู่จริงใน MT5 (ไม่นับที่ expired/cancelled/filled แล้ว)"""
    from connectors.mt5_connector import get_pending_orders
    return len(get_pending_orders())


def count_pending_by_direction() -> dict:
    """นับ pending orders แยกตามทิศทาง — คืน {"BUY": n, "SELL": n}"""
    from connectors.mt5_connector import get_pending_orders
    orders = get_pending_orders()
    buy_count  = sum(1 for o in orders if "BUY"  in (o.get("pending_type") or ""))
    sell_count = sum(1 for o in orders if "SELL" in (o.get("pending_type") or ""))
    return {"BUY": buy_count, "SELL": sell_count}


def scan_manual_orders(chart_data: dict | None = None) -> int:
    """
    ตรวจหา order ใน MT5 ที่ไม่ได้เปิดโดยระบบ AI → บันทึกลง log
    Returns: จำนวน manual order ที่พบใหม่
    """
    log     = _load_log()
    _sync_closed_trades(log)    # อัปเดต PnL/status ของ trade ที่ปิดแล้ว
    _sync_pending_orders(log)   # ตรวจ pending filled / expired
    known   = _known_tickets(log)
    mt5_hist = get_mt5_history(days=60)
    new_count = 0

    for deal in mt5_hist:
        ticket_str = str(deal["ticket"])
        if ticket_str in known:
            continue
        if deal["source"] != "MANUAL":
            continue   # ระบบ AI เปิดเองแต่ log หาย — ไม่จัดเป็น manual

        direction = deal["direction"]
        entry_ts  = datetime.fromtimestamp(deal["time"]).isoformat() if deal["time"] else datetime.now().isoformat()

        analysis  = _infer_manual_analysis(deal["price"], direction, chart_data)

        trade_entry = {
            # ── Order info ────────────────────────────────
            "source":      "MANUAL",
            "timestamp":   entry_ts,
            "ticket":      deal["ticket"],
            "direction":   direction,
            "lot":         deal["lot"],
            "entry_price": deal["price"],
            "sl":          deal.get("sl"),
            "tp":          deal.get("tp"),
            # ── Technical context (วิเคราะห์ ณ เวลาที่ตรวจพบ) ─
            "technical_signal":     analysis["technical_signal"],
            "technical_confidence": analysis["technical_confidence"],
            "trend":                analysis["trend"],
            "sr_zone":              analysis["sr_zone"],
            "sr_strength":          analysis["sr_strength"],
            "pa_action":            analysis["pa_action"],
            "pa_zone":              analysis["pa_zone"],
            "pa_level":             analysis["pa_level"],
            "pa_patterns":          analysis["pa_patterns"],
            "entry_type":           "MANUAL",
            "sentiment":            None,
            # ── Manual-specific ───────────────────────────
            "manual_analysis": analysis["manual_analysis"],
            "manual_reason":   deal.get("comment", ""),   # comment จาก MT5
            # ── Result ────────────────────────────────────
            "status": "OPEN",
            "pnl":    None,
        }

        log["trades"].append(trade_entry)
        log["summary"]["total"] += 1
        new_count += 1
        logger.info(f"Manual order detected — Ticket:{deal['ticket']} {direction} @ {deal['price']}")

    if new_count:
        _save_log(log)

    # อัปเดต SL/TP ของ manual orders จาก open positions
    _sync_manual_sl_tp(log)

    return new_count


def _sync_manual_sl_tp(log: dict):
    """อัปเดต SL/TP ของ ALL open trades (MANUAL + SYSTEM) จาก MT5 positions"""
    positions = get_open_positions()
    pos_map = {str(p["ticket"]): p for p in positions}
    changed = False

    for t in log["trades"]:
        if t.get("status") != "OPEN":
            continue
        tk = str(t.get("ticket"))
        if tk in pos_map:
            p = pos_map[tk]
            new_sl = p["sl"] if p["sl"] != 0.0 else None
            new_tp = p["tp"] if p["tp"] != 0.0 else None
            if t.get("sl") != new_sl or t.get("tp") != new_tp:
                t["sl"] = new_sl
                t["tp"] = new_tp
                changed = True

    if changed:
        _save_log(log)


# ─────────────────────────────────────────────────────────────
#  LOG SYSTEM TRADE
# ─────────────────────────────────────────────────────────────

def log_trade(decision_result: dict):
    if decision_result.get("action") != "EXECUTE":
        return

    log   = _load_log()
    order = decision_result.get("order", {})
    if not order.get("success"):
        return

    tech = decision_result.get("technical", {})

    sr_actions  = tech.get("sr_actions", [])
    candle_pat  = tech.get("candle_pat", {})
    scan        = tech.get("scan", {})
    direction   = decision_result.get("direction", "")
    pa_patterns = candle_pat.get("patterns", [])

    if sr_actions:
        pa_action = sr_actions[0].get("action", "NONE")
        pa_zone   = sr_actions[0].get("zone",   "—")
        pa_level  = sr_actions[0].get("level",  None)
    else:
        best_setup = _best_scan_setup(scan, direction)
        if best_setup:
            pa_action = best_setup["type"]
            pa_zone   = f"{best_setup['tf']}_{best_setup['type']}"
            pa_level  = best_setup.get("level")
        else:
            pa_action = "NONE"
            pa_zone   = "—"
            pa_level  = None

    entry_type = tech.get("entry_type", "NONE")
    if entry_type == "NONE":
        best_setup = _best_scan_setup(scan, direction)
        if best_setup:
            entry_type = best_setup["type"]

    account  = get_account_info()
    ticket   = order.get("ticket")
    sent_obj = decision_result.get("sentiment") or {}
    trade_entry = {
        # ── Source ────────────────────────────────────
        "source":           "SYSTEM",
        "symbol":           _cfg.SYMBOL,
        "strategy_version": 2,
        # ── Order info ────────────────────────────────
        "timestamp":   datetime.now().isoformat(),
        "ticket":      ticket,
        "direction":   order.get("direction"),
        "lot":         order.get("lot"),
        "entry_price": order.get("price"),
        "sl":          order.get("sl"),
        "tp":          order.get("tp"),
        # ── Signal ────────────────────────────────────
        "technical_signal":     tech.get("signal"),
        "technical_confidence": tech.get("confidence"),
        "trend":                tech.get("trend"),
        "entry_type":           entry_type,
        "sentiment":            sent_obj.get("sentiment"),
        # ── Price action ──────────────────────────────
        "pa_action":   pa_action,
        "pa_zone":     pa_zone,
        "pa_level":    pa_level,
        "pa_patterns": pa_patterns,
        "sr_zone":     tech.get("sr_zone"),
        "sr_strength": tech.get("sr_strength"),
        # ── Analysis (Claude's decision reasoning) ────
        "analysis":    decision_result.get("analysis", ""),
        # ── Manual fields (ว่างสำหรับ system trades) ─
        "manual_analysis": None,
        "manual_reason":   None,
        # ── Account snapshot ──────────────────────────
        "balance_before": account.get("balance"),
        # ── Result ────────────────────────────────────
        "status": "OPEN",
        "pnl":    None,
    }

    # Upsert: update existing skeleton entry if ticket already in log (e.g. added by dashboard sync)
    for i, t in enumerate(log["trades"]):
        if t.get("ticket") == ticket:
            log["trades"][i].update(trade_entry)
            _save_log(log)
            logger.info(f"System trade updated — Ticket:{ticket} | PA:{pa_action} | Type:{entry_type}")
            _db_write_trade(trade_entry)
            return

    log["trades"].append(trade_entry)
    log["summary"]["total"] += 1
    _save_log(log)
    logger.info(f"System trade logged — Ticket:{ticket} | PA:{pa_action} | Type:{entry_type}")
    _db_write_trade(trade_entry)


def _db_write_trade(trade: dict) -> None:
    try:
        from db.writer import write_trade
        write_trade(trade)
    except Exception as e:
        logger.debug(f"DB trade write skipped: {e}")


# ─────────────────────────────────────────────────────────────
#  LOG PENDING ORDER
# ─────────────────────────────────────────────────────────────

def log_pending_order(decision_result: dict):
    """บันทึก pending order ลง trades.json"""
    if decision_result.get("action") != "PENDING":
        return

    order = decision_result.get("order", {})
    if not order.get("success"):
        return

    log  = _load_log()
    tech = decision_result.get("technical", {})
    pt   = order.get("pending_type", "")

    trade_entry = {
        "source":        "SYSTEM",
        "symbol":        _cfg.SYMBOL,
        "order_type":    f"PENDING_{pt}",
        "timestamp":     datetime.now().isoformat(),
        "ticket":        order.get("ticket"),
        "pending_type":  pt,
        "pending_price": order.get("price"),
        "direction":     "BUY" if pt.startswith("BUY") else "SELL",
        "lot":           order.get("lot"),
        "entry_price":   None,
        "sl":            order.get("sl"),
        "tp":            order.get("tp"),
        "expiry":        order.get("expiry"),
        "technical_signal":     tech.get("signal"),
        "technical_confidence": tech.get("confidence"),
        "trend":                tech.get("trend"),
        "entry_type":           "PENDING",
        "sr_zone":              tech.get("sr_zone"),
        "sr_strength":          tech.get("sr_strength"),
        "sentiment":            decision_result.get("sentiment", {}).get("sentiment"),
        "strategy_version":     2,
        "manual_analysis": None,
        "manual_reason":   None,
        "status": "PENDING",
        "pnl":    None,
    }

    log["trades"].append(trade_entry)
    _save_log(log)
    logger.info(f"Pending order logged — Ticket:{order.get('ticket')} {pt} @ {order.get('price')}")


# ─────────────────────────────────────────────────────────────
#  HISTORY SUMMARY (for Decision Maker)
# ─────────────────────────────────────────────────────────────

def get_trade_history_summary() -> dict:
    trades: list = []
    try:
        from db.reader import get_trades
        rows = get_trades(_cfg.SYMBOL)
        if rows is not None:
            trades = rows
        else:
            raise RuntimeError("DB not available")
    except Exception:
        trades = _load_log().get("trades", [])

    closed = [t for t in trades if t.get("status") == "CLOSED"]
    today_str = date.today().isoformat()

    today_trades = [t for t in trades if t.get("timestamp", "").startswith(today_str)]
    today_pnl    = sum(t.get("pnl") or 0 for t in today_trades if t.get("pnl") is not None)

    last_10      = closed[-10:]
    last_10_win  = sum(1 for t in last_10 if (t.get("pnl") or 0) > 0)
    last_10_loss = len(last_10) - last_10_win
    last_10_winrate = round(last_10_win / len(last_10) * 100, 1) if last_10 else 0

    # นับ losing streak เฉพาะ order ของวันนี้เท่านั้น — reset ทุกวัน
    today_closed  = [t for t in closed if t.get("timestamp", "").startswith(today_str)]
    losing_streak = 0
    for t in reversed(today_closed):
        if (t.get("pnl") or 0) < 0:
            losing_streak += 1
        else:
            break

    recent_trades_text = ""
    for t in closed[-5:]:
        pnl    = t.get("pnl") or 0
        result = "WIN" if pnl > 0 else "LOSS"
        src    = t.get("source", "SYS")[:3].upper()
        entry  = t.get("entry_type") or "—"
        pa     = t.get("pa_action")  or "—"
        sr     = t.get("sr_zone")    or "—"
        trend  = t.get("trend")      or "—"
        recent_trades_text += (
            f"  [{t['timestamp'][:16]}] [{src}] {t.get('direction')} "
            f"Entry:{entry} PA:{pa} SR:{sr} Trend:{trend} "
            f"Tech:{t.get('technical_signal')} Sent:{t.get('sentiment')} "
            f"→ {pnl:+.2f} ({result})\n"
        )

    # ── Entry type performance — v2 trades only ─────────────────
    # v1 = old code (EMA_CROSS era), v2 = current strategy (Issues #1-5)
    _REMOVED_SIGNALS = {"EMA_CROSS", "MACD_CROSS"}   # signals no longer in system
    _V2_MIN_TRADES   = 5                              # ต้องมีอย่างน้อย N trades จึงแสดง WR

    closed_v2 = [t for t in closed if t.get("strategy_version", 1) == 2]
    closed_v1_count = len(closed) - len(closed_v2)

    entry_perf: dict[str, dict] = {}
    for t in closed_v2:
        et = t.get("entry_type") or "UNKNOWN"
        if et in _REMOVED_SIGNALS:
            continue
        if et not in entry_perf:
            entry_perf[et] = {"count": 0, "wins": 0, "pnl": 0.0}
        entry_perf[et]["count"] += 1
        if (t.get("pnl") or 0) > 0:
            entry_perf[et]["wins"] += 1
        entry_perf[et]["pnl"] = round(entry_perf[et]["pnl"] + (t.get("pnl") or 0), 2)

    if not closed_v2:
        entry_perf_text = f"  [v2 system: 0 trades — building history | v1 legacy: {closed_v1_count} trades (excluded)]\n"
    else:
        header = f"  [v2: {len(closed_v2)} trades"
        if closed_v1_count:
            header += f" | v1 legacy excluded: {closed_v1_count}]"
        else:
            header += "]"
        entry_perf_text = header + "\n"
        for et, s in sorted(entry_perf.items(), key=lambda x: -x[1]["pnl"]):
            wr = round(s["wins"] / s["count"] * 100, 1) if s["count"] else 0
            wr_note = "" if s["count"] >= _V2_MIN_TRADES else " (low sample)"
            entry_perf_text += f"  {et:<22} {s['count']} trades | WR={wr}%{wr_note} | P&L={s['pnl']:+.2f}\n"

    return {
        "today_trades":       len(today_trades),
        "today_pnl":          round(today_pnl, 2),
        "total_closed":       len(closed),
        "last_10_winrate":    last_10_winrate,
        "last_10_win":        last_10_win,
        "last_10_loss":       last_10_loss,
        "losing_streak":      losing_streak,
        "recent_trades":      closed[-5:],       # trade objects สำหรับ display โดยตรง
        "recent_trades_text": recent_trades_text or "  ยังไม่มีประวัติการเทรด",
        "entry_perf_text":    entry_perf_text    or "  ยังไม่มีข้อมูล",
    }


# ─────────────────────────────────────────────────────────────
#  AI PERFORMANCE ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyze_performance() -> str:
    """เรียก Claude ด้วย reporter.md + ข้อมูลจริงจาก trades.json + balance MT5
    คืนค่า report text หรือ "" ถ้า cooldown ยังไม่หมดหรือข้อมูลน้อยเกินไป
    """
    global _last_analysis_at
    now = datetime.now()
    if _last_analysis_at and (now - _last_analysis_at) < timedelta(seconds=_ANALYSIS_COOLDOWN):
        return ""

    log    = _load_log()
    closed = [t for t in log.get("trades", []) if t.get("status") == "CLOSED"]
    if len(closed) < 3:
        return ""  # ข้อมูลน้อยเกินไป

    from config import START_BALANCE
    account       = get_account_info()
    open_pos      = get_open_positions()
    history       = get_trade_history_summary()
    open_pnl      = sum(p.get("profit", 0) for p in open_pos)
    currency      = account.get("currency", "USD")
    balance       = account.get("balance", 0)
    equity        = account.get("equity", 0)

    # คำนวณ expectancy
    wins   = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) < 0]
    avg_win  = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    wr       = len(wins) / len(closed) if closed else 0
    expectancy = round((wr * avg_win) + ((1 - wr) * avg_loss), 2)
    drawdown_pct = round((1 - balance / START_BALANCE) * 100, 1) if START_BALANCE > 0 else 0

    user_msg = f"""วิเคราะห์ performance จากข้อมูลต่อไปนี้:

=== บัญชี (ข้อมูลจริงจาก MT5) ===
Balance       : {balance:,.2f} {currency}
Equity        : {equity:,.2f} {currency}
Open P&L      : {open_pnl:+.2f} {currency}
Start Balance : {START_BALANCE:,.2f} {currency}  ← ทุนเริ่มต้นจริง (ใช้ค่านี้คำนวณ drawdown)
Drawdown      : {drawdown_pct:.1f}% (คำนวณจาก Start Balance แล้ว)

=== สถิติรวม ===
Total Closed  : {len(closed)} trades
Win Rate      : {round(wr*100, 1)}%  ({len(wins)} W / {len(losses)} L)
Expectancy    : {expectancy:+.2f} {currency}
Today P&L     : {history['today_pnl']:+.2f}
Losing Streak : {history['losing_streak']}

=== Strategy Performance (entry type) ===
{history['entry_perf_text']}
=== 5 Trade ล่าสุด ===
{history['recent_trades_text']}
=== ประวัติการเทรดทั้งหมด (trades.json, {len(closed)} trades ล่าสุด) ===
{json.dumps(closed[-30:], ensure_ascii=False, indent=2)}
"""

    global _last_usage
    _last_usage = None
    try:
        from config import ANTHROPIC_API_KEY
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=[{"type": "text", "text": _REPORTER_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        _last_usage = response.usage
        report = response.content[0].text
        _last_analysis_at = now
        logger.info("Performance analysis completed")
        return report
    except Exception as e:
        logger.error(f"Reporter analysis error: {e}")
        return ""


# ─────────────────────────────────────────────────────────────
#  TERMINAL SUMMARY
# ─────────────────────────────────────────────────────────────

def print_summary():
    from utils.display import print_account_summary, print_performance_report
    account        = get_account_info()
    open_positions = get_open_positions()
    history        = get_trade_history_summary()
    protected      = count_protected_slots()
    print_account_summary(account, open_positions, history, protected)

    report = analyze_performance()
    if report:
        print_performance_report(report)
