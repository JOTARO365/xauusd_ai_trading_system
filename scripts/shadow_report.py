"""
shadow_report.py — สรุปผล A/B shadow ของ chart_watcher (Phase 1 token optimization)

รัน:  python scripts/shadow_report.py
อ่าน: logs/shadow_chart.jsonl (สร้างเมื่อ CHART_SHADOW=true)
ตอบ: terse output เปลี่ยน "การตัดสินใจเทรด" มั้ย + ประหยัด token แค่ไหน

เกณฑ์สลับมาใช้ terse จริง: decision_match ≥ 95%
"""
import json
from pathlib import Path

F = Path(__file__).resolve().parent.parent / "logs" / "shadow_chart.jsonl"
if not F.exists():
    print("ยังไม่มี logs/shadow_chart.jsonl — ตั้ง CHART_SHADOW=true แล้วรัน bot ก่อน")
    raise SystemExit(0)

rows = [json.loads(l) for l in F.read_text(encoding="utf-8").splitlines() if l.strip()]
n = len(rows)
if not n:
    print("ไฟล์ว่าง — ยังไม่มี shadow cycle"); raise SystemExit(0)

dm  = sum(1 for r in rows if r.get("decision_match"))
sm  = sum(1 for r in rows if r.get("sig_match"))
slm = sum(1 for r in rows if r.get("sl_match"))
tpm = sum(1 for r in rows if r.get("tp_match"))

real_tok = [r["real_out_tok"]   for r in rows if r.get("real_out_tok")]
shad_tok = [r["shadow_out_tok"] for r in rows if r.get("shadow_out_tok")]
avg_r = sum(real_tok) / len(real_tok) if real_tok else 0
avg_s = sum(shad_tok) / len(shad_tok) if shad_tok else 0
save_pct = (1 - avg_s / avg_r) * 100 if avg_r else 0

print(f"\n=== Shadow A/B Report — chart_watcher ({n} cycles) ===\n")
print(f"  decision_match (SIGNAL + CONF±5) : {dm}/{n} = {dm/n*100:5.1f}%   <- ตัวชี้ขาด")
print(f"  signal_match  (BUY/SELL/NO_TRADE): {sm}/{n} = {sm/n*100:5.1f}%")
print(f"  sl_match  (เป๊ะ)                  : {slm}/{n} = {slm/n*100:5.1f}%")
print(f"  tp_match  (เป๊ะ)                  : {tpm}/{n} = {tpm/n*100:5.1f}%")
print(f"\n  output tokens: real {avg_r:.0f}  ->  shadow {avg_s:.0f}  (ลด {save_pct:.0f}%)")
print(f"  ประมาณการประหยัด chart_watcher output: ~${save_pct/100*4.61:.2f} จาก $4.61")

verdict = "✅ ผ่าน — terse ปลอดภัย พร้อมสลับจริง" if dm/n >= 0.95 \
          else "❌ ยังไม่ผ่าน — terse เปลี่ยนการตัดสินใจ เก็บ verbose ไว้"
print(f"\n  เกณฑ์ (decision_match >= 95%): {verdict}")

diffs = [r for r in rows if not r.get("decision_match")][-5:]
if diffs:
    print(f"\n  ตัวอย่าง DIFF ล่าสุด ({len(diffs)}):")
    for r in diffs:
        print(f"    {r['ts']}: real={r['real']['signal']}/{r['real']['confidence']}"
              f"  vs  shadow={r['shadow']['signal']}/{r['shadow']['confidence']}")
print()
