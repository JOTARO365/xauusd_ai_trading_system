-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: เพิ่ม account_login ใน cycles และ agent_usage
-- รัน 1 ครั้งสำหรับ Supabase / PostgreSQL ที่มี schema เก่า
-- Supabase: SQL Editor → วางแล้ว Run
-- PostgreSQL: psql $DATABASE_URL < db/migration_add_account_login.sql
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE cycles     ADD COLUMN IF NOT EXISTS account_login BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS account_login BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_cycles_account      ON cycles(account_login);
CREATE INDEX IF NOT EXISTS idx_agent_usage_account ON agent_usage(account_login);
