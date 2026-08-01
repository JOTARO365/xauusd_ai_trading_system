"""Read layer — 2 โหมด (mirror db/writer.py):

  A) TRADING_API_URL + TRADING_API_KEY ตั้งค่า → อ่านผ่าน API proxy (user mode —
     ไม่ต้องมี Supabase key; proxy scope ตาม account ของ key เสมอ)
  B) SUPABASE_URL/KEY ตั้งค่า → อ่าน Supabase ตรง (owner mode — filter account_login เองได้)

mapping/aggregation อยู่ที่นี่จุดเดียว; ต่างกันแค่ "แหล่ง rows". JSON fallback = หน้าที่ caller.
"""
import json as _json
import os as _os
import urllib.parse as _uparse
import urllib.request as _ureq
from datetime import datetime, timedelta
from loguru import logger

from db.connection import get_client

_PROXY_URL = _os.getenv("TRADING_API_URL", "").rstrip("/")
_PROXY_KEY = _os.getenv("TRADING_API_KEY", "")

_ALIASES = {
    "GOLD": "XAUUSD", "GOLD#": "XAUUSD", "XAUUSD": "XAUUSD",
    "BTC": "BTCUSD", "BTCUSD": "BTCUSD",
}

_TRADE_COLS = (
    "ticket,account_login,symbol,source,direction,entry_type,status,"
    "lot,entry_price,sl,tp,pnl,opened_at,closed_at,close_reason,close_price,"
    "technical_signal,technical_confidence,trend,sr_zone,sr_strength,pa_action,"
    "sentiment,analysis,strategy_version"
)


def _norm(sym: str) -> str:
    return _ALIASES.get(sym.upper(), sym.upper())


def _get_account_login() -> int:
    try:
        import MetaTrader5 as mt5
        info = mt5.account_info()
        return int(info.login) if info else 0
    except Exception:
        return 0


def _proxy_mode() -> bool:
    return bool(_PROXY_URL and _PROXY_KEY)


def _proxy_get(endpoint: str, params: dict | None = None) -> dict:
    """GET ไปยัง API proxy พร้อม X-Api-Key. คืน dict (raise ถ้าพลาด — caller จับเอง)."""
    url = f"{_PROXY_URL}/{endpoint}"
    if params:
        url += "?" + _uparse.urlencode(params)
    req = _ureq.Request(url, headers={"X-Api-Key": _PROXY_KEY}, method="GET")
    with _ureq.urlopen(req, timeout=15) as r:
        return _json.loads(r.read().decode())


def get_trades(symbol: str = "XAUUSD", account_login: int | None = None) -> list[dict] | None:
    all_sym = symbol is not None and str(symbol).lower() == "all"    # "all" = ทุกคู่
    symbols: list[str] = []
    if not all_sym:
        normed = _norm(symbol)
        # รวมทุก alias ที่ map ไป instrument เดียวกัน (GOLD, GOLD#, XAUUSD → XAUUSD)
        symbols = list({k for k, v in _ALIASES.items() if v == normed} | {normed, symbol.upper()})

    # ── source rows: proxy (user) หรือ DB (owner) ────────────────────────────────
    if _proxy_mode():
        try:
            params = {} if all_sym else {"symbols": ",".join(symbols)}
            data = _proxy_get("trades", params)      # proxy scope account จาก key เอง
            rows = data.get("rows", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.debug(f"get_trades proxy error: {e}")
            return None
    else:
        login = account_login if account_login is not None else _get_account_login()
        try:
            q = get_client().table("trades").select(_TRADE_COLS)
            if not all_sym:
                q = q.in_("symbol", symbols)
            if login:
                q = q.eq("account_login", login)
            rows = q.order("opened_at", desc=True).limit(500).execute().data
        except Exception as e:
            logger.debug(f"get_trades DB error: {e}")
            return None

    # ── map (shared) ─────────────────────────────────────────────────────────────
    result = []
    for r in rows:
        result.append({
            "ticket":                r.get("ticket"),
            "symbol":                r.get("symbol"),
            "source":                r.get("source", "SYSTEM"),
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
            "close_reason":          r.get("close_reason"),
            "close_price":           r.get("close_price"),
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
    # CONTRACT: คืน chronological (เก่า→ใหม่) เหมือน logs/trades.json — consumer ทุกตัว
    # (reporter closed[-10:]/losing-streak, dashboard list(reversed)) พึ่ง convention นี้.
    # query/proxy เป็น desc+limit เพื่อได้ "500 ไม้ล่าสุด" แล้วกลับด้านที่นี่จุดเดียว.
    result.reverse()
    return result


def _aggregate_accounting(agent_rows: list, cycle_rows: list, all_cycles: list) -> dict:
    """รวมสถิติ (shared ทั้ง proxy/DB path) — pure python, ไม่แตะ network."""
    today_str = datetime.utcnow().date().isoformat()   # UTC — ตรงกับ cycle_at[:10]

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

    all_cost   = round(sum(float(r.get("total_cost_usd") or 0) for r in all_cycles), 6)
    all_trades = sum(1 for r in all_cycles if r.get("ticket"))

    return {
        "summary": {
            "total_cost_usd": all_cost,
            "total_cycles":   len(all_cycles),
            "total_trades":   all_trades,
        },
        "agents":  agents,
        "today":   daily.get(today_str, {}),
        "daily":   daily,
    }


def get_accounting(symbol: str | None = None, account_login: int | None = None) -> dict | None:
    use_filter = symbol is not None and symbol.lower() != "all"
    symbols: list[str] = []
    if use_filter:
        normed = _norm(symbol)
        symbols = list({normed, symbol.upper()})

    # ── source rows: proxy (user) หรือ DB (owner) ────────────────────────────────
    if _proxy_mode():
        try:
            params = {"symbols": ",".join(symbols)} if use_filter else {}
            raw = _proxy_get("accounting", params)
            agent_rows   = raw.get("agent_usage", [])
            cycle_rows   = raw.get("cycles_recent", [])
            all_cycles   = raw.get("cycles_all", [])
        except Exception as e:
            logger.debug(f"get_accounting proxy error: {e}")
            return None
    else:
        use_acct = account_login is not None and account_login != 0
        cutoff   = (datetime.utcnow() - timedelta(days=30)).isoformat()
        try:
            client = get_client()
            q = client.table("agent_usage").select(
                "agent_name,model,cost_usd,input_tokens,output_tokens,"
                "cache_read_tokens,cache_write_tokens")
            if use_filter:
                q = q.in_("symbol", symbols)
            if use_acct:
                q = q.eq("account_login", account_login)
            agent_rows = q.execute().data

            q = (client.table("cycles").select("cycle_at,total_cost_usd,ticket")
                 .gte("cycle_at", cutoff).order("cycle_at", desc=True).limit(1000))
            if use_filter:
                q = q.in_("symbol", symbols)
            if use_acct:
                q = q.eq("account_login", account_login)
            cycle_rows = q.execute().data

            q2 = client.table("cycles").select("total_cost_usd,ticket")
            if use_filter:
                q2 = q2.in_("symbol", symbols)
            if use_acct:
                q2 = q2.eq("account_login", account_login)
            all_cycles = q2.execute().data
        except Exception as e:
            logger.debug(f"get_accounting DB error: {e}")
            return None

    return _aggregate_accounting(agent_rows, cycle_rows, all_cycles)
