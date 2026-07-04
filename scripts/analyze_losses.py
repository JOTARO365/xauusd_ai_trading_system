"""
Loss Analysis Script — XAUUSD AI Trading System
วิเคราะห์ trade จาก Supabase เพื่อหาสาเหตุการขาดทุน
รัน: python scripts/analyze_losses.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from collections import defaultdict
from db.connection import get_client

SEP = "═" * 60

# ── ดึง trades ทั้งหมด ────────────────────────────────────────
client = get_client()
res = client.table("trades").select(
    "ticket,direction,entry_type,status,lot,entry_price,sl,tp,pnl,"
    "opened_at,closed_at,technical_signal,technical_confidence,"
    "trend,sr_zone,sr_strength,pa_action,sentiment"
).execute()

all_trades = res.data or []
closed = [t for t in all_trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]
wins   = [t for t in closed if float(t.get("pnl") or 0) > 0]
losses = [t for t in closed if float(t.get("pnl") or 0) <= 0]

print(f"\n{SEP}")
print("  LOSS ANALYSIS — XAUUSD AI Trading System")
print(SEP)

# ── 1. Overview ───────────────────────────────────────────────
total_pnl  = sum(float(t.get("pnl") or 0) for t in closed)
win_pnl    = sum(float(t.get("pnl") or 0) for t in wins)
loss_pnl   = sum(float(t.get("pnl") or 0) for t in losses)
avg_win    = win_pnl  / len(wins)   if wins   else 0
avg_loss   = loss_pnl / len(losses) if losses else 0
rr_actual  = abs(avg_win / avg_loss) if avg_loss != 0 else 0

print(f"\n[1] OVERVIEW")
print(f"  Trades รวม   : {len(all_trades)}  (Open: {len(all_trades)-len(closed)}, Closed: {len(closed)})")
print(f"  Win / Loss   : {len(wins)} W / {len(losses)} L  (WR: {len(wins)/len(closed)*100:.1f}%)" if closed else "  ไม่มี closed trade")
print(f"  Total P&L    : ${total_pnl:+.2f}")
print(f"  Avg Win      : ${avg_win:+.2f}    Avg Loss: ${avg_loss:+.2f}")
print(f"  Actual R:R   : {rr_actual:.2f}  (ตั้ง 2.0)")

# ── 2. Loss by direction ──────────────────────────────────────
print(f"\n[2] LOSS BY DIRECTION")
by_dir = defaultdict(lambda: {"w":0,"l":0,"pnl":0.0})
for t in closed:
    d = t.get("direction","?")
    p = float(t.get("pnl") or 0)
    if p > 0: by_dir[d]["w"] += 1
    else:     by_dir[d]["l"] += 1
    by_dir[d]["pnl"] += p
for d, v in sorted(by_dir.items()):
    tot = v["w"] + v["l"]
    wr  = v["w"]/tot*100 if tot else 0
    print(f"  {d:8s}: {v['w']}W/{v['l']}L  WR {wr:.0f}%  P&L ${v['pnl']:+.2f}")

# ── 3. Loss by entry_type ─────────────────────────────────────
print(f"\n[3] LOSS BY ENTRY TYPE")
by_et = defaultdict(lambda: {"w":0,"l":0,"pnl":0.0})
for t in closed:
    k = t.get("entry_type","?") or "?"
    p = float(t.get("pnl") or 0)
    if p > 0: by_et[k]["w"] += 1
    else:     by_et[k]["l"] += 1
    by_et[k]["pnl"] += p
for k, v in sorted(by_et.items(), key=lambda x: x[1]["pnl"]):
    tot = v["w"] + v["l"]
    wr  = v["w"]/tot*100 if tot else 0
    print(f"  {k:30s}: {v['w']}W/{v['l']}L  WR {wr:.0f}%  P&L ${v['pnl']:+.2f}")

# ── 4. Loss by trend ──────────────────────────────────────────
print(f"\n[4] LOSS BY TREND")
by_trend = defaultdict(lambda: {"w":0,"l":0,"pnl":0.0})
for t in closed:
    k = t.get("trend","?") or "?"
    p = float(t.get("pnl") or 0)
    if p > 0: by_trend[k]["w"] += 1
    else:     by_trend[k]["l"] += 1
    by_trend[k]["pnl"] += p
for k, v in sorted(by_trend.items(), key=lambda x: x[1]["pnl"]):
    tot = v["w"] + v["l"]
    wr  = v["w"]/tot*100 if tot else 0
    print(f"  {k:12s}: {v['w']}W/{v['l']}L  WR {wr:.0f}%  P&L ${v['pnl']:+.2f}")

# ── 5. Loss by confidence bucket ─────────────────────────────
print(f"\n[5] LOSS BY CONFIDENCE")
buckets = {"<50":[],"50-59":[],"60-69":[],"70-79":[],"80+":[],"?": []}
for t in closed:
    c = t.get("technical_confidence")
    p = float(t.get("pnl") or 0)
    if c is None:
        buckets["?"].append(p)
    elif c < 50:  buckets["<50"].append(p)
    elif c < 60:  buckets["50-59"].append(p)
    elif c < 70:  buckets["60-69"].append(p)
    elif c < 80:  buckets["70-79"].append(p)
    else:         buckets["80+"].append(p)
for label, pnls in buckets.items():
    if not pnls: continue
    w = sum(1 for p in pnls if p > 0)
    l = sum(1 for p in pnls if p <= 0)
    wr = w/(w+l)*100 if (w+l) else 0
    print(f"  conf {label:6s}: {w}W/{l}L  WR {wr:.0f}%  P&L ${sum(pnls):+.2f}")

# ── 6. Loss by SR zone ────────────────────────────────────────
print(f"\n[6] LOSS BY SR ZONE")
by_sr = defaultdict(lambda: {"w":0,"l":0,"pnl":0.0})
for t in closed:
    k = t.get("sr_zone","?") or "NONE"
    p = float(t.get("pnl") or 0)
    if p > 0: by_sr[k]["w"] += 1
    else:     by_sr[k]["l"] += 1
    by_sr[k]["pnl"] += p
for k, v in sorted(by_sr.items(), key=lambda x: x[1]["pnl"]):
    tot = v["w"] + v["l"]
    wr  = v["w"]/tot*100 if tot else 0
    print(f"  {k:12s}: {v['w']}W/{v['l']}L  WR {wr:.0f}%  P&L ${v['pnl']:+.2f}")

# ── 7. Consecutive losses ─────────────────────────────────────
print(f"\n[7] CONSECUTIVE LOSSES (streak)")
sorted_closed = sorted(closed, key=lambda x: x.get("opened_at",""))
max_streak = cur_streak = 0
streak_details = []
for t in sorted_closed:
    p = float(t.get("pnl") or 0)
    if p <= 0:
        cur_streak += 1
        max_streak = max(max_streak, cur_streak)
    else:
        if cur_streak > 0:
            streak_details.append(cur_streak)
        cur_streak = 0
if cur_streak > 0:
    streak_details.append(cur_streak)
print(f"  Max streak    : {max_streak} ขาดทุนติดกัน")
if streak_details:
    print(f"  Streaks found : {sorted(streak_details, reverse=True)[:10]}")

# ── 8. Worst trades ───────────────────────────────────────────
print(f"\n[8] WORST 5 TRADES")
worst = sorted(losses, key=lambda x: float(x.get("pnl") or 0))[:5]
for t in worst:
    conf = t.get("technical_confidence","?")
    et   = (t.get("entry_type") or "?")[:20]
    trnd = t.get("trend","?") or "?"
    sr   = t.get("sr_zone","?") or "?"
    pnl  = float(t.get("pnl") or 0)
    dt   = (t.get("opened_at") or "")[:10]
    print(f"  ${pnl:+7.2f}  {dt}  {t.get('direction','?'):4s}  conf={conf}  {et:20s}  trend={trnd}  sr={sr}")

# ── 9. แท้จริงตอนขาดทุน: SL vs pnl ──────────────────────────
print(f"\n[9] SL ANALYSIS — ปิดด้วย SL หรือ manual?")
sl_hit = partial = 0
for t in losses:
    entry = float(t.get("entry_price") or 0)
    sl    = float(t.get("sl") or 0)
    pnl   = float(t.get("pnl") or 0)
    lot   = float(t.get("lot") or 0.01)
    if entry == 0 or sl == 0:
        continue
    sl_pips   = abs(entry - sl) / 0.01
    exp_loss  = lot * sl_pips * 0.01 * 100
    if abs(pnl) >= exp_loss * 0.85:
        sl_hit += 1
    else:
        partial += 1
print(f"  ชนแท่ง SL เต็ม : ~{sl_hit}  (loss ≥ 85% ของ max SL)")
print(f"  ปิดก่อน SL     : ~{partial}")

# ── 10. Summary + Recommendations ────────────────────────────
print(f"\n{SEP}")
print("  RECOMMENDATIONS")
print(SEP)

if not closed:
    print("  ⚠ ไม่มี closed trade ใน DB — DRY_RUN หรือยังไม่มีข้อมูล")
else:
    wr = len(wins)/len(closed)*100
    if wr < 40:
        print("  ❌ Win Rate < 40% — สัญญาณ entry ไม่แม่นพอ")
        print("     → เพิ่ม STREAK_MIN_CONFIDENCE หรือ MIN_TECHNICAL_CONFIDENCE")
    elif wr < 50:
        print("  ⚠ Win Rate 40-50% — ต้องการ R:R ≥ 2.5 เพื่อ break-even")
    else:
        print(f"  ✅ Win Rate {wr:.0f}% — อยู่ในเกณฑ์ที่ยอมรับได้")

    if rr_actual < 1.5:
        print("  ❌ Actual R:R < 1.5 — TP ถูก hit น้อยกว่า SL มาก")
        print("     → ตรวจ DYNAMIC_TP, ลด DEFAULT_TP_PIPS, หรือ trailing stop")
    elif rr_actual < 2.0:
        print(f"  ⚠ Actual R:R {rr_actual:.2f} — ต่ำกว่าเป้า 2.0")
    else:
        print(f"  ✅ Actual R:R {rr_actual:.2f} — ดี")

    # worst entry type
    worst_et = min(by_et.items(), key=lambda x: x[1]["pnl"]) if by_et else None
    if worst_et and worst_et[1]["l"] >= 2:
        print(f"  ⚠ Entry type ที่ขาดทุนมากสุด: {worst_et[0]}  (P&L ${worst_et[1]['pnl']:+.2f})")

    # worst trend
    worst_tr = min(by_trend.items(), key=lambda x: x[1]["pnl"]) if by_trend else None
    if worst_tr and worst_tr[1]["l"] >= 2:
        print(f"  ⚠ Trend ที่ขาดทุนมากสุด: {worst_tr[0]}  (P&L ${worst_tr[1]['pnl']:+.2f})")

    if max_streak >= 3:
        print(f"  ⚠ Max streak {max_streak} — STREAK_PROTECTION ควรกระตุ้นที่ 3")

print()
