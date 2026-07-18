# Quant-entry backtest investigation — findings (2026-07-18)

**สรุป 1 บรรทัด:** algo family systematic ง่ายๆ (breakout + mean-reversion + regime-routing บน OHLC)
**ไม่มี edge จริง**ทั้งบน BTC และทอง เมื่อทดสอบแบบไม่โกงตัวเอง (นับ N, DSR, PBO, **intrabar fill**, net cost).
อย่ากลับมาลอง naive breakout/mean-rev ซ้ำโดยไม่มี lever ใหม่จริงๆ.

## บริบท
ส่วนหนึ่งของ entry overhaul ([[entry-exit-quant-overhaul]]) — ทดสอบว่าถ้าแทน entry ปัจจุบัน
(LLM confidence + heuristic gates) ด้วย deterministic quant algo (จาก skill `quant-systematic-trading`)
จะมี edge ที่พิสูจน์ได้มั้ย. ทดสอบบน BTC (โมดูลใหม่) ก่อน แล้วชี้ harness เดียวกันมาที่ทอง.

## Harness (reusable, offline, ไม่แตะ live/gold pipeline)
| script | ทำอะไร |
|--------|--------|
| `scripts/fetch_btc.py` | ดึง OHLCV จาก Binance (BTCUSDT / PAXGUSDT gold-proxy), ฟรีไม่ต้อง key |
| `scripts/btc_backtest.py` | single-config exploratory backtest (ดูสัญญาณหยาบ ไม่ใช่ validation) |
| `scripts/btc_validate.py` | **full gauntlet**: param sweep→นับ N · Deflated Sharpe · PBO/CSCV · walk-forward · net cost. symbol-agnostic (`argv[1]`=data, `argv[2]`=fee) |
| `scripts/gold_strengthen.py` | theory-motivated filter (confirm buffer / vol-floor / wider SL) + **holdout 30% ล็อก** + **intrabar-fill toggle** (`argv[2]="intrabar"`) |

## ผลการทดสอบ (ตามลำดับ)
| # | การทดสอบ | ผล | verdict |
|---|----------|-----|---------|
| 1 | BTC naive 2-algo, 1yr hourly (503 ไม้) | net −191R, WR 31%, CI ทั้งช่วงติดลบ, OOS − | ❌ ไม่มี edge |
| 2 | BTC→gold intermarket feature (F8) | predictive corr ≈ 0, ไม่ lead, rolling corr −0.30↔+0.62 (ไม่คงที่) | ❌ ไม่ทำนาย |
| 3 | BTC regime-routed 3yr, N=54, gauntlet | best Sharpe +0.033 < SR0 +0.194, **DSR 0**, OOS − | ❌ overfit/no edge |
| 4a | **Gold** regime-routed, close-path fill, 5.9yr, N=12 | **DSR 0.981**, holdout +77.9R, 12/12 กำไร, PBO 0 | ⚠️ **ดูผ่าน — แต่ artifact** |
| 4b | **Gold เดียวกัน + intrabar H/L fill (สมจริง)** | **DSR 0.051, 0/12 กำไร**, net −54R | ❌ **edge หายเกลี้ยง** |

## 🔑 บทเรียนสำคัญ — close-path fill = backtest artifact
ข้อ 4 คือหัวใจ: config เดียวกัน, data เดียวกัน, cost เดียวกัน — เปลี่ยนแค่**วิธีเช็ค SL/TP**:
- **close-path** (เช็ค SL เฉพาะตอนราคาปิดเลย level) → DSR 0.981 "validated" น่า deploy
- **intrabar** (ไส้เทียน low/high แตะ SL/TP ในแท่ง, SL-priority ถ้าชนทั้งคู่) → DSR 0.051 ขาดทุน

close-path **มองไม่เห็น stop ที่โดน wick** → ประเมิน loss ต่ำเกินอย่างรุนแรง. ด้วย RR3 (TP ไกล 7.5·ATR
แทบไม่โดน แต่ SL 2.5·ATR โดน wick บ่อย) ผลต่างมหาศาล. **ถ้าเชื่อ DSR 0.98 แล้ว deploy = เสียเงินจริง
กับระบบที่ดู validated แล้ว.** → ทุก backtest/replay ต้องใช้ intrabar fill + realistic cost เสมอ.

## ข้อสรุป
- **ปิด BTC direction** (trading + gold-feature) — พิสูจน์ 3 ทางว่าไม่คุ้ม.
- **ไม่มี deployable edge จาก simple algo family** บนทองเช่นกัน (หลัง intrabar).
- สอดคล้อง premise ของ skill: edge retail ส่วนใหญ่ไม่มีจริง; คุณค่าของวินัย = **ไม่เสียเงิน**กับ backtest หลอกตา.

## สิ่งที่ยังไม่ถูก refute (สุขุมขึ้น)
- **F1-F7 + zone `bounce_pct` empirical prior** บน decision context จริงของบอท (ต่างจาก hourly breakout) —
  รอ `decision_snapshots.jsonl` สะสม. prior ว่า "systematic edge ง่ายๆ มีจริง" **ลดลงมาก**;
  แม้ทำก็ต้องผ่าน **intrabar-fill + net-cost** gauntlet เดียวกัน.
- บอทปัจจุบัน (LLM+gates) เก็บไว้รันตามเดิม — ยังไม่มีตัวแทน systematic ที่พิสูจน์แล้วว่าดีกว่า.

## Data regeneration (blob ไม่ commit — regenerable)
```
& $PY scripts/fetch_btc.py                 # BTC 1yr → data/btc_{daily,hourly}_raw.json
& $PY scripts/fetch_btc.py PAXGUSDT        # gold-proxy 1yr
# 3yr / full: ปรับ days ใน fetcher หรือ inline (ดู git log commit นี้)
```

เกี่ยว: skill `quant-systematic-trading` (§6 validation rigor), `docs/VALIDATION_CHECKLIST.md`,
`docs/ROADMAP_quant_entry_migration.md`, [[entry-exit-quant-overhaul]].
