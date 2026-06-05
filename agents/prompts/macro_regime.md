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
PHASE: re-accelerating inflation + Fed on hold + negative real rates -> structurally BULLISH gold; geopolitics(ME) adds safe-haven swings
DATA (as of 2026-06): CPI YoY ~3.8%, m/m HOT & re-accelerating (Mar +1.05%, Apr +0.85%); FedFunds 3.63% on hold; 10Y 4.48% rising -> real policy rate ~negative
OVERRIDES (else use default gold_factors):
- inflation_surprise -> BULLISH gold (CPI re-accelerating, Fed not hiking, real yields negative)
- geopolitics de-escalation/ceasefire -> LESS safe-haven -> gold dip risk (peace != flat)
- WATCH: if Fed turns hawkish vs the inflation re-accel -> inflation->gold can flip BEARISH
DRIVERS: ME ceasefire/troop-withdrawal; leader statements at set times
FILTER: oil move != gold unless clear causal link to gold
CATALYSTS: scheduled political/geo statements = volatility windows (not only data prints)
UPDATED: 2026-06-05 (AlphaVantage CPI/FedFunds/10Y + HFM live 06-04)
