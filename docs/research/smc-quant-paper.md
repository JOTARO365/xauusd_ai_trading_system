# SMC/ICT × Quant สำหรับระบบ XAUUSD — Research → Backtest → Dashboard

> เอกสารสรุป (paper) วันที่ 2026-08-01. รวม: (1) หลักฐาน SMC↔quant, (2) ออกแบบ+ปรับ algo และ backtest จริง,
> (3) ความรู้เพิ่มเสถียร/ประสิทธิภาพ dashboard, (4) feature ที่แนะนำ. ความรู้ถูกเก็บเป็น skill
> `smc-ict-quant-evidence` แล้ว. **ทุกข้อคง CORE INVARIANT: entry = คำนวณจาก data ไม่ predict; SMC = context/monitor ไม่ใช่ entry.**

---

## Abstract (อ่านบรรทัดเดียวจบ)

กลไกที่ SMC อ้าง (order flow ดันราคา, order กระจุก, overextension revert, breakout ไปต่อ) **จริง มี peer-review**.
แต่ชั้น ICT เฉพาะตัว (swing high/low = แม่เหล็ก liquidity, order block, การไล่ล่า stop รายย่อยเป็นกิจวัตร)
**ไม่มี journal รองรับ + บางส่วนถูกค้าน**. **Backtest ของเราเอง (XAUUSD H1, 70k bars, causal, หัก cost) ยืนยัน:
ไม่มี SMC candidate ตัวไหนให้ directional edge หลัง cost** — ตรงกับ stance repo เดิม. ค่าที่ใช้ได้จริงของ SMC =
**monitor/context + risk** (เช่น "อย่า fade sweep") ไม่ใช่ตัวสร้าง entry. ชิ้นเดียวที่ validated และใช้อยู่แล้ว =
**structural-SL ปลายไส้แท่ง** (= liquidity/OB โดยธรรมชาติ).

---

## 1. หลักฐาน SMC ↔ Quant

### 1.1 kernel ที่จริง (เก็บได้)
- **order flow ดันราคา** — OFI ทำนาย mid-price (Cont-Kukanov-Stoikov 2014), Kyle's λ (1985), square-root impact law.
  *แต่* impact จริงแม้ใน crypto → เป็น **กลไก** (book จำกัดดูด volume) ไม่ใช่ลายนิ้วมือ smart-money.
- **stop/TP กระจุก → S/R + cascade** — Osler (JF 2003, JIMF 2005, FRBNY 2000) จาก order book แบงก์ FX จริง:
  TP กระจุก *ที่* เลขกลม (reversal, revert <30min), SL กระจุก *เลยไปนิด* (breakout/cascade, persist ~2h).
  **นี่คือ kernel จริงหนึ่งเดียวของ SMC → ใช้ round number + prior-day/session extreme เป็น liquidity level ไม่ใช่ swing มั่ว.**
- **"สถาบันไล่ล่า stop รายย่อย"** — อ่อน/กลับด้าน. Predatory trading (Brunnermeier-Pedersen 2005) เล่นงานรายใหญ่ที่ถูกบังคับ
  ไม่ใช่ chart-stop รายย่อย. default สถาบัน = **ซ่อนตัว** (VWAP/TWAP/iceberg ~44% volume). VPIN toxicity ถูก rebut (2014).

### 1.2 SMC → ชื่อจริง quant
| SMC | quant จริง | verdict |
|---|---|---|
| BOS | **time-series momentum** (Moskowitz-Ooi-Pedersen 2012, รวมทอง) | แข็งสุด เทรดได้ — repo มี algo นี้แล้ว |
| liquidity sweep | short-term reversal + FX stop cascade | บทบาทมัก **กลับด้าน** จากที่ SMC สอน |
| order block | S/R + LOB depth | re-label ของ S/R (subjective สุด) |
| premium/discount | mean-revert สู่ VWAP/mid | re-label |
| FVG-fill | gap-fill/mean-revert | เอฟเฟกต์จริง แต่วัตถุไม่ตรง |
| "imbalance"=OFI | order-flow imbalance | **category error** |
| Fib OTE 0.618/0.786 | — | **numerology ไม่มี edge** — ทิ้ง |

### 1.3 backtestable ranking
FVG (สะอาดสุด, 3-candle) > premium/discount > BOS event > liquidity sweep > CHoCH > **order block (อ่อนสุด)**.

---

## 2. Algo — ออกแบบ, ปรับ, backtest

โค๊ด: `scripts/smc_backtest.py` (causal: signal@i / resolve@i+1, SL-first, cost=spread pips, MIN_N=100, MAX_HOLD=240).
data: `data/xau_h1.json` (70,000 bars, 2014→2026) + `xau_d1.json` (prior-day levels).

### 2.1 candidate + ผล (exp_R หลัง cost 30 pips)

| candidate | n | WR | exp_R | t | PSR0 | verdict |
|---|---|---|---|---|---|---|
| A0 momentum baseline (TREND) | 1575 | .331 | **−0.054** | −1.5 | .07 | ไม่มี edge (เดิม) |
| A1 momentum **+ FVG filter** | 1341 | .339 | −0.031 | −0.8 | .22 | ดูดีขึ้น — **แต่ไม่รอด OOS (ดู 2.2)** |
| B1 sweep-reversal (fade PDH/PDL) rr1.5 | 4439 | .411 | −0.042 | −2.3 | .01 | −EV |
| B2 sweep-rev rr1.0 | 4439 | .503 | −0.062 | −4.1 | 0 | −EV, high-WR trap |
| B3 sweep-rev target=opp-level | 4439 | **.617** | −0.120 | −13 | 0 | **กับดัก WR สูง/RR ต่ำ** |
| C1 FVG-fill fade rr1.0 | 8164 | .478 | −0.126 | −11 | 0 | แย่สุด |

### 2.2 OOS split (เปิดโปง overfit)
FVG filter (A1) split 70/30:
- in-sample (2014-22): A0 −0.124 → A1 −0.069 (filter *ดูเหมือน* ช่วย)
- **OOS (2022-26): A0 +0.047 → A1 +0.023 (filter ทำให้ *แย่ลง*)**

→ momentum sign-flip ตามช่วง (−0.124 เก่า → +0.047 ใหม่) = **window bias ครอง** ไม่ใช่ FVG. FVG filter = **overfit ปฏิเสธเป็น edge**.

sweep-**continuation** (ไปตาม break แทน fade): −0.083/−0.054 = ก็ −EV → **sweep ไม่ให้ edge ทั้ง 2 ทิศ**.

### 2.3 บทสรุป algo
1. **ไม่มี SMC-derived candidate ให้ directional edge หลัง cost** — ยืนยัน stance repo (minimal-AI: entry=data ไม่มี edge OOS).
2. **อย่า wire อะไรเป็น entry.** in-sample gain โดดเดี่ยว = สัญญาณ overfit (t ต้อง >3, ไม่มีตัวไหนถึง).
3. **fade sweep = แพ้** (สู้ cascade ตาม Osler) → ถ้าจะทำอะไรกับ sweep ให้เป็น **alert/risk** ("ระวังไม้เกาะ level"), ไม่ auto-fade.
4. ชิ้น SMC เดียวที่ validated + ใช้อยู่ = **structural-SL ปลายไส้ D1/H4** (= liquidity/OB) — คงไว้.
5. ทางที่มีเหตุผลถ้าจะลองต่อ = เก็บ FVG/sweep เป็น **shadow log** (algo_registry → shadow-only, ไม่แตะ live) เก็บ forward-OOS
   ก่อนคิด enable — แต่ priority ต่ำเพราะ in-sample ก็ไม่มี edge.

---

## 3. ความรู้เพิ่มเสถียร/ประสิทธิภาพ Dashboard

จาก audit (`dashboard/app.py` + `index.html`): waitress 4 threads + pair-collector daemon + `_cached` refresh threads.

### 3.1 HIGH (แก้ก่อน — impact สูงสุด)
1. **MT5 ไม่มี lock ใน dashboard** — bot serialize ทุก MT5 call ด้วย `_mt5_lock` แต่ dashboard เรียก `mt5.*` ตรงจาก 4 request thread + collector + refresh thread **ไม่มี lock** → return None/garbage/ค้าง + ชนกับ bot ข้าม process. **แก้: lock กลาง route ทุก `mt5.*` (หรือ reuse mt5_connector wrapper). = คุ้มสุด.**
2. **`/api/tsmom` MT5 สดทุก 5s ไม่ cache** (copy_rates D1 300 + positions_get) + `loadTsmom` ไม่ throttle. **แก้: `_cached ttl=15` + client throttle.**
3. **`/api/monitor` `orders_get` ไม่ cache ทุก 5s** (+ init/shutdown churn ถ้า collector ปิด). **แก้: `_cached ttl=10`, ห้าม init/shutdown บน request path.**
4. **5s `loadLivePrice` cascade ~16 endpoint ไม่มี `document.hidden` gate** — ทุกแท็บ (แม้ background) ยิงทุก 5s ตลอด. **แก้: early-return เมื่อ tab hidden/ไม่ active.**
5. **`_sync_from_mt5` scan deal 7 วัน + rewrite trades.json 486KB ทุก ~30s** — หนัก + ชน writer ของ bot. **แก้: ขยาย TTL 120-300s, ลด window, ย้ายเข้า collector loop.**

### 3.2 MED (สรุป)
- `/api/data` ส่ง trade history เต็มทุก 10s (ส่งแค่ N ล่าสุด/delta) · `/api/calendar` block ~10s ไม่ cache · weekly-outlook spawn thread ทุก poll + guard race (เสี่ยงยิง Opus ซ้ำ = เงินจริง; ใส่ Lock) · cache 2 dict โตไม่จำกัด (LRU/sweep) · `_cached` refresh race + กลืน error เงียบ (Lock + log) · `/api/config` เขียน .env ไม่ atomic (tmp+os.replace) · `/api/gap-monitor` MT5 ไม่ cache วันธรรมดา.

### 3.3 LOW / quick win
- ไม่มี `document.hidden` gate ที่ timer ไหนเลย (pause on `visibilitychange`) · `TEMPLATES_AUTO_RELOAD=True` prod (ปิด) · `/api/backtest` ไม่ cache · endpoint ซ้ำใน cascade + own setInterval (ยุบ) · account subscript ตรง (ใช้ .get).

### 3.4 Quick wins (คุ้มสุด/แรงน้อยสุด)
1. MT5 lock กลาง (#1) 2. `_cached` `/api/tsmom` + `/api/monitor` (#2,#3) 3. `document.hidden` gate cascade (#4,#13)
4. ขยาย sync TTL หยุด scan 7 วันทุก 30s (#5) 5. bound cache dict + Lock refresh/weekly-outlook (#8,#9,#10).

> หมายเหตุปลอดภัย: `mt5.shutdown()` ใน dashboard = process-local **ไม่ฆ่า** connection ของ bot (คนละ process). ความเสี่ยงจริง = contention + churn (#1) ไม่ใช่ shutdown.

---

## 4. Feature แนะนำ (จากความรู้นี้ — ทั้งหมด display/monitor/risk, 0 token, ไม่แตะ entry)

**ระดับ evidence-based + ปลอดภัย (แนะนำ):**
1. **FVG monitor column** (H1/H4 unfilled FVG ต่อคู่บน ecosystem/chart) — context เท่านั้น. detector causal (`_fvg_dir_at`, lag ก่อตัวครบ).
2. **Liquidity map overlay** — prior-day H/L + round-number ($5/$10) บนหน้า chart/monitor (= Osler kernel จริง). โชว์ระยะราคาถึง level.
3. **Sweep alert (ไม่ auto-trade)** — เตือนเมื่อราคาแตะเลย PDH/PDL แล้วปิดกลับเข้าใน + ป้ายเตือน **"sweep→มัก continuation อย่า fade"** (backtest ยืนยัน fade แพ้).
4. **BOS/regime badge** — ป้าย TREND/RANGE + breakout-of-structure (= momentum ที่มีอยู่) เพื่อ context.

**ระดับ shadow (ถ้าอยากเก็บ data ต่อ, priority ต่ำ):**
5. FVG/sweep เป็น **shadow algo** ใน `algo_registry` (auto shadow-only, ไม่มี switch LIVE) เก็บ forward-OOS. เตือน: backtest in-sample ก็ไม่มี edge → คาดหวังต่ำ.

**ไม่แนะนำ:** order-block auto-detect (subjective สุด, ไม่มี edge), Fib OTE (numerology), auto-fade sweep (แพ้ยับ), wire SMC เป็น entry/gate ใดๆ.

**stability เป็น feature:** ทำ HIGH 3.1 = dashboard เสถียรขึ้นชัด (ไม่ค้าง/ไม่ชน bot) = "ประสิทธิภาพ" ที่ได้จริงกว่าการเพิ่ม signal.

---

## 5. Recommendation

1. **อย่าเพิ่ม SMC เป็น entry** — หลักฐานนอก + backtest ในบ้านตรงกัน: ไม่มี edge หลัง cost. คง entry = algo/data.
2. **ทำ dashboard HIGH fixes ก่อน** (§3.1) — ได้เสถียรภาพจริง + แก้อาการ cycle ช้า/ชน MT5 ที่เจอมาแล้ว session ก่อน.
3. **เพิ่ม feature display** §4 ข้อ 1-4 (FVG/liquidity map/sweep-alert/regime badge) — 0 token, ปลอดภัย, ให้ context เทรดมือ/เฝ้าดู.
4. ถ้าจะวิจัยต่อ: purged/embargo CPCV + Deflated Sharpe + t>3 hurdle ก่อน enable อะไร (repo มี `scripts/multiple_testing_demo.py`).

**สิ่งที่ทำไปแล้ว session นี้:** skill `smc-ict-quant-evidence` (เก็บความรู้), `scripts/smc_backtest.py` (candidate + OOS), เอกสารนี้.
