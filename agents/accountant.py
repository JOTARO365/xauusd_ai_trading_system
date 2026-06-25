import json
import os
from datetime import datetime, timezone, date
from typing import Optional

from loguru import logger

# ── Pricing (USD per token) ───────────────────────────────────────────────────
# cache_write = 1.25x input;  cache_read = 0.10x input
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input":        0.80 / 1_000_000,
        "output":       4.00 / 1_000_000,
        "cache_write":  1.00 / 1_000_000,
        "cache_read":   0.08 / 1_000_000,
    },
    "claude-sonnet-4-6": {
        "input":        3.00 / 1_000_000,
        "output":      15.00 / 1_000_000,
        "cache_write":  3.75 / 1_000_000,
        "cache_read":   0.30 / 1_000_000,
    },
    # ── เพิ่ม provider อื่นตอน migrate (ใส่ราคาจริงจาก doc ของแต่ละค่าย; ค่า cache 0 ได้ถ้าไม่มี) ──
    # "grok-...":  {"input": _/1e6, "output": _/1e6, "cache_write": 0, "cache_read": 0},
    # "gemini-...":{"input": _/1e6, "output": _/1e6, "cache_write": 0, "cache_read": 0},
    # "qwen-...":  {"input": _/1e6, "output": _/1e6, "cache_write": 0, "cache_read": 0},
}
_FALLBACK = _PRICING["claude-haiku-4-5-20251001"]

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "accounting.json")
_MAX_CYCLES = 500   # เก็บไว้ใน memory เท่านี้ (aggregate ยังครบ)

# MT5 symbol aliases → canonical names
_SYMBOL_ALIASES: dict[str, str] = {
    "GOLD":   "XAUUSD",
    "GOLD#":  "XAUUSD",
    "XAUUSD": "XAUUSD",
    "BTCUSD": "BTCUSD",
    "BTC":    "BTCUSD",
}

def _norm_symbol(sym: str) -> str:
    return _SYMBOL_ALIASES.get(sym.upper(), sym.upper())


# ── I/O ──────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(_LOG_PATH):
        try:
            with open(_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "summary": {"total_cost_usd": 0.0, "total_cycles": 0, "total_trades": 0},
        "agents":  {},
        "daily":   {},
        "cycles":  [],
    }


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
    with open(_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Cost calculation ──────────────────────────────────────────────────────────

def _normalize_usage(usage) -> tuple[int, int, int, int]:
    """คืน (input, output, cache_read, cache_write) จาก usage ของ provider ใดก็ได้.
    รองรับ: Anthropic (input_tokens/cache_*_input_tokens), OpenAI-compatible — Qwen/Grok
    ผ่าน OpenAI SDK (prompt_tokens/completion_tokens, prompt_tokens_details.cached_tokens),
    LangChain usage_metadata (input_tokens/output_tokens), dict, หรือ None.
    หมายเหตุ: OpenAI-style prompt_tokens รวม cached แล้ว ส่วน Anthropic input_tokens แยก —
    การ map นี้พอสำหรับ cost ระดับ accounting ไม่ได้ละเอียดระดับ cache discount ทุกค่าย."""
    if usage is None:
        return 0, 0, 0, 0
    if isinstance(usage, dict):
        g = lambda k, d=0: usage.get(k, d) or 0
        _details = usage.get("prompt_tokens_details") or {}
    else:
        g = lambda k, d=0: getattr(usage, k, d) or 0
        _details = getattr(usage, "prompt_tokens_details", None) or {}
    inp = g("input_tokens") or g("prompt_tokens")
    out = g("output_tokens") or g("completion_tokens")
    cr  = g("cache_read_input_tokens")
    cw  = g("cache_creation_input_tokens")
    if not cr:   # OpenAI-style cached tokens
        cr = (_details.get("cached_tokens", 0) if isinstance(_details, dict)
              else getattr(_details, "cached_tokens", 0)) or 0
    return int(inp or 0), int(out or 0), int(cr or 0), int(cw or 0)


def calc_cost(model: str, usage) -> dict:
    """คำนวณต้นทุน USD จาก usage object ของ provider ใดก็ได้ (ดู _normalize_usage)."""
    p = _PRICING.get(model)
    if p is None:
        logger.warning(
            f"[accounting] ไม่มีราคา model '{model}' ใน _PRICING — ใช้ fallback (cost อาจผิด). "
            f"เพิ่มราคาจริงใน agents/accountant.py::_PRICING"
        )
        p = _FALLBACK
    inp, out, cr, cw = _normalize_usage(usage)

    cost = (inp * p["input"]
          + out * p["output"]
          + cr  * p["cache_read"]
          + cw  * p["cache_write"])

    total_in = inp + cr + cw
    hit_rate = round(cr / total_in * 100, 1) if total_in > 0 else 0.0

    return {
        "input_tokens":       inp,
        "output_tokens":      out,
        "cache_read_tokens":  cr,
        "cache_write_tokens": cw,
        "cost_usd":           round(cost, 6),
        "cache_hit_rate":     hit_rate,
    }


# ── Main recording function ───────────────────────────────────────────────────

def record_cycle(
    symbol: str,
    agent_usages: dict,                       # {name: (model, usage_obj | None)}
    ticket: Optional[int] = None,
    latencies_ms: Optional[dict[str, int]] = None,
) -> dict:
    """บันทึก token usage + cost ของ 1 trading cycle ลง accounting.json"""
    data = _load()
    lat  = latencies_ms or {}
    # UTC canonical — cycle "at" ถูกเก็บเป็น UTC; daily bucket ต้องใช้ UTC date ให้ตรงกับ
    # readers (get_summary_by_symbol / db.reader) ที่ bucket จาก at[:10] (UTC) อยู่แล้ว
    today = datetime.now(timezone.utc).date().isoformat()
    symbol = _norm_symbol(symbol)

    cycle: dict = {
        "at":             datetime.now(timezone.utc).isoformat(),
        "symbol":         symbol,
        "ticket":         ticket,
        "total_cost_usd": 0.0,
        "agents":         {},
    }

    for name, (model, usage) in agent_usages.items():
        if usage is None:
            continue
        info = calc_cost(model, usage)
        info["model"]      = model
        info["latency_ms"] = lat.get(name)
        cycle["agents"][name] = info
        cycle["total_cost_usd"] = round(cycle["total_cost_usd"] + info["cost_usd"], 6)

        # ── per-agent aggregate ───────────────────────────────────────────
        agg = data["agents"].setdefault(name, {
            "model":                    model,
            "total_calls":              0,
            "total_cost_usd":           0.0,
            "total_input_tokens":       0,
            "total_output_tokens":      0,
            "total_cache_read_tokens":  0,
            "total_cache_write_tokens": 0,
        })
        agg["total_calls"]              += 1
        agg["total_cost_usd"]            = round(agg["total_cost_usd"] + info["cost_usd"], 6)
        agg["total_input_tokens"]       += info["input_tokens"]
        agg["total_output_tokens"]      += info["output_tokens"]
        agg["total_cache_read_tokens"]  += info["cache_read_tokens"]
        agg["total_cache_write_tokens"] += info["cache_write_tokens"]

    # ── daily summary ─────────────────────────────────────────────────────
    day = data["daily"].setdefault(today, {
        "total_cost_usd": 0.0, "cycles": 0, "trades": 0,
    })
    day["total_cost_usd"] = round(day["total_cost_usd"] + cycle["total_cost_usd"], 6)
    day["cycles"] += 1
    if ticket:
        day["trades"] += 1

    # ── global summary ────────────────────────────────────────────────────
    s = data["summary"]
    s["total_cost_usd"] = round(s["total_cost_usd"] + cycle["total_cost_usd"], 6)
    s["total_cycles"]  += 1
    if ticket:
        s["total_trades"] += 1

    data["cycles"].append(cycle)
    if len(data["cycles"]) > _MAX_CYCLES:
        data["cycles"] = data["cycles"][-_MAX_CYCLES:]

    _save(data)
    logger.info(
        f"Accounting: ${cycle['total_cost_usd']:.5f}/cycle | "
        f"total ${s['total_cost_usd']:.4f} | ticket={ticket}"
    )

    # ── write-through to PostgreSQL (optional — ถ้า DB ไม่พร้อมก็ไม่ crash) ──
    try:
        from db.writer import write_cycle as _db_write_cycle
        _db_write_cycle(cycle)
    except Exception as _e:
        logger.debug(f"DB cycle write skipped: {_e}")

    return cycle


# ── Report helpers ────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """คืน summary รวมทุก symbol สำหรับ dashboard"""
    data = _load()
    return {
        "summary": data.get("summary", {}),
        "agents":  data.get("agents",  {}),
        "today":   data.get("daily", {}).get(datetime.now(timezone.utc).date().isoformat(), {}),
        "daily":   data.get("daily",   {}),
    }


def get_summary_by_symbol(symbol: str) -> dict:
    """คืน summary filtered by symbol — ใช้สำหรับ dashboard multi-system"""
    data     = _load()
    sym_up   = _norm_symbol(symbol)
    today_str = datetime.now(timezone.utc).date().isoformat()

    cycles = [c for c in data.get("cycles", [])
              if _norm_symbol(c.get("symbol", "XAUUSD")) == sym_up]

    # per-agent aggregates
    agents: dict = {}
    for c in cycles:
        for name, info in c.get("agents", {}).items():
            agg = agents.setdefault(name, {
                "model":                    info.get("model", ""),
                "total_calls":              0,
                "total_cost_usd":           0.0,
                "total_input_tokens":       0,
                "total_output_tokens":      0,
                "total_cache_read_tokens":  0,
                "total_cache_write_tokens": 0,
            })
            agg["total_calls"]              += 1
            agg["total_cost_usd"]            = round(agg["total_cost_usd"] + info.get("cost_usd", 0), 6)
            agg["total_input_tokens"]       += info.get("input_tokens", 0)
            agg["total_output_tokens"]      += info.get("output_tokens", 0)
            agg["total_cache_read_tokens"]  += info.get("cache_read_tokens", 0)
            agg["total_cache_write_tokens"] += info.get("cache_write_tokens", 0)

    # daily costs
    daily: dict = {}
    for c in cycles:
        day = (c.get("at") or "")[:10]
        if not day:
            continue
        d = daily.setdefault(day, {"total_cost_usd": 0.0, "cycles": 0, "trades": 0})
        d["total_cost_usd"] = round(d["total_cost_usd"] + c.get("total_cost_usd", 0), 6)
        d["cycles"] += 1
        if c.get("ticket"):
            d["trades"] += 1

    total_cost   = sum(c.get("total_cost_usd", 0) for c in cycles)
    total_trades = sum(1 for c in cycles if c.get("ticket"))

    return {
        "summary": {
            "total_cost_usd": round(total_cost, 6),
            "total_cycles":   len(cycles),
            "total_trades":   total_trades,
        },
        "agents": agents,
        "today":  daily.get(today_str, {}),
        "daily":  daily,
    }
