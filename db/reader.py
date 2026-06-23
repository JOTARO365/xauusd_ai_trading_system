"""Read layer — Supabase primary, JSON fallback is handled by callers."""

from datetime import date, datetime, timedelta
from loguru import logger

from db.connection import get_client

_ALIASES = {
    "GOLD": "XAUUSD", "GOLD#": "XAUUSD", "XAUUSD": "XAUUSD",
    "BTC": "BTCUSD", "BTCUSD": "BTCUSD",
}


def _norm(sym: str) -> str:
    return _ALIASES.get(sym.upper(), sym.upper())


def _get_account_login() -> int:
    try:
        import MetaTrader5 as mt5
        info = mt5.account_info()
        return int(info.login) if info else 0
    except Exception:
        return 0


def get_trades(symbol: str = "XAUUSD", account_login: int | None = None) -> list[dict] | None:
    normed = _norm(symbol)
    # รวมทุก alias ที่ map ไปยัง instrument เดียวกัน (เช่น GOLD, GOLD#, XAUUSD → XAUUSD)
    symbols = list({k for k, v in _ALIASES.items() if v == normed} | {normed, symbol.upper()})

    login = account_login if account_login is not None else _get_account_login()

    try:
        q = (
            get_client()
            .table("trades")
            .select(
                "ticket,account_login,symbol,source,direction,entry_type,status,"
                "lot,entry_price,sl,tp,pnl,"
                "opened_at,closed_at,"
                "technical_signal,technical_confidence,"
                "trend,sr_zone,sr_strength,pa_action,sentiment,analysis,"
                "strategy_version"
            )
            .in_("symbol", symbols)
        )
        if login:
            q = q.eq("account_login", login)
        res = q.order("opened_at", desc=False).execute()
        result = []
        for r in res.data:
            result.append({
                "ticket":                r.get("ticket"),
                "account_login":         r.get("account_login"),
                "symbol":                r.get("symbol"),
                "source":                r.get("source"),
                "direction":             r.get("direction"),
                "entry_type":            r.get("entry_type"),
                "status":                r.get("status"),
                "lot":                   r.get("lot"),
                "entry_price":           r.get("entry_price"),
                "sl":                    r.get("sl"),
                "tp":                    r.get("tp"),
                "pnl":                   r.get("pnl"),
                "timestamp":             r.get("opened_at"),
                "close_time":            r.get("closed_at"),
                "technical_signal":      r.get("technical_signal"),
                "technical_confidence":  r.get("technical_confidence"),
                "trend":                 r.get("trend"),
                "sr_zone":               r.get("sr_zone"),
                "sr_strength":           r.get("sr_strength"),
                "pa_action":             r.get("pa_action"),
                "sentiment":             r.get("sentiment"),
                "analysis":              r.get("analysis"),
                "strategy_version":      r.get("strategy_version", 1),
            })
        return result
    except Exception as e:
        logger.debug(f"get_trades DB error: {e}")
        return None


def get_accounting(symbol: str | None = None) -> dict | None:
    use_filter = symbol is not None and symbol.lower() != "all"
    today_str = date.today().isoformat()
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()

    try:
        client = get_client()
        symbols = []
        if use_filter:
            normed = _norm(symbol)
            symbols = list({normed, symbol.upper()})

        # ── agent_usage rows ──────────────────────────────────
        q = client.table("agent_usage").select(
            "agent_name,model,cost_usd,input_tokens,output_tokens,"
            "cache_read_tokens,cache_write_tokens"
        )
        if use_filter:
            q = q.in_("symbol", symbols)
        agent_rows = q.execute().data

        # ── cycles rows (last 30 days) ────────────────────────
        q = client.table("cycles").select("cycle_at,total_cost_usd,ticket").gte("cycle_at", cutoff)
        if use_filter:
            q = q.in_("symbol", symbols)
        cycle_rows = q.execute().data

        # ── aggregate agent stats in Python ──────────────────
        agents: dict = {}
        for r in agent_rows:
            name = r["agent_name"]
            if name not in agents:
                agents[name] = {
                    "model":                    r.get("model", ""),
                    "total_calls":              0,
                    "total_cost_usd":           0.0,
                    "total_input_tokens":       0,
                    "total_output_tokens":      0,
                    "total_cache_read_tokens":  0,
                    "total_cache_write_tokens": 0,
                }
            a = agents[name]
            a["total_calls"]              += 1
            a["total_cost_usd"]           += float(r.get("cost_usd") or 0)
            a["total_input_tokens"]       += int(r.get("input_tokens") or 0)
            a["total_output_tokens"]      += int(r.get("output_tokens") or 0)
            a["total_cache_read_tokens"]  += int(r.get("cache_read_tokens") or 0)
            a["total_cache_write_tokens"] += int(r.get("cache_write_tokens") or 0)
        for a in agents.values():
            a["total_cost_usd"] = round(a["total_cost_usd"], 6)

        # ── aggregate daily costs in Python ──────────────────
        daily: dict = {}
        for r in cycle_rows:
            day_key = (r.get("cycle_at") or "")[:10]
            if not day_key:
                continue
            if day_key not in daily:
                daily[day_key] = {"total_cost_usd": 0.0, "cycles": 0, "trades": 0}
            daily[day_key]["total_cost_usd"] += float(r.get("total_cost_usd") or 0)
            daily[day_key]["cycles"]         += 1
            if r.get("ticket"):
                daily[day_key]["trades"]     += 1
        for d in daily.values():
            d["total_cost_usd"] = round(d["total_cost_usd"], 6)

        today_entry = daily.get(today_str, {})
        total_cost  = round(sum(d["total_cost_usd"] for d in daily.values()), 6)

        # ── all-time totals ───────────────────────────────────
        q2 = client.table("cycles").select("total_cost_usd,ticket")
        if use_filter:
            q2 = q2.in_("symbol", symbols)
        all_cycles = q2.execute().data
        all_cost   = round(sum(float(r.get("total_cost_usd") or 0) for r in all_cycles), 6)
        all_trades = sum(1 for r in all_cycles if r.get("ticket"))

        return {
            "summary": {
                "total_cost_usd": all_cost,
                "total_cycles":   len(all_cycles),
                "total_trades":   all_trades,
            },
            "agents":  agents,
            "today":   today_entry,
            "daily":   daily,
        }
    except Exception as e:
        logger.debug(f"get_accounting DB error: {e}")
        return None
