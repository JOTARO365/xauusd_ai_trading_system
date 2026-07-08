# HAS Terminal "Gold Intelligent" — Feature Inventory + Architecture Blueprint

> **จุดประสงค์:** เอกสารอ้างอิงสำหรับสร้างระบบ analysis terminal แบบ UHAS เอง (โดยเลียนแบบ
> architecture) ในอนาคต — กลั่นจากไลฟ์ UHAS 3 stream ผ่าน context-firewall subagents
> (transcript ไม่เข้า main context). **ไม่ใช่สิ่งที่ต้องทำตอนนี้** — เป็น backlog/blueprint.
>
> **Sources:** UHAS lives 2026-07-01 (`sZHD5FpEpBU`), 07-02 เช้า (`Di_9o0LaIGI`),
> 07-02 NFP (`cn190HRnoIM`). อัปเดต: 2026-07-03.
>
> ⚠️ **Caveat:** UHAS เปิดเผย architecture "บาง" มาก (ไลฟ์ ~90% เป็น trade-calling).
> facts ที่ยืนยันได้มีจำกัด, บางอย่าง (เช่น "1M AI agents") เป็น marketing-tinged.
> แยก [FACT] / [IMPLIED] / [MARKETING] ทุกข้อ.

---

## PART 1 — FEATURE INVENTORY (รวม 3 stream, dedupe แล้ว)

จัดกลุ่มตาม "layer" ที่ feature นั้นอยู่ (สำคัญต่อการ copy architecture):

### A. Deterministic math layer (คำนวณด้วยสูตร ไม่ใช่ LLM)
| # | Feature | รายละเอียด |
|---|---------|-----------|
| A1 | **AI S/R "key level" zones** | โซนรับ-ต้าน auto-draw (เขียว/แดง), persist ตอน scroll. UHAS ยืนยัน = "สูตรคณิตศาสตร์บน historical price + weighting" **ไม่ใช่ LLM output** |
| A2 | **Zone strength %** | แต่ละโซนมี % ความแข็งแรงจาก weighting scheme (volume + touch + structure) |
| A3 | **Auto role-flip** | ราคาทะลุโซน → reclassify ต้าน↔รับ อัตโนมัติ (realtime price re-analysis) |
| A4 | **Zone rationale** | อธิบาย "ทำไม": volume-profile KDE, touch significance (FDR), volatility-adjusted width, **gamma/Max-Pain option walls, COT, futures positioning, fair value** — "ไม่ใช่แค่เลขกลม" |
| A5 | **Auto-trendline** | (ใหม่ 07-02) auto-draw channel/trendline + break-probability read-out (เช่น ต้าน 4188 = 37% break / 63% hold) |
| A6 | **Tick / 1-second chart + clustering** | timeframe เร็วสุดระดับวินาที (dot render); คำนวณ S/R จาก tick-level clustering nodes (เช่น 4119/4128/4137) |

### B. LLM-generated layer (narrative + probability)
| # | Feature | รายละเอียด |
|---|---------|-----------|
| B1 | **Live speech transcription** | subtitle ไทยรายประโยคของ Fed/ECB panel สด (ASR + translate บน LLM ของเขา) |
| B2 | **Per-sentence hawk/dove tagging** | AI จับทุกประโยค weight เหยี่ยว/พิราบ/กลาง สดๆ → เทรด sentiment shift |
| B3 | **Gold-impact analysis cards** | สรุป AI เป็นระยะ ("Fed เน้น uncertainty → หนุนทองผ่าน real yield ต่ำ") + สรุปทั้งคลิปหลังจบ |
| B4 | **Probabilistic calls** | LLM ให้ % จาก news + market + trend strength (เช่น "target 4200 = 62%", "break 26%/reject 74%") |
| B5 | **Chat AI** | sidebar ถาม-ตอบกับ AI |
| B6 | **"Advanced Analysis" (ปุ่มเดียว)** | (07-02) 1-click ได้: multi-TF verdict (H1/H4/D down, W sideways) + zones + **trade plan พร้อม entry+RR** ("ถ้าลง 4050 → buy RR 6:1") + role-flip prob (เด้ง 78%/สำเร็จ 86%) + pattern/trendline + O/H/L |

### C. Data / calendar layer
| # | Feature | รายละเอียด |
|---|---------|-----------|
| C1 | **Economic calendar detail** | countdown + prev/forecast + auto interpretation (NFP 114 vs 172 = USD-negative/gold+) |
| C2 | **Event importance auto re-tiering** | red/orange/yellow ปรับ dynamic (Trump speech demote เป็น orange เพราะ Warsh สำคัญกว่า; ADP red→orange) |
| C3 | **Forward price-impact projection** | (07-02) ฉายกรอบราคาต่อ event anchor ราคาสด (AHE 4059 → up 4112 / down 4021 ~1.3%) |
| C4 | **Historical event-reaction stats ("heat map")** | NFP 113 ครั้ง: ขึ้น 55/ลง 40/นิ่ง 5%, D+1/D+2 momentum, beat/miss conditional (beat→avg −0.01%, miss→+0.04%) |
| C5 | **Speaker panel schedule** | ตารางผู้พูด + สี impact weighting |
| C6 | **News / Macro Economic pages** | feed ข่าว + หน้า macro + "gold drivers" board (research/scrape → linked relationship view) |

### D. Simulation layer (in development)
| # | Feature | รายละเอียด |
|---|---------|-----------|
| D1 | **Warroom / "simulation arena"** | [MARKETING] อ้าง ~**1,000,000 AI agents** วางเป็น "positions" ในโลกจำลอง → harvest consensus. 07-02 รันได้แค่ unemployment (ไม่ใช่ NFP), **~60% โหวต "sell on fact"**. UHAS บอกเอง 70-80% เสถียร ยัง dev |

### E. Reliability notes (บันทึกไว้เตือนตัวเอง)
- 07-02 NFP: terminal **พิมพ์เลขผิดเป็น 172K** (echo prior), แก้เป็น 57K หลัง ~30 วิ → **realtime data ingestion มี lag/bug**, ต้องมี validation layer
- ไม่เคยโชว์ backtest / accuracy % เลยทั้ง 3 stream — **probabilistic calls ยังพิสูจน์ไม่ได้**
- ไม่เคยให้ entry/exit call ("AI วิเคราะห์ ไม่ใช่เรา" — compliance)

---

## PART 2 — ARCHITECTURE BLUEPRINT (5 layers)

จาก UHAS: *"สร้าง AI ก่อน แล้วขยายเป็น terminal"* — **LLM เป็นศูนย์กลาง, feature เป็น wrapper**

```
┌─────────────────────────────────────────────────────────────┐
│  5. PRESENTATION — web terminal (chart + zones + cards + chat) │
├─────────────────────────────────────────────────────────────┤
│  4. LLM CORE (self-hosted, local server)                      │
│     - narrative, hawk/dove tagging, probabilistic calls       │
│     - [IMPLIED] RAG over research/news knowledge layer         │
├──────────────────────┬──────────────────────────────────────┤
│  3a. MATH LAYER       │  3b. RESEARCH/RAG LAYER               │
│  (deterministic)      │  (LLM-fed context)                    │
│  - S/R zones + %      │  - news scrape + calendar             │
│  - trendlines         │  - "gold drivers" relationship map    │
│  - clustering (tick)  │  - COT / options positioning          │
├──────────────────────┴──────────────────────────────────────┤
│  2. DATA INGESTION                                            │
│     - own tick collector (price → 1s granularity, stored)     │
│     - news feeds / economic calendar / macro / geopolitics    │
├─────────────────────────────────────────────────────────────┤
│  1. INFRA — local server(s), backend team push สด 7 วัน/สัปดาห์│
└─────────────────────────────────────────────────────────────┘
```

### Facts ต่อ layer
- **[FACT] LLM**: self-built LLM รันบน **local server ของเขาเอง**. ไม่บอก base model / param / fine-tune vs prompt. เหตุผล local = **control/customization** (ฝังสูตร/ทฤษฎีลงโมเดลเอง) ไม่ใช่ cost/latency/privacy
- **[FACT] Math layer**: S/R + trendline = สูตรคณิต + weighting → % strength (LLM ไม่ยุ่ง)
- **[FACT] Tick ingestion**: เก็บ tick เอง ดูได้ถึง 1 วินาที (jumpiness = raw tick render)
- **[IMPLIED] Research layer**: "research → เก็บข้อมูล → สร้างความเชื่อมโยง" = RAG/knowledge-graph-shaped (ไม่เคยเรียกชื่อ)
- **[MARKETING] "1M agent simulated world"**: multi-agent Monte-Carlo/ABM feed model — vague, likely embellished, copy ตรงๆ ไม่ได้
- **ไม่เปิดเผย**: GPU count, framework, vector DB, backtest engine, ทีม split

---

## PART 3 — MAP เข้า stack ของเรา (มี / สร้าง / ข้าม)

| UHAS layer | เรามีอยู่ | gap | คุ้มสร้างไหม |
|-----------|----------|-----|-------------|
| A1-A3 S/R zones + strength + flip | ✅ `chart_watcher` (swing + touch + HTF confluence + role-flip logic ใน `manage_zone_break_close`) | แค่ presentation | ✅ ทำ dashboard viz (S) |
| A4 zone rationale (gamma/COT) | ❌ positioning data | COT ฟรี (CFTC), gamma แพง (CME) | COT ✅ / gamma ✗ |
| A5 auto-trendline | ❌ | geometric detection module | 🟡 nice-to-have |
| A6 tick/1s clustering | ⚠️ MT5 มี tick | เราไม่ scalp วินาที (cycle 5 นาที) | ✗ ไม่คุ้ม |
| B1-B3 speech ASR + hawk/dove | ❌ | Whisper + Haiku pipeline | 🟡 L / ~$5-10/เดือน (ROI ลดหลัง Warsh ยกเลิก guidance) |
| B4 probabilistic calls | ⚠️ conf score | calibrate เป็น % + backtest | 🟡 M |
| B6 Advanced Analysis (1-click) | ✅ chart+decision agents | รวมเป็น report เดียวบน dashboard | ✅ M / ฟรี |
| C1-C2 calendar + re-tier | ✅ FF calendar + analyst | dynamic re-rank | S |
| C3 forward projection | 🟡 มี event_stats แล้ว | สูตร: ราคาสด ± avg\|move\| | ✅ S / ฟรี |
| C4 event-reaction stats | ✅ **ทำแล้ว** `scripts/event_reaction_stats.py` (NFP 179 ครั้ง) | เพิ่ม CPI/FOMC | ✅ ทำต่อ |
| C6 gold-drivers RAG | ⚠️ news vector search + `macro_regime.md` | knowledge graph | 🟡 |
| D1 Warroom | ❌ | — | ✗ marketing |
| LLM self-host | ❌ ใช้ Claude API | local model | ✗ (Claude ถูกกว่า/ฉลาดกว่าจนกว่าจะ scale มาก) |

**สรุป: เรามีโครง ~60-70% แล้ว** — ที่ขาดจริงและคุ้ม = COT, forward projection, Advanced-Analysis report, live speech (ถ้า ROI คุ้ม)

---

## PART 4 — BUILD-YOUR-OWN ROADMAP (ถ้าจะสร้างเวอร์ชันเราเอง)

**หลักการ:** เลียน architecture (LLM-at-center + math layer + data ingestion) แต่**ไม่ต้อง self-host LLM** —
Claude API ทำหน้าที่ LLM core ได้ ถูกกว่า/ฉลาดกว่า ($7/วันปัจจุบัน) จนกว่าจะ scale ระดับหลายพัน user

- **Phase 0 (มีแล้ว):** chart_watcher (math S/R) + analyst (LLM narrative) + FF calendar + news vector + event_stats + dashboard = **นี่คือ UHAS ย่อส่วนอยู่แล้ว**
- **Phase 1 (ฟรี, S-M):** COT ingestion (CFTC weekly) → macro_regime; forward price projection บน dashboard; Advanced-Analysis report (รวม agent output เป็นการ์ดเดียว); เพิ่ม CPI/FOMC เข้า event_stats
- **Phase 2 (~$5-10/เดือน, L):** live speech pipeline (yt-dlp → Whisper ASR → Haiku hawk/dove tag → dashboard panel + force_fresh เข้า analyst) — เฉพาะ red event
- **Phase 3 (M, ถ้าอยากมี edge จริง):** backtest engine ให้ probabilistic call (calibrate conf → % แล้ววัด reliability บน history — ตัวที่ UHAS ไม่เคยโชว์ = จุดที่เราเหนือกว่าได้)
- **ข้าม:** gamma/max-pain (data แพง), 1s scalp chart, Warroom, self-host LLM

---

## PART 5 — บทเรียนเชิงกลยุทธ์ (ไม่ใช่แค่ feature)

1. **Math ≠ LLM** — UHAS แยกชัด: S/R/trendline = สูตร (deterministic, auditable), LLM ทำแค่ narrative + %. **ตรงกับ design เราแล้ว** (gates เป็น Python, Claude ตัดสินใจ) — อย่าให้ LLM ทำสิ่งที่โค้ดทำได้
2. **Probabilistic > directional** — เขาไม่บอก "ซื้อ/ขาย" บอก "% เด้ง/ทะลุ" → เราแปลง conf score เป็น calibrated % + backtest ได้ (edge เหนือเขา เพราะเขาไม่มี backtest โชว์)
3. **Reliability layer จำเป็น** — NFP misprint 172K→57K = ถ้าไม่มี validation, bad data → bad call. เรามี fail-open guards แล้ว, ต้องคงไว้
4. **Event stats เป็น prior ไม่ใช่ signal** — UHAS ใช้ heat map เป็นบริบท ไม่ใช่ trigger. เราทำถูกแล้ว (`_event_prior_lines` ฉีดเป็น context)

---

## PART 6 — UHAS live 08-07 additions (candidate features, ยังไม่ build)

จากไลฟ์ oRjLdb2AiX4 (08-07, transcript 133K ~95% price-call — terminal feature ถูกเอ่ยถึงน้อย
เพราะเป็นภาพบนจอ). เก็บเฉพาะที่ผู้พูดอ้างถึงจริง + ยังไม่มีในระบบ + display-only/computed-in-code.
เรียงตามความคุ้มค่า:

1. **Per-zone touch-reaction stat** (คุ้มสุด — ต่อยอด zone ladder เดิม)
   - ผู้พูด: "แตะโซนนี้ 79 แท่งก่อน เด้ง ~44 เหรียญ, ต้านแข็ง 99%"
   - มีบางส่วนแล้ว: `bot_status.zones.sr_meta` มี `touches` + `strength` + `why` (แสดง/ต่อยอดได้เลย display-only)
   - ที่ขาด: **bars-since-touch (recency)** + **avg bounce ($)** ต่อ zone → ต้องคำนวณจาก OHLC intraday
     ฝั่ง bot (chart_watcher) แล้วใส่เพิ่มใน sr_meta (agent code — ต้องขออนุมัติ)
   - value: อัปเกรด zone จาก %นิ่งๆ → "เด้งแรง/สดจริงแค่ไหน" = prior เข้าเทรดชัดขึ้น

2. **Liquidity pool map** — ✅ **DONE 2026-07-08** (chart_watcher.find_liquidity_pools → BSL/SSL cluster
   equal highs/lows บน H1, display-only zero-token; dashboard renderLiquidity. v2 = swept-detection ยังไม่ทำ)
   — จุด stop-cluster เหนือ/ใต้ราคา (ต่างจาก S/R zone)
   - ผู้พูด: "liquidity อยู่ตรงไหน" → pool บน ~4125, ล่าง ~4100/4098; พูดเรื่อง "กวาด" ก่อนกลับตัว
   - data: MT5 price — equal-highs/equal-lows clustering + swing extremes ล่าสุด
   - value: ทองชอบกวาด stop ที่ pool ก่อนวิ่งจริง → ชี้จุด sweep-and-reverse

3. **Volume wall + buy/sell imbalance**
   - ผู้พูด: "โซนวอลุ่มสะสมหนา = กำแพงจริง", "เริ่มมีวอลุ่มฝั่งเซลล์"
   - data: MT5 tick-volume by price (HVN) + up/down-bar volume delta
   - ⚠️ caveat: MT5 gold volume = **tick-volume ไม่ใช่ contract จริง** — ต้องติดป้ายกำกับเสมอ
   - value: ราคาที่คนเล่นหนา + เตือน order-flow พลิกทิศ

4. **Auto-Fibonacci (multi-TF + RSI)** — ✅ **DONE 2026-07-08** (display-only; data มีใน bot_status
   fib_h4/fib_h1 จาก chart_watcher.calc_fibonacci อยู่แล้ว — เพิ่มแค่ renderFib() ใน dashboard)
   - data: MT5 price auto-swing H4/D → 0.382/0.5/0.618 + RSI computed-in-code
   - value: ระดับ pullback entry ที่โต๊ะใช้จริง

**Build note:** #1(บางส่วน)/#2/#3/#4 ที่เป็น display ล้วน ทำใน dashboard ได้ (zero AI cost).
ส่วนที่ต้อง OHLC intraday (recency/bounce/liquidity/volume) ต้องคำนวณฝั่ง bot = แตะ chart_watcher →
ต้องขออนุมัติ design ก่อน (iron rule).

---

## APPENDIX — ข้อมูลตลาดที่กลั่นได้ (สำหรับ macro_regime, จะหมดอายุเร็ว)
- **NFP 07-02 actual 57K** vs forecast 114K (prior 172K → revised 129K) = **miss แรง** → ทองพุ่ง +60 ทันที 4065→4120-4128, run ถึง ~4140 **stall ที่ prior-high 4140, ไม่ผ่าน 4200**, ไม่แตะ 3960
- UHAS post-NFP bias: **bullish** (jobs อ่อน → Fed no rush → หนุนทอง); ต้านถัดไป 4170/4188/4200; support flip เป็น ~4080
- **ยืนยัน regime "Warsh long hold" + NFP prior ที่เพิ่งเพิ่ม** (miss → gold+ ตรงสถิติ)
