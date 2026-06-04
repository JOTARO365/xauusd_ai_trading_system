-- ─────────────────────────────────────────────────────────────────────────────
-- XAUUSD AI Trading System — Database Schema
-- Compatible with PostgreSQL 14+ and Supabase
-- Run once: psql $DATABASE_URL < db/schema.sql
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Trades ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id                   BIGSERIAL PRIMARY KEY,
    ticket               BIGINT UNIQUE NOT NULL,
    symbol               TEXT NOT NULL DEFAULT 'XAUUSD',
    source               TEXT,                        -- SYSTEM | MANUAL | RECOVERED
    direction            TEXT,                        -- BUY | SELL
    entry_type           TEXT,                        -- BREAKOUT | REVERSAL | MANUAL …
    status               TEXT NOT NULL DEFAULT 'OPEN', -- OPEN | CLOSED
    lot                  NUMERIC(10,4),
    entry_price          NUMERIC(12,5),
    sl                   NUMERIC(12,5),
    tp                   NUMERIC(12,5),
    pnl                  NUMERIC(10,2),
    opened_at            TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    -- AI context
    technical_signal     TEXT,
    technical_confidence INT,
    trend                TEXT,
    sr_zone              TEXT,
    sr_strength          TEXT,
    pa_action            TEXT,
    sentiment            TEXT,
    analysis             TEXT,
    -- decision snapshot (leakage-free features frozen at entry → learned filter v2)
    planned_sl_pips      NUMERIC,
    entry_score          NUMERIC,
    atr_h4               NUMERIC,
    momentum             TEXT,
    htf_zone_tf          TEXT,
    -- strategy versioning (1=legacy, 2=current v2 strategy)
    strategy_version     SMALLINT DEFAULT 1,
    -- meta
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ── Agent usage — one row per API call ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_usage (
    id                  BIGSERIAL PRIMARY KEY,
    account_login       BIGINT NOT NULL DEFAULT 0,    -- MT5 account number (0 = unknown)
    symbol              TEXT NOT NULL DEFAULT 'XAUUSD',
    agent_name          TEXT NOT NULL,
    model               TEXT NOT NULL,
    cycle_at            TIMESTAMPTZ NOT NULL,
    ticket              BIGINT,                       -- NULL ถ้า cycle นั้นไม่เปิด trade
    input_tokens        INT  DEFAULT 0,
    output_tokens       INT  DEFAULT 0,
    cache_read_tokens   INT  DEFAULT 0,
    cache_write_tokens  INT  DEFAULT 0,
    cost_usd            NUMERIC(10,6) NOT NULL,
    cache_hit_rate      NUMERIC(5,2),
    latency_ms          INT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Cycles — one row per trading cycle ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS cycles (
    id              BIGSERIAL PRIMARY KEY,
    account_login   BIGINT NOT NULL DEFAULT 0,        -- MT5 account number (0 = unknown)
    symbol          TEXT NOT NULL DEFAULT 'XAUUSD',
    cycle_at        TIMESTAMPTZ NOT NULL,
    ticket          BIGINT,
    total_cost_usd  NUMERIC(10,6) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_trades_ticket     ON trades(ticket);
CREATE INDEX IF NOT EXISTS idx_trades_status     ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_opened_at  ON trades(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_usage_at      ON agent_usage(cycle_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_usage_agent   ON agent_usage(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_usage_account ON agent_usage(account_login);
CREATE INDEX IF NOT EXISTS idx_cycles_at           ON cycles(cycle_at DESC);
CREATE INDEX IF NOT EXISTS idx_cycles_account      ON cycles(account_login);

-- ── Auto-update updated_at on trades ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_trades_updated_at ON trades;
CREATE TRIGGER trg_trades_updated_at
    BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();
