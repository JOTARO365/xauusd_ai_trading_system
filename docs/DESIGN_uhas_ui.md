# DESIGN — UHAS-style UI redesign (reference + spec)

> ที่มา: วิเคราะห์จากวิดีโอ UHAS "The Inner Circle Trade" (Uhas Trader, 10 ส.ค. 2026,
> members-only, cap ผ่าน claude-in-chrome). อ้างอิงภาพ 4 เฟรม: title / scenario-view
> (นาที 15) / price-zone bar / chart-view (นาที 40).
> เป้า: ปรับ dashboard เราให้ **หน้าตา + การนำเสนอ data** ใกล้ UHAS โดย **ไม่แตะ data/endpoint เดิม**
> (display-only, additive). CORE INVARIANT ไม่กระทบ — นี่คือ viz ไม่ใช่ entry logic.

---

## 1. Feature/UI ที่ UHAS โชว์ (จากภาพ)

### 1.1 หน้า Scenario (การวางแผน)
- **Scenario cards** 3 ใบเรียงแนวนอน: `แผน ก` / `แผน ข` / `แผนพัก` — แต่ละใบ:
  - **probability %** (เช่น 58% / 38%) + tag ซื้อ/ขาย (สีเขียว/แดง)
  - **โซนเข้า** (range เช่น 4,323.94–4,326.51) · **คัท**(stop) · **โซนเป้า** (range)
  - **RR** "ได้ต่อเสีย" (เช่น 1.15 ต่อ 10.50 เท่า)
  - **trigger** ("รอแตะ 4,319.05–4,325.22 แล้วแท่ง 15m ปิดกลับเหนือ 4,325.22")
- **หัวการ์ด "มองขาขึ้น"** + score: ความสอดคล่อง 70/100 · ความมั่นใจ 72/100
- **validity window**: "วางแผน 18:19 น. หมดอายุ 22:19 น."
- **แถบ price-zone แนวนอน** บนสุด: `คัท | โซนเข้า | โซนเป้า` color-coded (เทา/ทอง/เทา) + RR + trigger

### 1.2 หน้า Chart
- **Candlestick chart** + **โซน S/R วาดเป็นแถบ (band) โปร่งแสง** (ไม่ใช่เส้น) — เพดาน/พื้นรับ/โซนเข้า มีป้ายช่วงราคา
- **เส้น projected path** (dashed + arrow) ทิศคาดการณ์รอบนี้
- **Right rail = การ์ดซ้อน**:
  - **S/R level + สถิติ**: ราคา · แตะ N ครั้ง · อายุ N แท่ง · แตะล่าสุด N แท่งก่อน · **role-flip** (เคยรับ→ต้าน)
  - **Directional prob**: "ขาขึ้น 51.14% · n=219 · ช่วง 44.56–57.69"
  - **Expected-move card**: ระยะแกว่งจริง 61.30$ (6,130 จุด) · ค่ากลางขยับรอบข่าว 0.54% · n=253
  - **Pattern probability** (เช่น 69%) · **news-next countdown**
- **TF selector** 15m/30m/1h/4h

---

## 2. Design language (สี/สไตล์)

UHAS = dark theme + gold accent — **ตรงกับ theme เราอยู่แล้ว** (`--bg #050505`, `--gold #e8b04b`).
ไม่ต้อง re-theme ทั้งระบบ. ปรับเฉพาะ component ให้เป็น UHAS-style:

| element | UHAS | token เรา (มีแล้ว) |
|---|---|---|
| background | ดำ/เทาเข้ม | `--bg` `--surface` `--surface2` |
| entry zone / highlight | ทอง/อำพัน โปร่งแสง | `--gold` `--gold-dim` |
| target / neutral zone | เทา โปร่งแสง | `--muted` + alpha |
| buy / support | เขียว | `--green` |
| sell / resistance / stop | แดง | `--red` |
| ตัวเลข | mono | `--mono` (JetBrains Mono) |
| card | พื้นเข้มกว่า + border บาง | `.card` / `--surface2`+`--border` |

**หลัก:** zone = แถบโปร่งแสง alpha 0.08–0.16 (ไม่ทึบ กัน candle หาย), ความเข้ม ∝ strength%.

---

## 3. Redesign — component spec (map กับ data ที่มี)

| UHAS component | data source เรา (มีแล้ว) | สถานะ | build |
|---|---|---|---|
| **Chart S/R zone bands** | `bs.zones` (sr_meta/setups strength) + `/api/cluster-map` + `/api/sr-ladder` | มี | **slice 1 (ทำเลย)** — canvas overlay วาดแถบ |
| S/R stat card (touch/age/flip) | `/api/sr-ladder` (touches/bounce%/break%/grade) + `/api/sr-level-stats` | มี | slice 2 — restyle เป็นการ์ด UHAS |
| Scenario cards (ก/ข/พัก) | สังเคราะห์: regime + S/R zone + algo signal + RR ที่ algo คำนวณ + trigger | สร้างได้ | slice 3 |
| Directional-prob gauge | `event_stats` (up/down% + n) + `macro_quant` | มี(บางส่วน) | slice 4 |
| Expected-move card | `event_stats` (avg move $) + ATR + `realized_moves` | มี | slice 4 |
| Projected path | จาก regime bias + zone ถัดไป | ต้องคิด | later |
| Pattern probability | — (candle-pattern stats) | ต้องหา source | later |

**ต้องหา data source เพิ่ม:** candle-pattern probability stats (เดียวที่ยังไม่มี).

---

## 4. Slice plan (ค่อยๆ ทำ, additive, ไม่แตะ data เดิม)

1. **[ทำเลย] Chart S/R zone bands** — canvas overlay บน `#price-chart`, วาดแถบจาก `bs.zones`
   (เส้น price-line เดิมคงไว้). gold-only เหมือน overlay เดิม. 0 endpoint ใหม่.
2. S/R stat card restyle (Key Levels → การ์ด UHAS: ราคา/touches/age/flip)
3. Scenario card panel (ก/ข/พัก สังเคราะห์จาก algo signal + S/R + RR + trigger + validity)
4. Directional-prob gauge + Expected-move card (จาก event_stats + ATR)

**กติกา:** ทุก slice = additive (element/ฟังก์ชัน/CSS ใหม่), ไม่ลบ/แก้ data flow เดิม,
ไม่เพิ่ม AI call (compute-in-code จาก data ที่มี), test ว่า dashboard เดิมไม่พัง ก่อนไป slice ถัดไป.
