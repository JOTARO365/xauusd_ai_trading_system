# Supabase Setup

## Project Info

| | |
|---|---|
| **Project URL** | `https://esfhjkmcuiwlzvxniifu.supabase.co` |
| **Region** | AWS Asia Pacific (Singapore) |
| **Dashboard** | https://supabase.com/dashboard/project/esfhjkmcuiwlzvxniifu |

---

## .env Config

```env
SUPABASE_URL=https://esfhjkmcuiwlzvxniifu.supabase.co
SUPABASE_KEY=<anon key จาก Settings → API → anon public>
```

> **หา key:** Supabase Dashboard → Settings → API → **anon public**
> ไม่ต้อง commit `.env` — อยู่ใน `.gitignore` แล้ว

---

## Schema (Tables)

รัน SQL นี้ใน **SQL Editor** ครั้งเดียวถ้า reset project:

```sql
-- Trades
CREATE TABLE IF NOT EXISTS trades (
    id                   BIGSERIAL PRIMARY KEY,
    ticket               BIGINT UNIQUE NOT NULL,
    symbol               TEXT NOT NULL DEFAULT 'XAUUSD',
    source               TEXT,
    direction            TEXT,
    entry_type           TEXT,
    status               TEXT NOT NULL DEFAULT 'OPEN',
    lot                  NUMERIC(10,4),
    entry_price          NUMERIC(12,5),
    sl                   NUMERIC(12,5),
    tp                   NUMERIC(12,5),
    pnl                  NUMERIC(10,2),
    opened_at            TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    technical_signal     TEXT,
    technical_confidence INT,
    trend                TEXT,
    sr_zone              TEXT,
    sr_strength          TEXT,
    pa_action            TEXT,
    sentiment            TEXT,
    analysis             TEXT,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- Agent usage
CREATE TABLE IF NOT EXISTS agent_usage (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL DEFAULT 'XAUUSD',
    agent_name          TEXT NOT NULL,
    model               TEXT NOT NULL,
    cycle_at            TIMESTAMPTZ NOT NULL,
    ticket              BIGINT,
    input_tokens        INT  DEFAULT 0,
    output_tokens       INT  DEFAULT 0,
    cache_read_tokens   INT  DEFAULT 0,
    cache_write_tokens  INT  DEFAULT 0,
    cost_usd            NUMERIC(10,6) NOT NULL,
    cache_hit_rate      NUMERIC(5,2),
    latency_ms          INT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Cycles
CREATE TABLE IF NOT EXISTS cycles (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL DEFAULT 'XAUUSD',
    cycle_at        TIMESTAMPTZ NOT NULL,
    ticket          BIGINT,
    total_cost_usd  NUMERIC(10,6) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trades_ticket     ON trades(ticket);
CREATE INDEX IF NOT EXISTS idx_trades_status     ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_opened_at  ON trades(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_usage_at    ON agent_usage(cycle_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_usage_agent ON agent_usage(agent_name);
CREATE INDEX IF NOT EXISTS idx_cycles_at         ON cycles(cycle_at DESC);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_trades_updated_at ON trades;
CREATE TRIGGER trg_trades_updated_at
    BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();

-- Disable RLS (server-side app ใช้ anon key + RLS ปิด)
ALTER TABLE trades      DISABLE ROW LEVEL SECURITY;
ALTER TABLE agent_usage DISABLE ROW LEVEL SECURITY;
ALTER TABLE cycles      DISABLE ROW LEVEL SECURITY;
```

---

## Security

| | |
|---|---|
| **Key ที่ใช้** | `anon` (publishable) — ปลอดภัยเพราะ RLS disabled |
| **RLS** | Disabled บน 3 tables (server-to-server ไม่ต้องการ) |
| **Network** | Supabase เปิด HTTPS เท่านั้น — ข้อมูล encrypt in transit |
| **`.env`** | อยู่ใน `.gitignore` — ไม่ถูก commit ขึ้น Git |

---

## Migrate ข้อมูลจาก JSON

```bash
python db/migrate.py
```

ใช้ได้เมื่อ SUPABASE_URL และ SUPABASE_KEY อยู่ใน `.env` แล้ว

---

## Code Layer

| File | หน้าที่ |
|---|---|
| `db/connection.py` | `get_client()` — สร้าง Supabase client |
| `db/writer.py` | `write_trade()`, `write_cycle()` — upsert/insert |
| `db/reader.py` | `get_trades()`, `get_accounting()` — query |
