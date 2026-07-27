# BACKLOG — ideas (ยังไม่อนุมัติ / ยังไม่โค้ด)

> logic/money changes ต้องผ่าน EXPLAIN-BEFORE-ACTING + อนุมัติ + validated-or-off (iron rule).

---

## Efficient-Frontier — multi-symbol weight allocation
สถานะ: **BACKLOG** · ที่มา: PDF "Copy of Stock Analysis" (PyPortfolioOpt) + multi-symbol engine ปัจจุบัน · 2026-07-27

**Idea:** จัดน้ำหนัก (position size %) ข้ามคู่ที่เทรด live (ทอง/WTI/BTC/silver...) แบบ **Markowitz efficient frontier**
(max Sharpe ภายใต้ constraint) แทน fixed lot/แยกคู่อิสระ → กระจายความเสี่ยงตาม correlation + risk-adjusted return.

**ทำอะไร:**
- input: expected return + covariance matrix ต่อคู่ (จาก real edge / regime) · constraint (เช่น Σw=1, per-pair cap)
- objective: max Sharpe (หรือ min variance) → optimal weights → แปลงเป็น lot ต่อคู่
- rebalance เป็นระยะ

**⚠️ กับดัก (จาก PDF เอง + quant skill):**
- **"past return = future return" คือจุดอ่อนหลัก** (PDF ยอมรับเป็น con) → ต้องใช้ forecast/shrunk return ไม่ใช่ mean อดีตดิบ
- covariance ไม่ stationary (regime เปลี่ยน) → ต้อง shrinkage (Ledoit-Wolf) + rolling window
- คู่น้อย (6 คู่ FULL) + correlated (gold-complex) → efficient frontier ให้ประโยชน์จำกัด (silver = diversifier เดียว ตาม [[multipair-universe-decision]])
- ต้อง net-of-cost + validated-or-off

**ต่อยอดจาก:** real_edge (return/cov ต่อคู่), pair_collector (correlation มีใน universe_probe), multi_symbol_executor (แปลง weight→lot)

**คู่กับ:** [[docs/DESIGN_algo_selector.md]] (selector เลือก "algo ไหน" · efficient-frontier เลือก "น้ำหนักคู่ไหน") — คนละชั้น เสริมกัน

**ไม่ใช่ตอนนี้เพราะ:** ต้องมี live edge หลายคู่ก่อน (ตอนนี้ WTI/BTC เพิ่งเริ่ม n น้อย) · forecast return ยังไม่มี · CORE INVARIANT ไม่กระทบ (เป็น sizing ไม่ใช่ entry prediction)
