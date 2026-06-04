-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: decision snapshot — leakage-free features ตอนเข้าไม้ (สำหรับ learned filter v2)
--   ปัญหาเดิม: `sl` ถูก breakeven/trailing ขยับ → ใช้เป็น ML feature ไม่ได้ (รั่ว outcome)
--   แก้: เก็บค่าที่ "วางแผน/วัดตอนเข้าไม้" แยกไว้ ไม่ถูกแก้ภายหลัง → ใช้เทรนได้สะอาด
-- Supabase: SQL Editor → วางแล้ว Run  (idempotent)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE trades ADD COLUMN IF NOT EXISTS planned_sl_pips NUMERIC;  -- SL ที่วางแผนตอนเข้า (ก่อน BE ขยับ)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_score     NUMERIC;  -- confluence score จาก chart scan
ALTER TABLE trades ADD COLUMN IF NOT EXISTS atr_h4          NUMERIC;  -- ATR H4 (volatility regime)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS momentum        TEXT;     -- momentum ตอนเข้า (UP_STRONG/...)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS htf_zone_tf     TEXT;     -- HTF zone timeframe (D1/W1/NULL)

-- หมายเหตุ: ค่าเหล่านี้เริ่มเก็บจาก trade ใหม่หลัง deploy reporter._decision_snapshot
-- (trade เก่าจะเป็น NULL — retrain เมื่อสะสมข้อมูลใหม่ ~2-4 สัปดาห์)
