"""
DB Connection & Read/Write Test
รัน: python db/test_db.py
ทดสอบ: connect → write_trade → read_trade → write_cycle → read_accounting → cleanup
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
from db.connection import get_client, is_available, get_url

# ──Test ticket (จะถูกลบหลังเทส) ────────────────────────────────
_TEST_TICKET = 99999901
_TEST_ACCOUNT = 99999999
_TEST_SYMBOL = "XAUUSD"

PASS = "✅ PASS"
FAIL = "❌ FAIL"

results = []

def check(label, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append(ok)
    print(f"  {icon}  {label}" + (f"  ({detail})" if detail else ""))
    return ok


# ════════════════════════════════════════════════════════════════
print("\n=== DB Test: XAUUSD AI Trading System ===")
print(f"  Supabase URL : {get_url() or '(ไม่พบ SUPABASE_URL)'}\n")

# ──1. Connection ────────────────────────────────────────────────
print("──1. Connection ──")
try:
    avail = is_available()
    check("is_available()", avail, "ping table trades")
except Exception as e:
    check("is_available()", False, str(e))

if not results or not results[-1]:
    print("\n[ABORT] ไม่สามารถเชื่อมต่อ Supabase ได้ — ตรวจสอบ SUPABASE_URL / SUPABASE_KEY ใน .env\n")
    sys.exit(1)

client = get_client()

# ──2. Write trade ───────────────────────────────────────────────
print("\n──2. Write trade ──")
from db.writer import write_trade, write_cycle

test_trade = {
    "ticket":                _TEST_TICKET,
    "account_login":         _TEST_ACCOUNT,
    "symbol":                _TEST_SYMBOL,
    "source":                "TEST",
    "direction":             "BUY",
    "entry_type":            "MOMENTUM_BREAKOUT",
    "status":                "OPEN",
    "lot":                   0.01,
    "entry_price":           3200.00,
    "sl":                    3180.00,
    "tp":                    3240.00,
    "pnl":                   None,
    "timestamp":             datetime.utcnow().isoformat(),
    "close_time":            None,
    "technical_signal":      "BUY",
    "technical_confidence":  75,
    "trend":                 "BULLISH",
    "sr_zone":               "STRONG",
    "sentiment":             "BULLISH",
    "strategy_version":      2,
}
ok_write = write_trade(test_trade)
check("write_trade() — insert new row", ok_write)

# update (upsert) — เปลี่ยน status → CLOSED
if ok_write:
    test_trade_closed = dict(test_trade)
    test_trade_closed["status"]     = "CLOSED"
    test_trade_closed["pnl"]        = 15.50
    test_trade_closed["close_time"] = datetime.utcnow().isoformat()
    ok_upsert = write_trade(test_trade_closed)
    check("write_trade() — upsert (status CLOSED + pnl)", ok_upsert)

# ──3. Read trade ────────────────────────────────────────────────
print("\n──3. Read trade ──")
from db.reader import get_trades

trades = get_trades(symbol=_TEST_SYMBOL, account_login=_TEST_ACCOUNT)
check("get_trades() returns list", isinstance(trades, list), f"{len(trades) if trades else 0} rows")

if trades:
    our = next((t for t in trades if t.get("ticket") == _TEST_TICKET), None)
    check("test ticket found in results", our is not None)
    if our:
        check("status == CLOSED", our.get("status") == "CLOSED", our.get("status"))
        check("pnl == 15.50", our.get("pnl") == 15.50, str(our.get("pnl")))
        check("direction == BUY", our.get("direction") == "BUY")

# ──4. Write cycle ───────────────────────────────────────────────
print("\n──4. Write cycle ──")
test_cycle = {
    "symbol":        _TEST_SYMBOL,
    "at":            datetime.utcnow().isoformat(),
    "ticket":        _TEST_TICKET,
    "total_cost_usd": 0.0123,
    "agents": {
        "TEST_AGENT": {
            "model":              "claude-sonnet-4-6",
            "input_tokens":       500,
            "output_tokens":      200,
            "cache_read_tokens":  100,
            "cache_write_tokens": 50,
            "cost_usd":           0.0123,
            "cache_hit_rate":     0.5,
            "latency_ms":         1200,
        }
    }
}
ok_cycle = write_cycle(test_cycle)
check("write_cycle() — insert cycle + agent_usage", ok_cycle)

# ──5. Read accounting ───────────────────────────────────────────
print("\n──5. Read accounting ──")
from db.reader import get_accounting

acc = get_accounting(symbol=_TEST_SYMBOL)
check("get_accounting() returns dict", isinstance(acc, dict))
if acc:
    check("summary keys exist", all(k in acc for k in ["summary", "agents", "today", "daily"]))
    total_cost = acc.get("summary", {}).get("total_cost_usd", -1)
    check("total_cost_usd >= 0", total_cost >= 0, f"${total_cost:.4f}")
    if acc.get("agents"):
        check("agent_usage rows returned", True, f"{len(acc['agents'])} agent(s)")
    else:
        check("agent_usage rows returned", False, "ไม่มี agent data")

# ──6. Cleanup ───────────────────────────────────────────────────
print("\n──6. Cleanup test data ──")
try:
    client.table("trades").delete().eq("ticket", _TEST_TICKET).eq("account_login", _TEST_ACCOUNT).execute()
    check("delete test trade from trades", True)
except Exception as e:
    check("delete test trade from trades", False, str(e))

try:
    client.table("agent_usage").delete().eq("agent_name", "TEST_AGENT").execute()
    client.table("cycles").delete().eq("ticket", _TEST_TICKET).execute()
    check("delete test cycle + agent_usage", True)
except Exception as e:
    check("delete test cycle + agent_usage", False, str(e))

# ──Summary ──────────────────────────────────────────────────────
passed = sum(results)
total  = len(results)
print(f"\n{'='*44}")
print(f"  Result: {passed}/{total} passed", end="")
if passed == total:
    print("  ✅ ทุก test ผ่าน — DB พร้อมใช้งาน")
else:
    print(f"  ❌ {total - passed} test(s) ล้มเหลว")
print()
