-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: เปิด RLS + Supabase Auth (JWT) multi-tenant
--   เป้าหมาย: เลิกพึ่ง anon key แบบ god-mode — แต่ละ user เห็นเฉพาะ account ตัวเอง
--   Owner bot/proxy ใช้ service_role (bypass RLS) → เขียนได้เหมือนเดิม ไม่กระทบเทรดจริง
--
-- ⚠️ ลำดับสำคัญ: ตั้ง SUPABASE_SERVICE_KEY ใน .env บน VM "ก่อน" รัน migration นี้
--    (ไม่งั้นบอทที่ยังถือ anon key จะเขียน DB ไม่ได้ — fail-soft แต่ accounting หยุดบันทึก)
--
-- Supabase: SQL Editor → วางแล้ว Run  (idempotent — รันซ้ำได้ปลอดภัย)
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1. mapping: Supabase Auth user → MT5 account(s) ───────────────────────────
CREATE TABLE IF NOT EXISTS user_accounts (
    user_id       UUID   NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_login BIGINT NOT NULL,
    role          TEXT   NOT NULL DEFAULT 'viewer',   -- viewer | owner
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, account_login)
);
CREATE INDEX IF NOT EXISTS idx_user_accounts_login ON user_accounts(account_login);

ALTER TABLE user_accounts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ua_select_own ON user_accounts;
CREATE POLICY ua_select_own ON user_accounts
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

-- ── 2. helper: คืน account_login ทั้งหมดที่ user ปัจจุบันมีสิทธิ์ ──────────────
--   SECURITY DEFINER → อ่าน user_accounts ได้โดยไม่ติด RLS ของตัวมันเอง
CREATE OR REPLACE FUNCTION auth_account_logins()
RETURNS SETOF BIGINT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT account_login FROM user_accounts WHERE user_id = auth.uid()
$$;

-- ── 3. เปิด RLS บนตารางข้อมูล ─────────────────────────────────────────────────
ALTER TABLE trades      ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE cycles      ENABLE ROW LEVEL SECURITY;

-- ── 4. read policies: authenticated เห็นเฉพาะ account ที่ผูกไว้ ────────────────
DROP POLICY IF EXISTS trades_select_own ON trades;
CREATE POLICY trades_select_own ON trades
    FOR SELECT TO authenticated
    USING (account_login IN (SELECT auth_account_logins()));

DROP POLICY IF EXISTS agent_usage_select_own ON agent_usage;
CREATE POLICY agent_usage_select_own ON agent_usage
    FOR SELECT TO authenticated
    USING (account_login IN (SELECT auth_account_logins()));

DROP POLICY IF EXISTS cycles_select_own ON cycles;
CREATE POLICY cycles_select_own ON cycles
    FOR SELECT TO authenticated
    USING (account_login IN (SELECT auth_account_logins()));

-- ─────────────────────────────────────────────────────────────────────────────
-- หมายเหตุความปลอดภัย:
--   • ไม่มี policy ให้ role "anon" → anon key (ถ้าหลุด) อ่าน/เขียนอะไรไม่ได้เลย
--   • ไม่มี INSERT/UPDATE/DELETE policy ให้ user → ฝั่ง web อ่านอย่างเดียว
--     การเขียน trade มาจาก bot (service_role) หรือ proxy (service_role) เท่านั้น
--   • service_role bypass RLS เสมอ → owner bot + proxy เขียนได้ปกติ ไม่กระทบ
--
-- ผูก user เข้ากับ account (owner ทำครั้งเดียวต่อ user หลังเขา sign up):
--   INSERT INTO user_accounts (user_id, account_login, role)
--   VALUES ('<auth.users.id ของ user>', <mt5_login>, 'viewer');
-- ─────────────────────────────────────────────────────────────────────────────
