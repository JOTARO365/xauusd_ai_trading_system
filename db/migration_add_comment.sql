-- migration: เพิ่ม comment ต่อ trade (algo attribution)
-- comment = order comment ที่ engine ตั้งตอนเข้าไม้ (ALGO-mom / ALGO-TSMOM / MSE-<algo> / AI)
-- → แยก edge ต่อ algo ได้จาก DB (เดิมไม่มี column นี้ → รวม system ทั้งก้อน)
-- รันครั้งเดียวใน Supabase SQL Editor ก่อน deploy code ที่เขียน comment (schema-before-code)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS comment TEXT;
