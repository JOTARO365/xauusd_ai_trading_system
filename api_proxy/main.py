"""
Trading API Proxy — รับ trade/cycle data จาก user bots แล้วเขียนลง Supabase
Deploy: Render.com (free tier) — https://render.com

Environment variables ที่ต้องตั้งบน Render:
  SUPABASE_URL          = https://xxx.supabase.co
  SUPABASE_SERVICE_KEY  = service_role key (ไม่ใช่ anon key)
"""
import os
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from supabase import create_client, Client

app = FastAPI(title="Trading API Proxy", version="1.0.0")

_client: Client | None = None


def _db() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]   # service role — bypass RLS
        _client = create_client(url, key)
    return _client


def _resolve_account(api_key: str) -> int:
    """ตรวจ api_keys table → คืน account_login หรือ raise 401"""
    try:
        res = (
            _db()
            .table("api_keys")
            .select("account_login")
            .eq("key", api_key)
            .eq("active", True)
            .single()
            .execute()
        )
        return int(res.data["account_login"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


# ── Trades ────────────────────────────────────────────────────────────────────

@app.post("/trades")
async def ingest_trade(request: Request, x_api_key: str = Header()):
    account_login = _resolve_account(x_api_key)
    trade = await request.json()

    ticket = trade.get("ticket")
    if not ticket:
        raise HTTPException(400, "Missing ticket")

    def _dt(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00")).isoformat()
        except Exception:
            return None

    row = {
        "ticket":               int(ticket),
        "account_login":        account_login,           # force — ป้องกัน spoof
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
        "planned_sl_pips":      trade.get("planned_sl_pips"),
        "entry_score":          trade.get("entry_score"),
        "atr_h4":               trade.get("atr_h4"),
        "momentum":             trade.get("momentum"),
        "htf_zone_tf":          trade.get("htf_zone_tf"),
        "strategy_version":     trade.get("strategy_version", 2),
    }
    row = {k: v for k, v in row.items() if v is not None or k in ("pnl", "sl", "tp", "closed_at")}

    try:
        (_db()
         .table("trades")
         .upsert(row, on_conflict="ticket,account_login")
         .execute())
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Cycles ────────────────────────────────────────────────────────────────────

@app.post("/cycles")
async def ingest_cycle(request: Request, x_api_key: str = Header()):
    account_login = _resolve_account(x_api_key)
    cycle = await request.json()
    cycle_at = cycle.get("at") or datetime.utcnow().isoformat()

    try:
        _db().table("cycles").insert({
            "account_login":  account_login,
            "symbol":         cycle.get("symbol", "XAUUSD"),
            "cycle_at":       cycle_at,
            "ticket":         cycle.get("ticket"),
            "total_cost_usd": cycle.get("total_cost_usd", 0),
        }).execute()

        for agent_name, info in cycle.get("agents", {}).items():
            _db().table("agent_usage").insert({
                "account_login":      account_login,
                "symbol":             cycle.get("symbol", "XAUUSD"),
                "agent_name":         agent_name,
                "model":              info.get("model", ""),
                "cycle_at":           cycle_at,
                "ticket":             cycle.get("ticket"),
                "input_tokens":       info.get("input_tokens", 0),
                "output_tokens":      info.get("output_tokens", 0),
                "cache_read_tokens":  info.get("cache_read_tokens", 0),
                "cache_write_tokens": info.get("cache_write_tokens", 0),
                "cost_usd":           info.get("cost_usd", 0),
                "cache_hit_rate":     info.get("cache_hit_rate"),
                "latency_ms":         info.get("latency_ms"),
            }).execute()

        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))
