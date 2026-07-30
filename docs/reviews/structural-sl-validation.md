# Structural SL — validation (2026-07-30)

**ปัญหา:** algo momentum เข้าถูกทางแต่โดน SL ก่อน — SL fixed/ATR วางในที่ว่าง ไม่พิงโครงสร้าง D1+
→ noise เขี่ยออกก่อนราคาไปต่อ.

**กฎ (user directive 07-30):** SL **ต้องอยู่ปลายไส้แท่ง D1 หรือ H4 ปิดล่าสุด เสมอ** (ไม่ว่าทุนน้อยแค่ไหน):
- BUY → SL = `low(แท่งปิดล่าสุด) − buffer·ATR` · SELL → SL = `high(...) + buffer·ATR`
- เลือก TF ตาม `STRUCTURAL_SL_PICK`: **farthest** = ไส้ไกลสุด (มัก D1, กัน noise มากสุด — backtest ดีสุด) · nearest = ไส้ใกล้สุด (มัก H4, SL แคบ)
- **ไม่ clamp, ไม่ fallback** เป็น pip เดิม (ยกเว้น geometry ผิดข้างทุก TF). **lot = min เสมอ + ข้าม risk-cap** (ยอม risk% เกินเพดาน).
- **เปลี่ยน SL อย่างเดียว, คง TP เดิม** (ไม่ scale RR).

## Backtest (no look-ahead)

`scripts/structural_sl_backtest.py` — signal ≤ i · ไส้ D1 ใช้แท่งที่ปิดก่อน time signal · forward-sim จาก i+1 ·
บาร์เดียวชน SL+TP นับ SL ก่อน (pessimistic). window 60,000 H1. mult ต่อคู่ตาม live (WTI 0.7).

### เปลี่ยน SL อย่างเดียว + คง TP เดิม + pick=farthest (= พฤติกรรม live)

| คู่ | fixed expR | D1-wick expR | Δ | SL-hit fixed→D1 |
|---|---|---|---|---|
| GOLD# | +0.028 | **+0.040** | +0.012 | 65.7% → **25.8%** |
| USDJPY# | −0.019 | **+0.017** | +0.036 | 67.3% → **26.4%** |
| EURUSD# | −0.121 | **−0.020** | +0.101 | 70.7% → **30.3%** |
| BTCUSD# | +0.074 | +0.045 | −0.030 | 64.2% → **26.5%** |
| OILCash# (WTI) | +0.027 | −0.004 | −0.031 | 73.4% → **28.0%** |

- **ทุกคู่ SL-hit ลด ~65-73% → ~26-30%** = แก้อาการ "โดน SL ก่อน" ได้ทั้งกระดาน.
- `worsened` (fix TP → D1-wick SL) = **0 ทุกคู่** — ไม่เคยเปลี่ยนไม้ชนะเป็นแพ้ (SL กว้างจนแทบไม่ชน).
- expR: GOLD/USDJPY/EURUSD ดีขึ้น (EUR ดีขึ้นมากจากลบหนัก), BTC/WTI แย่ลงเล็กน้อยแต่ยัง ~เสมอ.

### เทียบ: คง RR (TP ขยายตาม SL) = แย่ (อย่าใช้)

SL กว้าง × RR → TP ไกลเกิน ราคาไม่ถึงใน 240 H1 → TIMEOUT พุ่ง (GOLD 491, WTI 586) → expR ติดลบ
(GOLD −0.008, WTI −0.151). จึงเลือก **คง TP เดิม**. (รันเทียบ: `BT_RR_PRESERVE=1 python scripts/structural_sl_backtest.py`)

## caveat

- profile = **WR สูง(~70%) / RR ต่ำ** (SL กว้าง + TP เดิม) — ไม้แพ้ขาดทุนก้อนใหญ่ (แต่ min-lot คุมค่าเงินสัมบูรณ์).
- sim ไม่รวม BE/trailing (live มี) — wide SL อาจ trail ล็อกกำไรแทน timeout จริง.
- window เดียว in-sample เทียบ relative · เปิดบน demo เก็บ forward OOS ก่อนเงินจริง.

## การตั้งค่า

- `STRUCTURAL_SL_GOLD=true` · `STRUCTURAL_SL_MSE=true` (user สั่งเปิดทุก algo ทุกคู่)
- SL ปลายไส้ D1 + min lot + ข้าม standdown เมื่อ flag on · restart บอทหลัง flip (logic เป็น code)
