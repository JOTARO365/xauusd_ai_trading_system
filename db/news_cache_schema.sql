-- ─────────────────────────────────────────────────────────────────────────────
-- News Cache Schema — pgvector + Haiku summarization
-- Run: psql $DATABASE_URL < db/news_cache_schema.sql
-- หรือ paste ใน Supabase SQL editor (เปิด pgvector extension ก่อนใน Dashboard > Extensions)
-- ─────────────────────────────────────────────────────────────────────────────

-- เปิด pgvector (Supabase: Dashboard → Database → Extensions → vector)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── News summary cache — 1 row ต่อ gathering batch ───────────────────────────
CREATE TABLE IF NOT EXISTS news_cache (
    id           BIGSERIAL PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,   -- MD5 ของ content เพื่อตรวจ duplicate
    summary      TEXT NOT NULL,          -- Haiku-generated summary (5 bullets)
    expires_at   TIMESTAMPTZ NOT NULL,   -- TTL 1 ชั่วโมง
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── Individual news items + embeddings สำหรับ vector search ──────────────────
CREATE TABLE IF NOT EXISTS news_embeddings (
    id         BIGSERIAL PRIMARY KEY,
    cache_id   BIGINT REFERENCES news_cache(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,            -- 'twitter' | 'forexfactory' | 'investing'
    content    TEXT NOT NULL,
    embedding  VECTOR(3072),             -- OpenAI text-embedding-3-small
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_news_cache_expires ON news_cache(expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_cache_hash    ON news_cache(content_hash);
CREATE INDEX IF NOT EXISTS idx_news_emb_cache     ON news_embeddings(cache_id);

-- IVFFlat index (สร้างหลังมีข้อมูลแล้ว — uncomment เมื่อ table มี row > 1000)
-- CREATE INDEX idx_news_emb_vec ON news_embeddings
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- ── RPC function: vector similarity search ────────────────────────────────────
CREATE OR REPLACE FUNCTION search_news_relevant(
    query_embedding VECTOR(3072),
    match_count     INT DEFAULT 3
)
RETURNS TABLE (source TEXT, content TEXT, similarity FLOAT)
LANGUAGE sql STABLE AS $$
    SELECT  ne.source,
            ne.content,
            1 - (ne.embedding <=> query_embedding) AS similarity
    FROM    news_embeddings ne
    JOIN    news_cache nc ON nc.id = ne.cache_id
    WHERE   nc.expires_at > NOW()
      AND   ne.embedding IS NOT NULL
    ORDER   BY ne.embedding <=> query_embedding
    LIMIT   match_count;
$$;
