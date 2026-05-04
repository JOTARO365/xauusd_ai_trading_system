"""Read layer — DB primary, JSON fallback is handled by callers."""

from datetime import date, datetime
from decimal import Decimal

from loguru import logger

from db.connection import get_conn

_ALIASES = {
    "GOLD": "XAUUSD", "GOLD#": "XAUUSD", "XAUUSD": "XAUUSD",
    "BTC": "BTCUSD", "BTCUSD": "BTCUSD",
}


def _norm(sym: str) -> str:
    return _ALIASES.get(sym.upper(), sym.upper())


def _to_py(val):
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def get_trades(symbol: str = "XAUUSD") -> list[dict] | None:
    normed = _norm(symbol)
    raw = symbol.upper()
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticket, symbol, source, direction, entry_type, status,
                           lot, entry_price, sl, tp, pnl,
                           opened_at, closed_at,
                           technical_signal, technical_confidence,
                           trend, sr_zone, sr_strength, pa_action,
                           sentiment, analysis
                    FROM trades
                    WHERE symbol IN (%s, %s)
                    ORDER BY opened_at ASC NULLS LAST
                    """,
                    (normed, raw),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        result = []
        for r in rows:
            result.append({
                "ticket":                r["ticket"],
                "symbol":                r["symbol"],
                "source":                r["source"],
                "direction":             r["direction"],
                "entry_type":            r["entry_type"],
                "status":                r["status"],
                "lot":                   _to_py(r["lot"]),
                "entry_price":           _to_py(r["entry_price"]),
                "sl":                    _to_py(r["sl"]),
                "tp":                    _to_py(r["tp"]),
                "pnl":                   _to_py(r["pnl"]),
                "timestamp":             _to_py(r["opened_at"]),
                "close_time":            _to_py(r["closed_at"]),
                "technical_signal":      r["technical_signal"],
                "technical_confidence":  r["technical_confidence"],
                "trend":                 r["trend"],
                "sr_zone":               r["sr_zone"],
                "sr_strength":           r["sr_strength"],
                "pa_action":             r["pa_action"],
                "sentiment":             r["sentiment"],
                "analysis":              r["analysis"],
            })
        return result
    except Exception as e:
        logger.debug(f"get_trades DB error: {e}")
        return None


def get_accounting(symbol: str | None = None) -> dict | None:
    use_filter = symbol is not None and symbol.lower() != "all"
    normed = _norm(symbol) if use_filter else None
    raw = symbol.upper() if use_filter else None
    today_str = date.today().isoformat()

    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # ── Query 1: agent aggregates ─────────────────────────────
                if use_filter:
                    cur.execute(
                        """
                        SELECT agent_name, model,
                               COUNT(*)                        AS total_calls,
                               SUM(cost_usd)                  AS total_cost_usd,
                               SUM(input_tokens)              AS total_input_tokens,
                               SUM(output_tokens)             AS total_output_tokens,
                               SUM(cache_read_tokens)         AS total_cache_read_tokens,
                               SUM(cache_write_tokens)        AS total_cache_write_tokens
                        FROM agent_usage
                        WHERE symbol IN (%s, %s)
                        GROUP BY agent_name, model
                        """,
                        (normed, raw),
                    )
                else:
                    cur.execute(
                        """
                        SELECT agent_name, model,
                               COUNT(*)                        AS total_calls,
                               SUM(cost_usd)                  AS total_cost_usd,
                               SUM(input_tokens)              AS total_input_tokens,
                               SUM(output_tokens)             AS total_output_tokens,
                               SUM(cache_read_tokens)         AS total_cache_read_tokens,
                               SUM(cache_write_tokens)        AS total_cache_write_tokens
                        FROM agent_usage
                        GROUP BY agent_name, model
                        """
                    )
                agent_rows = cur.fetchall()

                # ── Query 2: daily costs (last 30 days) ───────────────────
                if use_filter:
                    cur.execute(
                        """
                        SELECT DATE(cycle_at)  AS day,
                               SUM(total_cost_usd) AS total_cost_usd,
                               COUNT(*)            AS cycles,
                               COUNT(ticket)       AS trades
                        FROM cycles
                        WHERE symbol IN (%s, %s)
                          AND cycle_at >= NOW() - INTERVAL '30 days'
                        GROUP BY DATE(cycle_at)
                        ORDER BY day
                        """,
                        (normed, raw),
                    )
                else:
                    cur.execute(
                        """
                        SELECT DATE(cycle_at)  AS day,
                               SUM(total_cost_usd) AS total_cost_usd,
                               COUNT(*)            AS cycles,
                               COUNT(ticket)       AS trades
                        FROM cycles
                        WHERE cycle_at >= NOW() - INTERVAL '30 days'
                        GROUP BY DATE(cycle_at)
                        ORDER BY day
                        """
                    )
                daily_rows = cur.fetchall()

                # ── Query 3: global totals ────────────────────────────────
                if use_filter:
                    cur.execute(
                        """
                        SELECT SUM(total_cost_usd) AS total_cost_usd,
                               COUNT(*)            AS total_cycles,
                               COUNT(ticket)       AS total_trades
                        FROM cycles
                        WHERE symbol IN (%s, %s)
                        """,
                        (normed, raw),
                    )
                else:
                    cur.execute(
                        """
                        SELECT SUM(total_cost_usd) AS total_cost_usd,
                               COUNT(*)            AS total_cycles,
                               COUNT(ticket)       AS total_trades
                        FROM cycles
                        """
                    )
                totals = cur.fetchone()
        finally:
            conn.close()

        agents = {}
        for r in agent_rows:
            agents[r["agent_name"]] = {
                "model":                    r["model"],
                "total_calls":              int(r["total_calls"]),
                "total_cost_usd":           float(_to_py(r["total_cost_usd"]) or 0),
                "total_input_tokens":       int(r["total_input_tokens"] or 0),
                "total_output_tokens":      int(r["total_output_tokens"] or 0),
                "total_cache_read_tokens":  int(r["total_cache_read_tokens"] or 0),
                "total_cache_write_tokens": int(r["total_cache_write_tokens"] or 0),
            }

        daily = {}
        today_entry = {}
        for r in daily_rows:
            day_key = r["day"].isoformat() if isinstance(r["day"], date) else str(r["day"])
            entry = {
                "total_cost_usd": float(_to_py(r["total_cost_usd"]) or 0),
                "cycles":         int(r["cycles"]),
                "trades":         int(r["trades"]),
            }
            daily[day_key] = entry
            if day_key == today_str:
                today_entry = entry

        summary = {
            "total_cost_usd": float(_to_py(totals["total_cost_usd"]) or 0) if totals else 0.0,
            "total_cycles":   int(totals["total_cycles"] or 0) if totals else 0,
            "total_trades":   int(totals["total_trades"] or 0) if totals else 0,
        }

        return {
            "summary": summary,
            "agents":  agents,
            "today":   today_entry,
            "daily":   daily,
        }
    except Exception as e:
        logger.debug(f"get_accounting DB error: {e}")
        return None
