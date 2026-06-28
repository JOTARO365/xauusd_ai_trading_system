"""Summarize logs/gate_blocks.jsonl — วัดว่า gate ตัวไหน block อะไรไปบ้าง.
ใช้พิสูจน์ guard ที่ไม่มี replay (news-first/HTF-fade/counter-spike) ว่า block ไม้ดีไหม.
รัน: python scripts/analyze_gate_blocks.py [days]
"""
import sys
import json
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

LOG = Path("logs") / "gate_blocks.jsonl"
days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
cutoff = datetime.now(timezone.utc) - timedelta(days=days)

if not LOG.exists():
    print(f"ยังไม่มีไฟล์ {LOG} — รอ bot รันสะสม block ก่อน")
    sys.exit(0)

rows = []
for line in LOG.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
        ts = datetime.fromisoformat(r["at"])
        if ts >= cutoff:
            rows.append(r)
    except Exception:
        continue

if not rows:
    print(f"ไม่มี block ใน {days} วันล่าสุด")
    sys.exit(0)

print(f"gate blocks (last {days}d): n={len(rows)}  "
      f"range {rows[0]['at'][:16]} .. {rows[-1]['at'][:16]}")

# by gate category
by_gate = defaultdict(list)
for r in rows:
    by_gate[r.get("gate") or "?"].append(r)
print("\n== by gate (sorted by count) ==")
for g, items in sorted(by_gate.items(), key=lambda kv: -len(kv[1])):
    dirs = Counter((x.get("signal") or "?") for x in items)
    trends = Counter((x.get("trend") or "?") for x in items)
    print(f"  {g:<16} n={len(items):<5} signals={dict(dirs)}  trends={dict(trends)}")

# anti-fade guards focus (the unproven ones)
print("\n== anti-fade guards (unproven — เฝ้าดูเป็นพิเศษ) ==")
for g in ("news_first", "htf_fade", "counter_spike", "counter_trend"):
    items = by_gate.get(g, [])
    if not items:
        print(f"  {g:<16} 0 blocks")
        continue
    print(f"  {g:<16} n={len(items)}")
    for x in items[-5:]:
        print(f"     {x['at'][:16]} sig={x.get('signal')} trend={x.get('trend')} "
              f"conf={x.get('conf')} sent={x.get('sentiment_bias')} price={x.get('price')}")
        print(f"        reason: {x.get('reason')}")
