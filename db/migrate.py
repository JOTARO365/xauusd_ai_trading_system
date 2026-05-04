"""
One-time migration: trades.json + accounting.json → PostgreSQL

รัน: python db/migrate.py
ต้องการ: DATABASE_URL ใน .env หรือ environment variable
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from db.connection import is_available
from db.writer import write_trade, write_cycle


def migrate_trades(trades_path: str = "logs/trades.json") -> int:
    if not os.path.exists(trades_path):
        print(f"  ไม่พบ {trades_path} — ข้าม")
        return 0
    with open(trades_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    trades = data.get("trades", [])
    ok = 0
    for t in trades:
        if write_trade(t):
            ok += 1
    return ok


def migrate_accounting(accounting_path: str = "logs/accounting.json") -> int:
    if not os.path.exists(accounting_path):
        print(f"  ไม่พบ {accounting_path} — ข้าม")
        return 0
    with open(accounting_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cycles = data.get("cycles", [])
    ok = 0
    for c in cycles:
        if write_cycle(c):
            ok += 1
    return ok


if __name__ == "__main__":
    print("=== XAUUSD DB Migration to Supabase ===")

    if not is_available():
        print("[ERROR] ไม่สามารถเชื่อมต่อ Supabase ได้")
        print("  ตรวจสอบ SUPABASE_URL และ SUPABASE_KEY ใน .env")
        sys.exit(1)

    print("[1/2] Migrating trades.json...")
    n = migrate_trades()
    print(f"  {n} trades imported")

    print("[2/2] Migrating accounting.json...")
    n = migrate_accounting()
    print(f"  {n} cycles imported")

    print("\nDone! ข้อมูลอยู่ใน Supabase แล้ว")
