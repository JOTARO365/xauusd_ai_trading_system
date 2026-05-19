-- Migration: trade_lessons table (v2 — hybrid search + frequency + recency)
-- รองรับทั้ง: ยังไม่มีตาราง (CREATE) และมีตารางเก่าแล้ว (ALTER)
-- Run in Supabase SQL Editor

-- ── 1. Enable pgvector ────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── 2. Create table (ถ้ายังไม่มี) ────────────────────────────
CREATE TABLE IF NOT EXISTS trade_lessons (
    id             BIGSERIAL    PRIMARY KEY,
    account_login  BIGINT       NOT NULL DEFAULT 0,
    mistake_type   TEXT         NOT NULL,
    pattern        TEXT         NOT NULL,
    context        JSONB        NOT NULL DEFAULT '{}',
    embedding      VECTOR(768),
    expires_at     TIMESTAMPTZ  NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── 3. ADD COLUMNS (ถ้ามีตารางเก่าอยู่แล้ว — idempotent) ─────
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS direction     TEXT  NOT NULL DEFAULT '';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS trend         TEXT  NOT NULL DEFAULT '';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS market_regime TEXT  NOT NULL DEFAULT '';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS frequency     INT   NOT NULL DEFAULT 1;
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS avg_pnl       FLOAT NOT NULL DEFAULT 0;

-- ── 4. Fix embedding column dimension ────────────────────────
-- ถ้า embedding เดิมเป็น VECTOR(3072) ต้อง drop แล้วสร้างใหม่เป็น VECTOR(768)
-- (ถ้าไม่มีข้อมูลใน table ยังก็รัน block นี้ได้เลย)
DO $$
BEGIN
    -- ตรวจว่า embedding column เป็น vector(3072) หรือเปล่า
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trade_lessons'
          AND column_name = 'embedding'
          AND udt_name = 'vector'
    ) THEN
        -- drop index ก่อน (ถ้ามี)
        DROP INDEX IF EXISTS idx_trade_lessons_embedding;
        -- เปลี่ยน type (ต้องการ cast ผ่าน NULL เพราะ dimension ต่างกัน)
        ALTER TABLE trade_lessons DROP COLUMN IF EXISTS embedding;
        ALTER TABLE trade_lessons ADD COLUMN embedding VECTOR(768);
    END IF;
END $$;

-- ── 5. Indexes ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_trade_lessons_embedding
    ON trade_lessons USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_trade_lessons_filter
    ON trade_lessons (account_login, direction, trend, expires_at);

-- ── 6. RLS ────────────────────────────────────────────────────
ALTER TABLE trade_lessons DISABLE ROW LEVEL SECURITY;

-- ── 7. RPC: Hybrid search ─────────────────────────────────────
CREATE OR REPLACE FUNCTION search_trade_lessons(
    query_embedding  VECTOR(768),
    match_count      INT     DEFAULT 3,
    p_account        BIGINT  DEFAULT 0,
    p_direction      TEXT    DEFAULT '',
    p_trend          TEXT    DEFAULT ''
)
RETURNS TABLE (
    id            BIGINT,
    mistake_type  TEXT,
    pattern       TEXT,
    direction     TEXT,
    trend         TEXT,
    frequency     INT,
    avg_pnl       FLOAT,
    context       JSONB,
    score         FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        tl.id,
        tl.mistake_type,
        tl.pattern,
        tl.direction,
        tl.trend,
        tl.frequency,
        tl.avg_pnl,
        tl.context,
        (1.0 - (tl.embedding <=> query_embedding))
        * (1.0 + LN(tl.frequency::FLOAT + 1) * 0.3)
        * (1.0 + GREATEST(0.0, 1.0 - EXTRACT(EPOCH FROM (NOW() - tl.created_at)) / (86400.0 * 90)) * 0.5)
        AS score
    FROM trade_lessons tl
    WHERE
        tl.account_login = p_account
        AND tl.expires_at > NOW()
        AND tl.embedding IS NOT NULL
        AND (p_direction = '' OR tl.direction = p_direction OR tl.direction = '')
        AND (p_trend     = '' OR tl.trend     = p_trend     OR tl.trend     = '')
    ORDER BY score DESC
    LIMIT match_count;
END;
$$;
