"""
shadow_report.py — สรุปผล A/B shadow ของ chart_watcher (token optimization Phase 1+2)

รัน:  python scripts/shadow_report.py
อ่าน: logs/shadow_chart.jsonl (สร้างเมื่อ CHART_SHADOW=true)
ตอบ: variant "terse + Haiku" เปลี่ยน "การตัดสินใจเทรด" มั้ย + ประหยัดเงินจริงแค่ไหน

เกณฑ์สลับจริง: decision_match ≥ 95%
"""
import json
import sys
from pathlib import Path

# ราคา Anthropic ($/1M tokens) — input, output
PRICES = {
    "claude-sonnet-4-6":          (3.00, 15.00),
    "claude-haiku-4-5-20251001":  (0.80,  4.00),
    "claude-haiku-4-5":           (0.80,  4.00),
}
REAL_MODEL = "claude-sonnet-4-6"   # production (verbose) ใช้ Sonnet
AVG_INPUT_TOK = 1852               # chart_watcher input/call จริง (logs/accounting.json)
CALLS_IN_LOG_PERIOD = 405          # chart_watcher calls ในช่วงที่วัด ($14.06 / 407 cycles)

# Windows console เป็น cp874 (Thai) — บังคับ UTF-8 ไม่ให้ ±/ไทย crash
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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

real_tok = [r["real_out_tok"]   for r in rows if r.get("real_out_tok")]
shad_tok = [r["shadow_out_tok"] for r in rows if r.get("shadow_out_tok")]
avg_r = sum(real_tok) / len(real_tok) if real_tok else 0
avg_s = sum(shad_tok) / len(shad_tok) if shad_tok else 0
save_pct = (1 - avg_s / avg_r) * 100 if avg_r else 0

shadow_model = next((r.get("shadow_model") for r in reversed(rows) if r.get("shadow_model")),
                    "claude-sonnet-4-6")
r_in, r_out = PRICES.get(REAL_MODEL,   (3.0, 15.0))
s_in, s_out = PRICES.get(shadow_model, (3.0, 15.0))
# ต้นทุน/call: input เท่ากันทั้งคู่ (input เดียวกัน) ต่างที่ "ราคา model" + "จำนวน output token"
cost_real   = (AVG_INPUT_TOK*r_in + avg_r*r_out) / 1e6
cost_shadow = (AVG_INPUT_TOK*s_in + avg_s*s_out) / 1e6
cost_save_pct = (1 - cost_shadow/cost_real) * 100 if cost_real else 0
period_save   = (cost_real - cost_shadow) * CALLS_IN_LOG_PERIOD

print(f"\n=== Shadow A/B Report — chart_watcher ({n} cycles) ===")
print(f"  variant: terse + {shadow_model}   vs   real: verbose + {REAL_MODEL}\n")
print(f"  decision_match (SIGNAL + CONF±5) : {dm}/{n} = {dm/n*100:5.1f}%   <- ตัวชี้ขาด")
print(f"  signal_match  (BUY/SELL/NO_TRADE): {sm}/{n} = {sm/n*100:5.1f}%")
print(f"  (SL/TP คำนวณในโค้ดแล้ว — เหมือนกันทั้ง 2 variant ไม่ต้องเทียบ)")
print(f"\n  output tokens : real {avg_r:.0f}  ->  shadow {avg_s:.0f}  (ลด {save_pct:.0f}%)")
print(f"  cost/call     : ${cost_real:.5f}  ->  ${cost_shadow:.5f}  (ลด {cost_save_pct:.0f}%)")
print(f"  ประหยัดในช่วงที่วัด ({CALLS_IN_LOG_PERIOD} calls): ~${period_save:.2f} "
      f"(จาก chart_watcher ~$7.1)")

verdict = f"✅ ผ่าน — terse+{shadow_model.split('-')[1]} ปลอดภัย พร้อมสลับจริง" if dm/n >= 0.95 \
          else "❌ ยังไม่ผ่าน — variant เปลี่ยนการตัดสินใจ เก็บ verbose+Sonnet ไว้"
print(f"\n  เกณฑ์ (decision_match >= 95%, n>=100): {verdict}")
if n < 100:
    print(f"  ⚠️  ข้อมูลยังน้อย (n={n}) — เก็บให้ถึง ~100 cycles ก่อนตัดสิน")

diffs = [r for r in rows if not r.get("decision_match")][-5:]
if diffs:
    print(f"\n  ตัวอย่าง DIFF ล่าสุด ({len(diffs)}):")
    for r in diffs:
        print(f"    {r['ts']}: real={r['real']['signal']}/{r['real']['confidence']}"
              f"  vs  shadow={r['shadow']['signal']}/{r['shadow']['confidence']}")
print()
