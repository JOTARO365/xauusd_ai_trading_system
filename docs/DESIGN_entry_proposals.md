# DESIGN — Entry Improvement Proposals (DRAFT)

> **สถานะ: DRAFT — ยังไม่อนุมัติ / ยังไม่มีการแก้ code ใด ๆ**
> วันที่: 2026-07-16 · ผู้ร่าง: Claude (ตามคำขอ user)
> ทั้ง 3 ร่างนี้แตะ **gate / money-management logic** → ต้องผ่าน EXPLAIN-BEFORE-ACTING +
> ผู้ใช้อนุมัติ + replay ก่อนเขียน code จริง (iron rule `.claude/roles/role.md`)

---

## ที่มา (context)

จากการไล่ log 15 ก.ค. เคส **ราคาไม่ผ่าน 4060 แต่บอทไม่เข้า SELL** (พลาด bounce):

| เวลา | ราคา | signal | ผล | เหตุ |
|------|------|--------|-----|------|
| 14:13–14:54 | 4054–4065 (ทดสอบ 4060) | **NO_TRADE** conf 38–42 | ไม่มีสัญญาณ | momentum h1/m15 = UP → ไม่ fade แนวต้านตอน momentum ขึ้น |
| 15:15 | 4046 | **SELL conf 62** | BLOCKED `htf_fade` | **NEWS_GATE**: ข่าว bull +91 ดัน floor 62→70 |
| 16:11 | 4040 | SELL conf 78 | BLOCKED `slot` | SELL เต็ม 2/2 (ถือ short อยู่แล้ว) |

**ข้อสังเกตเสริม:** `volume_profile` ตอนนั้น = `sell 66.8%` (แรงซื้อหด) และ momentum m15 พลิกลง —
**ยืนยัน SELL ทั้งคู่ แต่เป็น display-only ไม่เข้า decision** จึงช่วยดันไม้ให้ผ่าน gate ไม่ได้

3 ร่างด้านล่างแก้คนละจุดของเคสนี้ — เลือกทำได้ทีละอัน/ผสม

---

## ร่าง (ก) — NEWS_GATE Contradiction Dampener

### 1. ทำอะไร
`_news_gate_adjust` (`decision_maker.py:281`) เจอข่าวสวนไม้ → บวก floor **+8 เสมอ** โดยไม่ดูว่า
price/flow กำลังยืนยันไม้เราอยู่ ร่างนี้เพิ่ม dampener: **ถ้า price action สวนข่าว (= ยืนยันทิศไม้เรา)
ชัดเจน → ลด penalty ลงตามน้ำหนักหลักฐาน** ไม่บวกเต็มทื่อ ๆ

### 2. ทำงานยังไง
เมื่อ `oppose=True` (เคส: ข่าว bull, ไม้ SELL) นับ "เสียงยืนยันทิศไม้" จากสัญญาณที่มีใน `chart_data`
(call site บรรทัด 647 อยู่ใน `_run_gates`, chart_data in scope):

| เสียงยืนยัน | เงื่อนไข | source |
|---|---|---|
| momentum m15 | `mom_m15==dir` + `STRONG` | `momentum_tf.m15` |
| momentum h1 | `mom_h1==dir` | `momentum_tf.h1` |
| ราคาไหลตามทิศ | `fast_move_pips` ตรงทิศ + เกิน threshold | `fast_move_pips` |
| แรงขาย/ซื้อ (proxy) | `volume_profile.tilt==dir` (น้ำหนักต่ำ = tick-vol) | `volume_profile` |

```
if oppose:
    penalty = NEWS_OPPOSE_PENALTY (8)
    votes   = count(เสียงยืนยัน)
    if votes >= NEWS_CONTRA_STRONG (3):  penalty = 0            # ราคาสวนข่าวท่วมท้น
    elif votes >= NEWS_CONTRA_SOME (2):  penalty = penalty // 2 # สวนบางส่วน (8→4)
    adj = base_floor + penalty
```
**เคส 4060:** m15 DOWN + fast_move −1187 + tilt sell = 3 เสียง → penalty 0 → floor คง 62 → SELL 62 **ผ่าน**

### 3. ผลกระทบ
- Token: **0** (compute-in-code)
- Pipeline: แก้แค่ `_news_gate_adjust` — ต้องเพิ่ม param ส่ง signals เข้าไป (เดิมรับแค่ `direction, base_floor`)
- **ความเสี่ยง:** NEWS_GATE oppose = เกราะกัน fade ข่าวสด. ผ่อน = เชื่อราค่า > ข่าว — อันตรายถ้า whipsaw
  ช่วงข่าวออก → กันด้วย require STRONG + sustained + **แค่ผ่อน penalty ไม่ยกเลิก floor พื้นฐาน** (gate 6/
  counter-spike/HTF ยังครบ)

### 4. ทางเลือก
- (ก1) vote นี้ ← เลือก: โปร่งใส จูนง่าย
- (ก2) score ต่อเนื่อง (news − momentum) → penalty: ลื่นแต่ opaque/replay ยาก
- (ก3) ผ่อนตามอายุข่าว: แก้คนละปัญหา

### 5. Tunables (default อนุรักษ์นิยม)
```
NEWS_CONTRA_ENABLED   = false
NEWS_CONTRA_STRONG    = 3
NEWS_CONTRA_SOME      = 2
NEWS_CONTRA_FAST_PIPS = 300
```

---

## ร่าง (ข) — Scalp-Fade Path (⚠️ เสี่ยงสูงสุด — ไม่แนะนำเริ่มก่อน)

### 1. ทำอะไร
ปัจจุบันบอท **ไม่ fade แนวต้านตอน momentum ยัง UP** (ออก NO_TRADE — เคส 14:xx ที่ 4060).
ร่างนี้เพิ่ม path ที่ยอม SELL fade แนวต้าน **grade A เฉพาะเมื่อ m15 momentum เริ่มพลิกลง**
(reversal confirmation) = mean-reversion scalp

### 2. ทำงานยังไง
เมื่อราคาอยู่ที่โซน grade A (score≥TH) + **m15 พลิก UP→DOWN** หรือ reversal candle confirm →
อนุญาต SELL แม้ H4 trend/momentum ยังไม่ align. เป็น **exception ใน gate ที่เดิม block** (gate 2e/4/5)

### 3. ผลกระทบ
- Token: 0
- **⚠️ ความเสี่ยงสูงสุดในสามร่าง** — มันคือ "fade" ที่ anti-fade guard (`_run_gates`) **ตั้งใจกันไว้ตรง ๆ**
  (replay เดิมพิสูจน์ว่า fade counter-momentum เจ๊ง). ถ้า m15 flip เป็น false = เข้าสวน momentum เต็ม ๆ
- แตะ gate หลัก (anti-fade/counter-trend) โดยตรง → กระทบหลาย path

### 4. ทางเลือก (ลดความเสี่ยง)
- (ข1) ทำเป็น **pending limit** ที่ขอบโซน แทน market → ปลอดภัยกว่า, ราคาต้องวิ่งมาหาเอง
- (ข2) **แค่ปรับ conf floor ลง** เมื่อ reversal confirm (แทนสร้าง path ใหม่) → กระทบน้อยกว่ามาก
- (ข3) ไม่ทำเลย → ให้ ZRE (ด้านล่าง) คุมเคสนี้แทน (แนะนำ)

> **คำแนะนำ:** ร่างนี้ทับซ้อนกับ ZRE แต่เสี่ยงกว่ามาก — **ควรข้าม (ข) ไปทำ ZRE** ซึ่งได้ผลคล้ายกัน
> (จับ bounce ที่โซนแข็ง) แต่ผ่าน limit + RR≥2 + trend-align ไม่ทะลุเกราะ anti-fade

---

## ร่าง ZRE — Zone Re-Entry RR≥2 (แนะนำเริ่มก่อน)

### 1. ทำอะไร
`manage_sl_reentry` (`pending_manager.py:858`) บังคับ RR≥2 อยู่แล้ว แต่เป็น **reactive post-SL + โซนถัดไป**
เท่านั้น ZRE เติมส่วนที่ขาด: **วาง LIMIT ดักเด้งที่โซนเกรดสูงเชิงรุก** (ไม่ต้องรอโดน SL) โดย:
- คง **RR≥2.0** (ไม่ tighten TP → ไม่ชน min_rr gate)
- **ไม่ average down** (1 ZRE/โซน ไม่ stack)
- "TP สั้นลง" แบบถูกวิธี = **หด SL ให้ชิดขอบโซน** (v1) ไม่ใช่หด TP → TP ใกล้ขึ้นที่ RR≥2 = ถือสั้นลงจริง

### 2. ทำงานยังไง (reuse plumbing เดิมทั้งหมด)
เพิ่มฟังก์ชันใน `pending_manager.py` เรียกจาก `trading_graph.py` node pending:
```
manage_zone_reentry(chart_data):
  ถ้า flag OFF → 0                                  # ZONE_REENTRY_ENABLED
  ถ้า daily_trade_cap → 0                            # reuse (กัน storm)
  best = sr_meta grade∈{A,B} + score≥TH + proximity + bars_since_touch≤N (สด)
  direction = R→SELL, S→BUY (bounce เข้า range)
  guards (reuse): trend-align + _d1_counter (ห้าม counter-D1),
                  counter_spike (ราคาทะลุโซนแรง=break → skip),
                  _has_zre_pending(zone) (1/โซน), _is_covered, slot cap
  SL = ขอบโซนไกล + buffer   (◄ ใหม่ v1: zone-anchored ≤ default_sl_pips)
  TP = _calc_tp_pips(zone, โซนตรงข้าม)               # reuse
  ถ้า RR < 2.0 → skip                                # reuse — hard gate
  place_pending_order(LIMIT, comment="ZRE-...")     # reuse
```
**REUSE:** `place_pending_order`,`_calc_tp_pips`,`_is_covered`,`_merge_levels`,`daily_trade_cap`,
`_d1_counter`, RR check, `sr_meta`
**NEW:** trigger จาก zone-hold (ไม่ใช่ post-SL), zone-anchored SL, dedup tag `ZRE-`

### 3. ผลกระทบ
| ด้าน | ผล |
|------|-----|
| Token | 0 — compute-in-code (ทำนอง SL-RE) |
| Pipeline | +1 ฟังก์ชันใน pending path (bypass `_run_gates` อยู่แล้ว) → **duplicate guard ครบเอง** |
| เสี่ยง #1 | เข้าถี่ขึ้น → cost/spread → กันด้วย score≥TH สูง + 1/โซน + slot + daily_cap |
| ⚠️ เสี่ยง #2 | **zone-anchored SL (v1) = แตะ money-management (iron-rule)** → **ต้องอนุมัติ** |

### 4. ทางเลือก
- **(v2) คง SL 2000p ตายตัว** ← **แนะนำเริ่ม**: ไม่แตะ iron-rule, พิสูจน์ "จับ bounce บ่อยขึ้น" ก่อน
  (แต่ TP ยังไกล RR≥2 = ≥4000p, ไม่ได้ "สั้นลง")
- (v1) zone-anchored SL: ได้ "ถือสั้น" จริง แต่แตะ SL → อนุมัติ + replay ก่อน
- (v3) ขยาย SL-RE เดิม: โค้ดน้อยสุด แต่ปน reactive/proactive สับสน

### 5. Tunables (default อนุรักษ์นิยม)
```
ZONE_REENTRY_ENABLED = false
ZRE_MIN_SCORE        = 78        # เฉพาะโซน A/สูง (_score_zone)
ZRE_MAX_BARS_SINCE   = 3         # โซนเพิ่งแตะ = สด
ZRE_PROXIMITY_PCT    = 0.4
ZRE_PER_ZONE         = 1         # กัน martingale
ZRE_SL_MODE          = "fixed"   # v2 ; "zone" = v1 (ต้องอนุมัติ)
ZRE_SL_BUFFER_PCT    = 0.15      # (v1) SL เลยขอบโซน
```

### 6. เทียบกับ idea เดิมของ user
| idea เดิม | ZRE |
|-----------|-----|
| เติมไม้ตอนถือขาดทุน | ❌ ตัด (martingale) → 1/โซน + daily_cap |
| TP สั้นลง | ✅ ถูกวิธี = หด **SL** (v1) ไม่ใช่หด TP → RR≥2 คง |
| recompute แนวใหม่/เดิม | ✅ ทุก cycle จาก sr_meta สด |
| โดน SL แล้วเข้าใหม่ | ✅ SL-RE เดิมยังทำงานคู่กัน |

---

## เปรียบเทียบ 3 ร่าง

| | (ก) NEWS dampener | (ข) Scalp-fade | ZRE |
|---|---|---|---|
| แก้เคส 4060 จุดไหน | SELL 62 โดน NEWS_GATE | NO_TRADE ตอน 14:xx | จับ bounce ที่โซนเชิงรุก |
| แตะ money-mgmt | ไม่ | ไม่ | **ใช่ (v1 SL) / ไม่ (v2)** |
| แตะ anti-fade guard | ไม่ | **ใช่ (โดยตรง)** | ไม่ (ผ่าน limit+trend-align) |
| Token | 0 | 0 | 0 |
| ความเสี่ยง | กลาง | **สูงสุด** | ต่ำ (v2) / กลาง (v1) |
| คำแนะนำ | ทำได้ (คู่ ZRE) | **ข้าม** | **เริ่มก่อน (v2)** |

**ลำดับที่แนะนำ:** ZRE v2 → (ก) → (ประเมิน ZRE v1) → ข้าม (ข)

---

## Rollout Gate ร่วม (บังคับทุกร่าง ก่อนเปิดใช้จริง)

1. เขียน code แบบ **flag OFF** (ไม่กระทบ path เดิมเลย)
2. **`replay-validator`** เทียบ history 400+ ไม้: WR/PnL ดีขึ้นมั้ย + นับ false-signal
   (false-bounce / whipsaw / fade-that-lost)
3. **`gate-integration-auditor`**: ยืนยันไม่ขัด HTF_DIRECTION_BLOCK / anti-fade / counter-spike / SIDEWAYS
   + enumerate order paths ที่ bypass DecisionMaker
4. ผ่านทั้งหมด → เปิด **SHADOW** เก็บ data ก่อน → review → ค่อย **ENABLED**
5. ทุกขั้น: log `continue.md` + update memory

> ⚠️ ห้ามข้ามขั้น 2–3 เด็ดขาด — ทั้ง 3 ร่างแตะสิ่งที่ replay เดิมพิสูจน์แล้วว่าอันตราย
> (fade counter-momentum / counter-D1 / averaging). LIVE-money — ผิดพลาด = เสียเงินจริง
