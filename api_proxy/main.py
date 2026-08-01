"""
Trading API Proxy — รับ trade/cycle data จาก user bots แล้วเขียนลง Supabase
Deploy: Render.com (free tier) — https://render.com

Environment variables ที่ต้องตั้งบน Render:
  SUPABASE_URL          = https://xxx.supabase.co
  SUPABASE_SERVICE_KEY  = service_role key (ไม่ใช่ anon key)
"""
import hashlib
import os
from datetime import datetime, timedelta

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
    """ตรวจ api_keys table → คืน account_login หรือ raise 401.
    DB เก็บแค่ sha256(key) → hash ค่าที่ส่งมาแล้วค่อย match (กัน DB หลุดแล้ว key ใช้ได้)."""
    key_hash = hashlib.sha256((api_key or "").encode()).hexdigest()
    try:
        res = (
            _db()
            .table("api_keys")
            .select("account_login")
            .eq("key", key_hash)
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


# ── Reads (scoped to the key's account — user ไม่ต้องมี Supabase key) ────────────
# proxy บังคับ eq(account_login) จาก key เสมอ → user เห็นเฉพาะ account ตัวเอง (RLS-equivalent)

_TRADE_COLS = (
    "ticket,account_login,symbol,source,direction,entry_type,status,"
    "lot,entry_price,sl,tp,pnl,opened_at,closed_at,close_reason,close_price,"
    "technical_signal,technical_confidence,trend,sr_zone,sr_strength,pa_action,"
    "sentiment,analysis,strategy_version"
)


@app.get("/trades")
def read_trades(x_api_key: str = Header(), symbols: str = ""):
    account_login = _resolve_account(x_api_key)
    syms = [s for s in symbols.split(",") if s]
    q = _db().table("trades").select(_TRADE_COLS).eq("account_login", account_login)
    if syms:
        q = q.in_("symbol", syms)
    try:
        res = q.order("opened_at", desc=True).limit(500).execute()
        return {"ok": True, "rows": res.data or []}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/accounting")
def read_accounting(x_api_key: str = Header(), symbols: str = ""):
    account_login = _resolve_account(x_api_key)
    syms = [s for s in symbols.split(",") if s]
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
    try:
        au = (_db().table("agent_usage").select(
                "agent_name,model,cost_usd,input_tokens,output_tokens,"
                "cache_read_tokens,cache_write_tokens")
              .eq("account_login", account_login))
        if syms:
            au = au.in_("symbol", syms)
        agent_usage = au.execute().data or []

        cr = (_db().table("cycles").select("cycle_at,total_cost_usd,ticket")
              .eq("account_login", account_login).gte("cycle_at", cutoff)
              .order("cycle_at", desc=True).limit(1000))
        if syms:
            cr = cr.in_("symbol", syms)
        cycles_recent = cr.execute().data or []

        ca = (_db().table("cycles").select("total_cost_usd,ticket")
              .eq("account_login", account_login))
        if syms:
            ca = ca.in_("symbol", syms)
        cycles_all = ca.execute().data or []

        return {"ok": True, "agent_usage": agent_usage,
                "cycles_recent": cycles_recent, "cycles_all": cycles_all}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Sync helpers: tickets list + partial update (scoped ตาม key) ─────────────────

@app.get("/trades/tickets")
def read_tickets(x_api_key: str = Header(), symbol: str = "", status: str = "", flt: str = ""):
    """คืน ticket ทั้งหมดของ account (paginate server-side). flt: pnl_null | trend_null."""
    account_login = _resolve_account(x_api_key)
    tickets: list = []
    start = 0
    try:
        while True:
            q = _db().table("trades").select("ticket").eq("account_login", account_login)
            if symbol:
                q = q.eq("symbol", symbol)
            if status:
                q = q.eq("status", status)
            if flt == "pnl_null":
                q = q.is_("pnl", "null")
            elif flt == "trend_null":
                q = q.is_("trend", "null")
            batch = q.range(start, start + 999).execute().data or []
            tickets += [r["ticket"] for r in batch if r.get("ticket") is not None]
            if len(batch) < 1000:
                break
            start += 1000
        return {"ok": True, "tickets": tickets}
    except Exception as e:
        raise HTTPException(500, str(e))


_UPDATABLE = {
    "status", "pnl", "closed_at", "close_reason", "close_price",
    "technical_signal", "technical_confidence", "trend", "entry_type",
    "sr_zone", "sr_strength", "pa_action", "sentiment", "analysis",
    "planned_sl_pips", "entry_score", "atr_h4", "momentum", "htf_zone_tf",
    "strategy_version",
}


@app.post("/trades/update")
async def update_trade(request: Request, x_api_key: str = Header()):
    """UPDATE partial fields ของ 1 ticket — scope account จาก key เสมอ (แตะบัญชีอื่นไม่ได้)."""
    account_login = _resolve_account(x_api_key)
    body = await request.json()
    ticket = body.get("ticket")
    if not ticket:
        raise HTTPException(400, "missing ticket")
    patch = {k: v for k, v in (body.get("fields") or {}).items() if k in _UPDATABLE}
    if not patch:
        raise HTTPException(400, "no updatable fields")
    try:
        (_db().table("trades").update(patch)
         .eq("ticket", int(ticket)).eq("account_login", account_login).execute())
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Cross-user algo cells (pooled — aggregate ฝั่ง server, ไม่ leak raw ต่อ account) ──
# ⚠️ attribution logic ต้อง sync กับ agents/trade_recorder._algo_of + algo_selector
_CU_ALIASES = {"GOLD": "XAUUSD", "GOLD#": "XAUUSD", "XAUUSD": "XAUUSD",
               "BTC": "BTCUSD", "BTCUSD": "BTCUSD"}
_CU_COMMENT_ALGO = {"ALGO-mom": "regime_momentum", "ALGO-TSMOM": "tsmom_d1"}
_CU_RETIRED = {"decision_ai"}


def _cu_norm(s):
    s = (s or "").upper()
    return _CU_ALIASES.get(s, s)


def _cu_algo_of(comment):
    c = (comment or "").strip()
    if c.startswith("MSE-"):
        return c[4:].strip() or "mse"
    for k, v in _CU_COMMENT_ALGO.items():
        if c.startswith(k):
            return v
    return "decision_ai"


def _cu_attribute(r):
    src = (str(r.get("source") or "")).upper()
    if src == "MANUAL":
        return None
    cm = r.get("comment")
    if cm:
        return _cu_algo_of(cm)
    if src == "SYSTEM":
        return "decision_ai"
    return None


def _cu_regime(trend):
    t = (str(trend or "")).upper()
    if "BULL" in t and "BEAR" not in t:
        return "BULLISH"
    if "BEAR" in t and "BULL" not in t:
        return "BEARISH"
    return "NEUTRAL"


@app.get("/cells")
def read_cells(x_api_key: str = Header(), by_regime: int = 1):
    """cross-user cells (ทุก account) — คืนเฉพาะ aggregate ไม่ส่ง raw ต่อ account.
    valid key = เข้าถึง pooled ได้ (จุดประสงค์ = เรียนรู้ร่วมกัน)."""
    _resolve_account(x_api_key)   # ต้องมี key ที่ active
    rows: list = []
    start = 0
    try:
        while True:
            batch = (_db().table("trades")
                     .select("comment,source,account_login,symbol,pnl,trend,status")
                     .eq("status", "CLOSED").range(start, start + 999).execute().data) or []
            rows += batch
            if len(batch) < 1000:
                break
            start += 1000
    except Exception as e:
        raise HTTPException(500, str(e))

    agg: dict = {}
    for r in rows:
        algo = _cu_attribute(r)
        if not algo or algo in _CU_RETIRED:
            continue
        sym = _cu_norm(str(r.get("symbol") or ""))
        reg = _cu_regime(r.get("trend")) if by_regime else "ALL"
        key = (algo, sym, reg)
        pnl = float(r.get("pnl") or 0.0)
        d = agg.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0, "acc": set()})
        d["n"] += 1
        d["wins"] += 1 if pnl > 0 else 0
        d["pnl"] += pnl
        if r.get("account_login"):
            d["acc"].add(r["account_login"])
    cells = [{"algo": a, "symbol": s, "regime": g, "n": d["n"], "wins": d["wins"],
              "pnl": round(d["pnl"], 2), "n_accounts": len(d["acc"])}
             for (a, s, g), d in agg.items()]
    return {"ok": True, "cells": cells}


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
