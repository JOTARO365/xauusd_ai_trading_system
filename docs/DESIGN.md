# DESIGN.md — XAUUSD Dashboard Design System

Style: **Data-Dense Dashboard** (financial terminal) · dark-first · WCAG AA · monospace-numeric.
เป้า: ทุกสี/spacing/typography มาจาก **token เดียว** — ห้าม hardcode hex ที่ซ้ำ token (ต้นเหตุ "theme ไม่เข้ากัน").

อ้างอิง: ui-ux-pro-max (Data-Dense Dashboard) · แนว [Fortress](https://tailwindcss.com) financial-terminal (dark surfaces + accent เฉพาะ gain/loss).

---

## 1. Color tokens (source of truth — `:root` ใน index.html)

**กฎเหล็ก:** ใช้ `var(--x)` เสมอ · ห้ามพิมพ์ hex ตรงๆ ถ้ามี token อยู่แล้ว.

| กลุ่ม | token | ค่า | ใช้ตอน |
|---|---|---|---|
| พื้น | `--bg` `--bg2` | #050505 #0a0a0a | หน้า/ชั้นล่าง |
| การ์ด | `--surface` `--surface2` `--surface3` | #131210 #181613 #1e1b16 | card/panel/hover |
| เส้น | `--border` `--border2` `--border3` | #262320 #2e2a24 #38332a | ขอบ/divider |
| ทอง (brand) | `--gold` `--gold-2` | #e8b04b #cf9835 | header/accent/แบรนด์ |
| **เขียว (กำไร)** | `--green` `--green-2` | #4ade80 #22c55e | ค่าบวก/BUY/ผ่าน |
| **แดง (ขาดทุน)** | `--red` `--red-2` | #ef4444 #dc2626 | ค่าลบ/SELL/fail |
| น้ำเงิน | `--cyan` | #60a5fa | link/info/neutral-active |
| เตือน | `--amber` | #f59e0b | warning/รอ |
| ม่วง | `--violet` | #a78bfa | badge/หมวดพิเศษ |
| ตัวอักษร | `--text` `--text-dim` `--muted` `--muted2` | #f3f4f6 #b4bcc8 #9ca3af #4b5563 | หลัก/รอง/จาง/จางสุด |

**สีต้องห้าม (ลบ/แทนด้วย token):** `#ff4444`→`--red` · `#44ff88`→`--green` · `#F4C430`/`#e8b923`→`--gold` ·
`#2a2a2a`/`#262a31`→`--border`/`--surface2` · `#9aa3b8`→`--text-dim` · `#3D4456`→`--border2` · `#9ca3af`→`--muted`.

### semantic (อย่าผูกสีดิบกับความหมาย — ผูก token)
- กำไร/บวก/ขึ้น = `--green` · ขาดทุน/ลบ/ลง = `--red` · กลาง/รอ = `--muted`
- brand/heading/accent = `--gold` (ใช้ให้น้อย = สงวนไว้เน้น) · link/info = `--cyan`

---

## 2. Typography
- ตัวเลข/ราคา/ตาราง = **`--mono`** (JetBrains Mono) — tabular, align จุดทศนิยม
- หัวข้อ/label = **`--display`/`--sans`** (Space Grotesk)
- ขนาด: body 12–13px (dense) · label 10–11px · section-title 14–15px · KPI 20–28px
- line-height 1.4–1.5 · น้ำหนัก: 400 ปกติ, 600–700 ตัวเลขเน้น/หัวข้อ

## 3. Spacing & density (density 9/10)
- scale: **4 · 8 · 12 · 16 · 24** (px) — dense, padding การ์ด 8–12px
- ตาราง: cell padding `4px 8px` · row-hover `--surface2`
- gap ระหว่าง card 10px · section margin 14px

## 4. Components (แบบเดียวทั้งระบบ)
- **card**: `background:var(--surface)` `border:1px solid var(--border)` `border-radius:8px` `padding:8–12px`
- **section-title**: `--display` 14–15px, สี `--text`, margin-top 14px
- **badge**: pill, bg `--x-dim`, text `--x` (เช่น เขียว = --green-dim/--green)
- **ค่าบวก/ลบ**: สี `--green`/`--red` + prefix `+`/`−` เสมอ
- **ปุ่ม toggle**: state ชัด (LIVE=--green · SHADOW=--cyan · OFF=--muted)

## 5. Motion (subtle 2/10)
- transition 150–300ms `ease` · hover เท่านั้น (ไม่มี decorative)
- loading = spinner ธีม (`--gold`) · เคารพ `prefers-reduced-motion`

## 6. Do / Don't
| ✅ Do | ❌ Don't |
|---|---|
| `color:var(--red)` | `color:#ff4444` (สีซ้ำนอก token) |
| สีเดียวต่อความหมาย | 3 เฉดทองในหน้าเดียว |
| SVG icon (Lucide/Heroicons) | emoji เป็น icon ปุ่ม |
| ตัวเลข mono + align | ตัวเลข sans เลื่อนไม่ตรง |
| accent (ทอง) เท่าที่จำเป็น | ทองทุกที่ = ไม่มีอะไรเด่น |

## 7. Pre-delivery checklist
- [ ] 0 hardcoded hex ที่ซ้ำ token (grep `#[0-9a-f]{6}` เหลือเฉพาะใน `:root`)
- [ ] contrast ≥ 4.5:1 (text บน surface) · badge ≥ 3:1
- [ ] cursor-pointer ทุกอันคลิกได้ · focus ring keyboard
- [ ] responsive 768/1024/1440 · ตารางกว้าง scroll ใน container (ไม่ดันหน้า)
- [ ] prefers-reduced-motion respected

---

## 8. งานที่ต้องทำ (consolidation)
1. **replace hardcoded → token** (สีต้องห้าม §1) ทั่ว index.html
2. รวมเฉดซ้ำ: red/green/gold ให้เหลือชุดเดียว
3. ย้าย ad-hoc gray (`#2a2a2a` ฯลฯ) เข้า `--border`/`--surface` scale
4. audit ตาราง: cell padding + hover + mono numeric ให้เหมือนกันทุกตาราง
