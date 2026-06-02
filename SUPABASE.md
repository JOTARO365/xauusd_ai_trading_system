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
# Owner bot/dashboard — service_role (bypass RLS). เก็บลับ! อย่า commit อย่าแจก
SUPABASE_SERVICE_KEY=<service_role key จาก Settings → API → service_role>
# anon key — ใช้เฉพาะชั้น web (Supabase Auth + JWT); บอทไม่ต้องใช้
# SUPABASE_ANON_KEY=<anon public key>
```

> **หา key:** Supabase Dashboard → Settings → API
> • **service_role** = owner bot (เห็นทุก account, bypass RLS) — ห้ามหลุด
> • **anon public** = ชั้น web เท่านั้น (ปลอดภัยเพราะ RLS เปิด — เห็นเฉพาะ account ของ user ที่ login)
> ไม่ต้อง commit `.env` — อยู่ใน `.gitignore` แล้ว
>
> ⚠️ `SUPABASE_KEY` แบบเดิม (anon) ยังใช้ได้ในฐานะ fallback แต่ถ้า RLS เปิดแล้ว
> anon เดี่ยวๆ จะ **เขียน/อ่านไม่ได้** — owner ต้องเปลี่ยนเป็น `SUPABASE_SERVICE_KEY`

---

## Schema (Tables)

รัน SQL นี้ใน **SQL Editor** ครั้งเดียวถ้า reset project:

```sql
-- Trades
CREATE TABLE IF NOT EXISTS trades (
    id                   BIGSERIAL PRIMARY KEY,
    ticket               BIGINT NOT NULL,
    account_login        BIGINT NOT NULL DEFAULT 0,
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
    updated_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticket, account_login)
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
CREATE INDEX IF NOT EXISTS idx_trades_ticket     ON trades(ticket, account_login);
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

-- RLS: เปิดแล้ว (multi-tenant) — ดู db/migration_enable_rls_auth.sql
--   owner bot ใช้ service_role → bypass RLS; web user ใช้ anon+JWT → เห็นเฉพาะ account ตัวเอง
```

---

## Security (RLS + Supabase Auth — multi-tenant)

| | |
|---|---|
| **Owner bot/proxy** | `service_role` key → **bypass RLS** เขียน/อ่านทุก account (เก็บลับ) |
| **Web user** | `anon` + **JWT** (Supabase Auth) → RLS บังคับให้เห็นเฉพาะ account ที่ผูกใน `user_accounts` |
| **anon key เปล่า (หลุด)** | ไม่มี policy → **อ่าน/เขียนอะไรไม่ได้เลย** (deny-all) |
| **RLS** | **Enabled** บน `trades` / `agent_usage` / `cycles` + `user_accounts` |
| **Network** | Supabase เปิด HTTPS เท่านั้น — ข้อมูล encrypt in transit |
| **`.env`** | อยู่ใน `.gitignore` — ไม่ถูก commit ขึ้น Git |

### Rollout (ลำดับสำคัญ — กันบอทเงินจริงพัง)

1. **VM ก่อน:** ตั้ง `SUPABASE_SERVICE_KEY=<service_role>` ใน `.env` แล้ว `pm2 restart main`
   → owner bot สลับมา bypass RLS (ยังเขียน DB ได้แม้ RLS เปิด)
2. **แล้วค่อย:** Supabase SQL Editor → รัน `db/migration_enable_rls_auth.sql`
3. ผูก user เข้ากับ account (ต่อ user หลังเขา sign up):
   ```sql
   INSERT INTO user_accounts (user_id, account_login, role)
   VALUES ('<auth.users.id>', <mt5_login>, 'viewer');
   ```

> สลับลำดับ (เปิด RLS ก่อนตั้ง service key) = บอทถือ anon → เขียน DB ไม่ได้
> แต่ระบบ fail-soft (JSON primary) → **การเทรดไม่หยุด** แค่ accounting/dashboard หยุดบันทึกชั่วคราว

---

## Migrate ข้อมูลจาก JSON

```bash
python db/migrate.py
```

ใช้ได้เมื่อ SUPABASE_URL และ SUPABASE_KEY อยู่ใน `.env` แล้ว

---

## Migration: เพิ่ม account_login (ถ้า DB มีข้อมูลอยู่แล้ว)

รัน SQL นี้ใน **SQL Editor** ครั้งเดียว:

```sql
-- เพิ่ม column (ถ้ายังไม่มี)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS account_login BIGINT NOT NULL DEFAULT 0;

-- ลบ unique constraint เดิม (ticket เดี่ยว)
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_ticket_key;

-- เพิ่ม unique constraint ใหม่ (ticket + account_login)
ALTER TABLE trades ADD CONSTRAINT IF NOT EXISTS trades_ticket_account_key
    UNIQUE (ticket, account_login);

-- อัปเดต index
DROP INDEX IF EXISTS idx_trades_ticket;
CREATE INDEX IF NOT EXISTS idx_trades_ticket ON trades(ticket, account_login);
```

---

## Code Layer

| File | หน้าที่ |
|---|---|
| `db/connection.py` | `get_client()` — สร้าง Supabase client |
| `db/writer.py` | `write_trade()`, `write_cycle()` — upsert/insert |
| `db/reader.py` | `get_trades()`, `get_accounting()` — query |
