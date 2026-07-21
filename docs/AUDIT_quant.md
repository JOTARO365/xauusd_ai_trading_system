# QUANT AUDIT — algo v2 + live flags (2026-07-21)

ผู้ตรวจ: quant-auditor (self-audit — agent registry ยังไม่ reload; ทำตาม iron-rule #12 + skill
`quant-systematic-trading`). Posture: **adversarial — พยายาม refute edge**. ตัวเลขทุกตัว reproduce เอง.

> **สรุปผู้บริหาร:** ระบบ live ตอนนี้วางไม้เงินจริงบน **2 กลยุทธ์ที่ไม่มี validated edge** (momentum −EV,
> fade −EV). justify ได้แค่ "lot จิ๋ว + เก็บ data". **RANGE fade (real order) = NO-GO — ปิดทันที.**

---

## EDGE 1 — RANGE fade ที่ S/R zones  →  VERDICT: **NULL (ไม่มี edge)**

**หลักฐาน (reproduce: `python scripts/fade_zone_gauntlet.py`, 70k H1):**
- KDE mid-strength zones (16-25 touches), intrabar-pessimistic + net cost + OOS 60/40 + null(random-level fade):
  - RR1.5: expR −0.002 (20p) → −0.050 (40p); PSR₀ 0.10-0.48; OOS **OUT expR −0.058** ❌
  - RR2.0: expR +0.003 (20p แทบ 0) → −0.045 (40p); OOS **OUT −0.065** ❌; **REAL (−0.021) แย่กว่า NULL (−0.005)**
- ล้มทุกเกณฑ์: expR≤0 หลัง cost จริง · PSR₀ ≪ 0.95 · แพ้/เสมอ null · OOS พังทั้ง 2 RR (in-sample→OOS = ลายเซ็น overfit)

**🔴 REAL-MONEY FLAG:** `.env REGIME_PENDING_FADE=true` = วาง **BUY_LIMIT/SELL_LIMIT จริง** บนกลยุทธ์นี้.
→ **NO-GO. ปิด `REGIME_PENDING_FADE=false` ทันที** (live-reload). เก็บ shadow ผ่าน journal (REGIME_SR_ENTRY) พอ.

---

## EDGE 2 — KDE mid-strength zone "edge" (respect 47% / +11.6% null)  →  VERDICT: **proxy artifact / INSUFFICIENT**

**หลักฐาน (`scripts/cluster_kde_research.py`):** respect-rate +11.6% เหนือ null (n=373) — **แต่เป็น proxy metric**
(react ≥0.8ATR ก่อนทะลุ) ไม่ใช่ trade EV. เมื่อ sim fade จริง (Edge 1) edge **หายเกลี้ยง** (−EV, แพ้ null).
= ตัวอย่างคลาสสิกที่ skill เตือน: **proxy ดูมี edge, trade จริงไม่มี.**
→ ใช้ได้แค่ **decision-support display** (KDE คัดโซนคม 8 vs 20 — ok) **ห้ามเป็น signal.** ไม่ใช่ edge.

---

## EDGE 3 — Momentum breakout (TREND) — **live entry ปัจจุบัน**  →  VERDICT: **INSUFFICIENT (−EV after cost)**

**หลักฐาน (reproduce: `data/regime_analytics.json`, regenerated 05:53 วันนี้):**
- TREND / momentum_breakout: N=1575, WR 33.1%, **exp_R −0.054 (−EV หลัง cost 30p)**, sharpe −0.038,
  **PSR₀ 0.067**, breakeven_wr 34.9% (WR 33.1% < breakeven), grade **C**.
- D1 momentum เคยผ่าน OOS แต่ **ตก null test** (artifact จาก fat-tail baseline) — ดู continue.md.

**🔴 REAL-MONEY FLAG:** `REGIME_LIVE_TICK=true` วาง market entry จริงจาก momentum นี้.
→ **marginal NO-GO.** เทรด signal −EV. justify ได้แค่ lot จิ๋ว (risk 0.5%, MAX 0.03) เพื่อเก็บ data จริง.
แนะนำ: ยอมรับเปิดต่อ**เฉพาะถ้า**ตั้งใจจ่ายค่า −EV เล็กน้อยแลก data live; ไม่งั้น shadow.

---

## EDGE 4 — entry_gate p_edge / RSI-confirm  →  VERDICT: **VALID (data-collection only), INVALID as live gate**

`agents/entry_gate.py` W = ILLUSTRATIVE, `fitted=False` — น้ำหนัก log-odds **ไม่ได้ fit/calibrate** กับ outcome จริง.
`p_edge` **ไม่ใช่ calibrated probability** → ใช้ตัดสิน EV/gate live ไม่ได้ (skill §2/§7).
✅ ถูกต้องที่ปัจจุบัน entry_gate ใช้ **journal-only** (ไม่แตะ live pending — pending ใช้ `_weak` veto แยก).
→ คง journal-only. ก่อนใช้ gate live: fit weights จาก journal + reliability diagram + OOS.

---

## EDGE 5 — algo_journal counterfactual methodology  →  VERDICT: **VALIDATED (sound basis)**

`agents/algo_journal.py`: intrabar first-touch (`_resolve`), assume-SL เมื่อ TP+SL แท่งเดียว (pessimistic),
net cost 30p, MFE/MAE, resolve จาก forward bars หลัง signal bar (outcome labeling — ไม่ใช่ feature leak),
dedup 1/bar, pending 2-phase (fill→TP/SL/EXPIRED). **ไม่มี look-ahead ใน labeling.**
✅ เป็น data pipeline ที่ถูกต้องสำหรับ validation อนาคต (fit model + calibrate). 1 caveat: fade capture ใช้
entry_gate near-gate (บันทึกเมื่อราคาใกล้) — dataset จะ bias ไป near-events; ระวังตอน fit.

---

## Go / No-Go สรุป (live enablement)

| flag | edge | verdict | action |
|---|---|---|---|
| `REGIME_PENDING_FADE` | fade S/R | **NULL** | 🔴 **ปิดทันที** (real order บน −EV) |
| `REGIME_LIVE_TICK` (momentum) | TREND breakout | INSUFFICIENT (−EV) | 🟠 shadow หรือรับ −EV จิ๋วแลก data |
| `REGIME_SR_EXIT` | TP/trailing | n/a (exit refinement) | 🟡 ต่ำเสี่ยง แต่สร้างบน entry ที่ยัง unvalidated |
| `REGIME_SR_SIZING` | sizing | valid (กลไก) | 🟢 ok |
| `REGIME_SR_ENTRY` | fade→journal | valid (shadow) | 🟢 keep — เก็บ data |

**Bottom line:** ยังไม่มี directional edge ที่ VALIDATED เลย (สอดคล้อง prior: ทองทิศทำนายไม่ได้ด้วย retail TA).
สิ่งที่ควรทำ live = **shadow เก็บ data + risk management** ไม่ใช่ real directional bets. หากต้องการ live จริง
ควรจำกัดที่ lot จิ๋วสุด + ยอมรับว่าจ่ายค่า negative-EV เพื่อ data (เป็น research cost ไม่ใช่กลยุทธ์ทำกำไร).

*Meta: audit นี้ทำโดย self (agent registry reload session หน้า). `.claude/agents/quant-auditor.md` พร้อม
audit อิสระครั้งต่อไป.*
