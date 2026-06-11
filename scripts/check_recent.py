"""เช็กไม้ล่าสุดจาก DB (บอท VM เขียนเข้า Supabase) — รัน: python scripts/check_recent.py
ดูว่าหลัง deploy guards บอทเปิดไม้อะไรบ้าง ทิศตรงข่าวไหม conf ผ่าน floor ไหม
"""
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
import config  # noqa: F401  (loads .env)
from db.reader import get_trades

t = get_trades("XAUUSD") or []
cut = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()[:19]
recent = [x for x in t if (x.get("timestamp") or "") >= cut]
print(f"trades last 48h: {len(recent)}  (0 = guards/gates บล็อกหมด หรือบอทไม่ได้รัน)")
for x in sorted(recent, key=lambda r: r.get("timestamp") or "")[-15:]:
    print(f"  {(x.get('timestamp') or '')[:16]} {str(x.get('source') or '')[:6]:<6} "
          f"{x.get('direction') or '?':<4} {(x.get('entry_type') or '?')[:14]:<14} "
          f"conf={x.get('technical_confidence')} status={x.get('status')} "
          f"pnl={x.get('pnl')} close={x.get('close_reason') or '-'}")
