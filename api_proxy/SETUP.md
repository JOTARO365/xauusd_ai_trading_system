# API Proxy — คู่มือ Setup

ทำครั้งเดียว ใช้ได้ตลอด

---

## ขั้นตอนที่ 1 — เตรียม Supabase (Owner ทำ)

เปิด [supabase.com](https://supabase.com) → เข้า project → **SQL Editor**

วาง SQL แล้วกด **Run** ทีละไฟล์:

**ไฟล์ที่ 1** — เพิ่ม `account_login` ใน cycles/agent_usage:
```sql
ALTER TABLE cycles      ADD COLUMN IF NOT EXISTS account_login BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_usage ADD COLUMN IF NOT EXISTS account_login BIGINT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_cycles_account      ON cycles(account_login);
CREATE INDEX IF NOT EXISTS idx_agent_usage_account ON agent_usage(account_login);
```

**ไฟล์ที่ 2** — สร้าง api_keys table:
```sql
CREATE TABLE IF NOT EXISTS api_keys (
    key           TEXT PRIMARY KEY,
    account_login BIGINT NOT NULL,
    label         TEXT,
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(active);
```

---

## ขั้นตอนที่ 2 — หา Supabase Service Key (Owner ทำ)

1. Supabase → **Settings** → **API**
2. หัวข้อ **Project API keys**
3. Copy **service_role** key (อย่าแชร์ key นี้กับใคร)

---

## ขั้นตอนที่ 3 — Deploy Proxy บน Render.com (Owner ทำ)

1. ไปที่ [render.com](https://render.com) → Sign up ฟรี (ไม่ต้องบัตร)

2. **New** → **Web Service**

3. เชื่อม GitHub repo หรือ deploy จาก public repo

4. ตั้งค่า:

   | Field | ค่า |
   |---|---|
   | **Root Directory** | `api_proxy` |
   | **Environment** | `Python 3` |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | **Instance Type** | `Free` |

5. เพิ่ม **Environment Variables** บน Render:

   | Key | Value |
   |---|---|
   | `SUPABASE_URL` | `https://xxx.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | service_role key จากขั้นตอนที่ 2 |

6. กด **Deploy** — รอ ~2 นาที

7. ได้ URL เช่น `https://xauusd-proxy.onrender.com`
   ทดสอบ: เปิด `https://xauusd-proxy.onrender.com/health` → ต้องเห็น `{"status":"ok",...}`

---

## ขั้นตอนที่ 4 — สร้าง API Key ให้ User (Owner ทำ)

รันบนเครื่อง owner (ต้องมี `.env` พร้อม `SUPABASE_URL` + `SUPABASE_KEY`):

```powershell
python scripts\manage_api_keys.py
```

เลือก **2) สร้าง key ใหม่** → ใส่ MT5 login ของ user → ใส่ชื่อ → ได้ key

```
✅ สร้างสำเร็จ!
   ส่งให้ user ใส่ใน .env :
   TRADING_API_KEY=abc123xyz...
```

ส่งให้ user 2 ค่า:
- `TRADING_API_URL` = URL จาก Render (ขั้นตอนที่ 3 ข้อ 7)
- `TRADING_API_KEY` = key ที่เพิ่งสร้าง

---

## ขั้นตอนที่ 5 — ตั้งค่า .env ฝั่ง User

user เปิด `.env` แล้วแก้ให้เป็น:

```env
# ── Claude API ───────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...

# ── MT5 ──────────────────────────────────────────────────────
MT5_LOGIN=xxxxxxx
MT5_PASSWORD=xxxxxxx
MT5_SERVER=XMGlobal-MT5 13

# ── Database (User mode — ผ่าน proxy) ────────────────────────
TRADING_API_URL=https://xauusd-proxy.onrender.com
TRADING_API_KEY=key_ที่ได้รับจาก_owner

# ── Trading Config ───────────────────────────────────────────
SYMBOL=GOLD#
START_BALANCE=3000
LOT_MODE=auto
...
```

> **หมายเหตุ**: user ไม่ต้องใส่ `SUPABASE_URL` หรือ `SUPABASE_KEY` เลย

---

## ตรวจสอบว่าทำงาน

**ฝั่ง user** — รัน bot แล้วดู log:
```
DB write_trade: ...   ← ถ้าเห็นบรรทัดนี้ = proxy ทำงาน
```

**ฝั่ง owner** — เปิด Supabase → Table Editor → trades → ต้องเห็น row ใหม่พร้อม `account_login` ของ user

---

## Revoke Key (กรณี user ออกจากระบบ)

```powershell
python scripts\manage_api_keys.py
```

เลือก **3) Revoke key** → พิมพ์ 8 ตัวแรกของ key → ปิดทันที user จะเขียน DB ไม่ได้ทันที

---

## สรุปใครเห็นอะไร

| | Supabase URL | Supabase Key | DB data |
|---|---|---|---|
| **Owner** | ✓ | ✓ (anon + service) | ทุก account |
| **User** | ✗ | ✗ | เฉพาะตัวเอง (ผ่าน proxy) |
| **Render proxy** | ✓ (env var) | ✓ service only | write only |
