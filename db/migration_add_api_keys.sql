-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: สร้าง api_keys table สำหรับ multi-user proxy auth
-- Supabase: SQL Editor → วางแล้ว Run
-- PostgreSQL: psql $DATABASE_URL < db/migration_add_api_keys.sql
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS api_keys (
    key           TEXT PRIMARY KEY,
    account_login BIGINT NOT NULL,
    label         TEXT,                              -- ชื่อ user เพื่อจดจำ
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(active);
