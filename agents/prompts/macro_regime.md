# CURRENT MACRO REGIME — Analyst override context

ไฟล์นี้คือ "ช่วงเศรษฐกิจปัจจุบัน" ที่ Agent 3 (Analyst) ใช้ปรับการตีความปัจจัยพื้นฐาน
เพราะความสัมพันธ์ของทองกับมาโคร **ไม่คงที่ — มันพลิกตาม regime**
(เช่น เงินเฟ้อร้อน → ทองขึ้น เมื่อ Fed ผ่อน/real yields ลง  แต่ → ทองลง เมื่อ Fed สู้เงินเฟ้อ)

วิธีใช้:
- อัปเดตไฟล์นี้เมื่อ **ช่วงเศรษฐกิจเปลี่ยน** (Fed เปลี่ยนโหมด, ธีมข่าวใหญ่เปลี่ยน) — ไม่ใช่ทุกวัน
- ป้อนได้จาก workflow `youtube-to-knowhow` (สรุปไลฟ์ตลาดรายวัน → กลั่นเป็น regime → วางที่นี่)
- เนื้อหาทุกบรรทัดใต้ REGIME_START ถูกฉีดเข้า analyst เป็น "บริบทที่ authoritative สำหรับช่วงนี้"
- **ลบเนื้อหาใต้ REGIME_START ให้ว่าง = analyst กลับไปใช้ default gold_factors ปกติ** (พฤติกรรมเดิม ปลอดภัย)
- อย่าใส่ระดับราคา/เป้า TP ที่นี่ (มันหมดอายุเร็ว + เป็นงานของ chart agent) — ใส่เฉพาะ "ทิศของปัจจัย" และ "ธีม/เหตุการณ์"

<!-- REGIME_START -->
PHASE: geopolitics(ME) drives safe-haven; new Fed members -> macro stance shifting
OVERRIDES (else use default gold_factors):
- inflation_surprise -> BULLISH gold (hot PCE/CPI + real yields soft)
- geopolitics de-escalation/ceasefire -> LESS safe-haven -> gold dip risk (peace != flat)
DRIVERS: ME ceasefire/troop-withdrawal; leader statements at set times
FILTER: oil move != gold unless clear causal link to gold
CATALYSTS: scheduled political/geo statements = volatility windows (not only data prints)
UPDATED: 2026-06-05 (HFM live 06-04)
