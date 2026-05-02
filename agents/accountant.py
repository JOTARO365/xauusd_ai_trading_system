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
}
_FALLBACK = _PRICING["claude-haiku-4-5-20251001"]

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "accounting.json")
_MAX_CYCLES = 500   # เก็บไว้ใน memory เท่านี้ (aggregate ยังครบ)


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

def calc_cost(model: str, usage) -> dict:
    """คำนวณต้นทุน USD จาก response.usage object"""
    p   = _PRICING.get(model, _FALLBACK)
    inp = getattr(usage, "input_tokens",                0) or 0
    out = getattr(usage, "output_tokens",               0) or 0
    cr  = getattr(usage, "cache_read_input_tokens",     0) or 0
    cw  = getattr(usage, "cache_creation_input_tokens", 0) or 0

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
    today = date.today().isoformat()

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
    return cycle


# ── Report helpers ────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """คืน summary สำหรับ dashboard"""
    data = _load()
    return {
        "summary": data.get("summary", {}),
        "agents":  data.get("agents",  {}),
        "today":   data.get("daily", {}).get(date.today().isoformat(), {}),
        "daily":   data.get("daily",   {}),
    }
