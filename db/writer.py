"""
Write-through layer: JSON เป็น primary, PostgreSQL เป็น secondary.
ถ้า DB ไม่พร้อม functions จะ log และ return False โดยไม่ crash.
"""
from datetime import datetime
from loguru import logger

from db.connection import get_conn


# ── helpers ──────────────────────────────────────────────────────────────────

def _dt(s) -> "datetime | None":
    """แปลง ISO string → datetime (หรือ None)"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None


# ── trades ───────────────────────────────────────────────────────────────────

def write_trade(trade: dict) -> bool:
    """Upsert trade — อัปเดต status/pnl/sl/tp เมื่อ trade ปิด"""
    ticket = trade.get("ticket")
    if not ticket:
        return False
    try:
        conn = get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO trades (
                            ticket, symbol, source, direction, entry_type, status,
                            lot, entry_price, sl, tp, pnl,
                            opened_at, closed_at,
                            technical_signal, technical_confidence,
                            trend, sr_zone, sr_strength,
                            pa_action, sentiment, analysis
                        ) VALUES (
                            %(ticket)s, %(symbol)s, %(source)s, %(direction)s,
                            %(entry_type)s, %(status)s,
                            %(lot)s, %(entry_price)s, %(sl)s, %(tp)s, %(pnl)s,
                            %(opened_at)s, %(closed_at)s,
                            %(technical_signal)s, %(technical_confidence)s,
                            %(trend)s, %(sr_zone)s, %(sr_strength)s,
                            %(pa_action)s, %(sentiment)s, %(analysis)s
                        )
                        ON CONFLICT (ticket) DO UPDATE SET
                            status      = EXCLUDED.status,
                            pnl         = EXCLUDED.pnl,
                            sl          = EXCLUDED.sl,
                            tp          = EXCLUDED.tp,
                            lot         = EXCLUDED.lot,
                            closed_at   = EXCLUDED.closed_at,
                            updated_at  = NOW()
                    """, {
                        "ticket":               int(ticket),
                        "symbol":               trade.get("symbol", "XAUUSD"),
                        "source":               trade.get("source"),
                        "direction":            trade.get("direction"),
                        "entry_type":           trade.get("entry_type"),
                        "status":               trade.get("status", "OPEN"),
                        "lot":                  trade.get("lot"),
                        "entry_price":          trade.get("entry_price"),
                        "sl":                   trade.get("sl"),
                        "tp":                   trade.get("tp"),
                        "pnl":                  trade.get("pnl"),
                        "opened_at":            _dt(trade.get("timestamp")),
                        "closed_at":            _dt(trade.get("close_time")),
                        "technical_signal":     trade.get("technical_signal"),
                        "technical_confidence": trade.get("technical_confidence"),
                        "trend":                trade.get("trend"),
                        "sr_zone":              trade.get("sr_zone"),
                        "sr_strength":          trade.get("sr_strength"),
                        "pa_action":            trade.get("pa_action"),
                        "sentiment":            trade.get("sentiment"),
                        "analysis":             trade.get("analysis"),
                    })
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.debug(f"DB write_trade: {e}")
        return False


# ── cycles + agent_usage ─────────────────────────────────────────────────────

def write_cycle(cycle: dict) -> bool:
    """Insert cycle summary + per-agent usage rows"""
    try:
        conn = get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # ── cycles row ───────────────────────────────────────────
                    cur.execute("""
                        INSERT INTO cycles (symbol, cycle_at, ticket, total_cost_usd)
                        VALUES (%(symbol)s, %(cycle_at)s, %(ticket)s, %(total_cost_usd)s)
                    """, {
                        "symbol":         cycle.get("symbol", "XAUUSD"),
                        "cycle_at":       _dt(cycle.get("at")) or datetime.utcnow(),
                        "ticket":         cycle.get("ticket"),
                        "total_cost_usd": cycle.get("total_cost_usd", 0),
                    })

                    # ── agent_usage rows ─────────────────────────────────────
                    for agent_name, info in cycle.get("agents", {}).items():
                        cur.execute("""
                            INSERT INTO agent_usage (
                                symbol, agent_name, model, cycle_at, ticket,
                                input_tokens, output_tokens,
                                cache_read_tokens, cache_write_tokens,
                                cost_usd, cache_hit_rate, latency_ms
                            ) VALUES (
                                %(symbol)s, %(agent_name)s, %(model)s,
                                %(cycle_at)s, %(ticket)s,
                                %(input_tokens)s, %(output_tokens)s,
                                %(cache_read_tokens)s, %(cache_write_tokens)s,
                                %(cost_usd)s, %(cache_hit_rate)s, %(latency_ms)s
                            )
                        """, {
                            "symbol":             cycle.get("symbol", "XAUUSD"),
                            "agent_name":         agent_name,
                            "model":              info.get("model", ""),
                            "cycle_at":           _dt(cycle.get("at")) or datetime.utcnow(),
                            "ticket":             cycle.get("ticket"),
                            "input_tokens":       info.get("input_tokens", 0),
                            "output_tokens":      info.get("output_tokens", 0),
                            "cache_read_tokens":  info.get("cache_read_tokens", 0),
                            "cache_write_tokens": info.get("cache_write_tokens", 0),
                            "cost_usd":           info.get("cost_usd", 0),
                            "cache_hit_rate":     info.get("cache_hit_rate"),
                            "latency_ms":         info.get("latency_ms"),
                        })
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.debug(f"DB write_cycle: {e}")
        return False
