"""
Write-through layer: JSON เป็น primary, Supabase เป็น secondary.
ถ้า Supabase ไม่พร้อม functions จะ log และ return False โดยไม่ crash.
"""
from datetime import datetime
from loguru import logger

from db.connection import get_client


def _dt(s) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


def _get_account_login() -> int:
    """ดึง MT5 account login ของเครื่องนี้ — fallback 0 ถ้าไม่ได้เชื่อมต่อ"""
    try:
        import MetaTrader5 as mt5
        info = mt5.account_info()
        return int(info.login) if info else 0
    except Exception:
        return 0


def write_trade(trade: dict) -> bool:
    ticket = trade.get("ticket")
    if not ticket:
        return False
    try:
        # account_login — ใช้ค่าใน trade dict ถ้ามี ไม่งั้นดึงจาก MT5 ตอนนี้
        account_login = int(trade["account_login"]) if trade.get("account_login") else _get_account_login()

        row = {
            "ticket":               int(ticket),
            "account_login":        account_login,
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
        }
        # ลบ None values เพื่อไม่ให้ทับค่าที่มีอยู่เมื่อ upsert
        row = {k: v for k, v in row.items() if v is not None or k in ("pnl", "sl", "tp", "closed_at")}
        get_client().table("trades").upsert(row, on_conflict="ticket,account_login").execute()
        return True
    except Exception as e:
        logger.debug(f"DB write_trade: {e}")
        return False


def write_cycle(cycle: dict) -> bool:
    try:
        client = get_client()

        cycle_row = {
            "symbol":         cycle.get("symbol", "XAUUSD"),
            "cycle_at":       _dt(cycle.get("at")) or datetime.utcnow().isoformat(),
            "ticket":         cycle.get("ticket"),
            "total_cost_usd": cycle.get("total_cost_usd", 0),
        }
        client.table("cycles").insert(cycle_row).execute()

        for agent_name, info in cycle.get("agents", {}).items():
            usage_row = {
                "symbol":             cycle.get("symbol", "XAUUSD"),
                "agent_name":         agent_name,
                "model":              info.get("model", ""),
                "cycle_at":           _dt(cycle.get("at")) or datetime.utcnow().isoformat(),
                "ticket":             cycle.get("ticket"),
                "input_tokens":       info.get("input_tokens", 0),
                "output_tokens":      info.get("output_tokens", 0),
                "cache_read_tokens":  info.get("cache_read_tokens", 0),
                "cache_write_tokens": info.get("cache_write_tokens", 0),
                "cost_usd":           info.get("cost_usd", 0),
                "cache_hit_rate":     info.get("cache_hit_rate"),
                "latency_ms":         info.get("latency_ms"),
            }
            client.table("agent_usage").insert(usage_row).execute()

        return True
    except Exception as e:
        logger.debug(f"DB write_cycle: {e}")
        return False
