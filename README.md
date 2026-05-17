# XAUUSD AI Trading System

ระบบ AI Trading อัตโนมัติสำหรับ XAUUSD (ทองคำ) โดยใช้ Claude AI + MetaTrader 5

---

## สถาปัตยกรรม

```
┌──────────────────────────────────────────────────────────────────┐
│                        AI Agent Pipeline                          │
│                                                                  │
│  ChartWatcher ──→ MarketAdvisor ──→ Analyst ──→ DecisionMaker   │
│       │                                              │            │
│  (H4/H1/M15                                   12 Python gates    │
│  multi-TF analysis,                           → Claude (8-line   │
│  4-component trend,                             clean summary)   │
│  entry scoring)                                      │            │
│                                              MT5 open_order()    │
└──────────────────────────────────────────────────────────────────┘
         ↕ PostgreSQL / Supabase
┌──────────────────────┐
│  Dashboard (port 5050)│  ← รันใน Docker ได้
│  Flask + Waitress    │
└──────────────────────┘
```

---

## ความต้องการของระบบ

| Component | ความต้องการ |
|---|---|
| **Trading Bot** (main.py) | Windows + MetaTrader5 Terminal เปิดค้างไว้ |
| **Dashboard** | Windows / Linux / Docker |
| Python | 3.11+ |
| Node.js | 18+ (สำหรับ PM2) |
| Database | PostgreSQL 14+ หรือ Supabase |

> ⚠️ `MetaTrader5` Python library รองรับ **Windows เท่านั้น**

---

## ติดตั้ง

### 1. Clone โปรเจกต์

```bash
git clone git@github.com:JOTARO365/xauusd_ai_trading_system.git
cd xauusd_ai_trading_system
```

### 2. ติดตั้ง Python dependencies

```bash
pip install -r requirements.txt
```

### 3. ตั้งค่า .env

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

เปิด `.env` แล้วกรอกค่าที่จำเป็น (ดู [Environment Variables](#environment-variables) ด้านล่าง)

### 4. ตั้งค่า Database

เลือก **1 วิธี** จาก 2 วิธีด้านล่าง:

#### วิธี A — PostgreSQL Local (รัน Docker)

```bash
# รัน PostgreSQL ผ่าน docker compose (port 5432)
docker compose up -d postgres

# ใน .env ใช้ค่านี้ (default แล้ว)
DATABASE_URL=postgresql://trading:trading@localhost:5432/trading
```

สร้าง schema:

```bash
psql $DATABASE_URL < db/schema.sql
```

#### วิธี B — Supabase (Cloud)

1. สร้าง project ที่ [supabase.com](https://supabase.com)
2. ไปที่ **SQL Editor** → วาง SQL จาก `SUPABASE.md` แล้วรัน
3. ใน `.env` เปลี่ยน DATABASE_URL:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASS@db.xxxx.supabase.co:5432/postgres
```

> ดูรายละเอียดเพิ่มเติมใน [SUPABASE.md](SUPABASE.md)

---

## รันระบบ

### วิธีที่ 1 — PM2 (แนะนำ)

```bash
# ติดตั้ง PM2
npm install -g pm2

# รัน trading bot + dashboard พร้อมกัน
pm2 start ecosystem.config.js
pm2 save

# ดู status
pm2 list
pm2 logs main
pm2 logs dashboard
```

คำสั่ง PM2 ที่ใช้บ่อย:

```bash
pm2 restart main        # restart trading bot
pm2 restart dashboard   # restart dashboard
pm2 restart all         # restart ทั้งหมด
pm2 stop all            # หยุดทั้งหมด
```

### วิธีที่ 2 — รันตรง

```bash
# Terminal 1: Trading bot
python main.py

# Terminal 2: Dashboard
python dashboard/app.py
```

---

## Dashboard

เปิดเบราว์เซอร์ไปที่ `http://localhost:5050`

| หน้า | รายละเอียด |
|---|---|
| **Overview** | Portfolio, สถิติ, ประวัติ trade, ปฏิทินข่าว |
| **Settings** | ปรับ config ได้ทันที — บันทึกแล้ว PM2 restart อัตโนมัติ |

---

## Docker

มี 2 โหมด ขึ้นอยู่กับความต้องการ:

### โหมด A — Linux containers (Dashboard เท่านั้น)

ใช้ Docker Desktop ปกติ (Linux mode) — **ไม่ต้องสลับ mode**

```bash
# สร้าง .env ก่อน
cp .env.example .env   # Linux/Mac
copy .env.example .env  # Windows

# รัน dashboard + postgres
docker compose up -d

# ดู logs
docker compose logs -f

# หยุด
docker compose down
```

- Dashboard เปิดที่ `http://localhost:5050`
- Trading bot (`main.py`) ต้องรันแยกบน Windows host ด้วย PM2 หรือ `python main.py`

### โหมด B — Windows containers (ระบบเต็ม — Bot + Dashboard)

Docker ติดตั้งทุกอย่างในตัว: **Python, Node.js, PM2** และ Python packages ทั้งหมด

**ข้อกำหนด:**
1. Docker Desktop บน Windows
2. สลับเป็น Windows containers mode:
   - right-click ไอคอน Docker ใน system tray
   - เลือก **"Switch to Windows containers..."**
3. MetaTrader5 terminal เปิดและ Login ไว้บน host

```bash
# สร้าง .env ก่อน
copy .env.example .env

# Build และรัน (ครั้งแรก build นาน ~15-30 นาที เพราะ image ใหญ่)
docker compose -f docker-compose.windows.yml up -d

# ดู logs แบบ real-time
docker compose -f docker-compose.windows.yml logs -f

# ดูสถานะ PM2 ภายใน container
docker exec xauusd-trading powershell -Command "pm2 list"

# Restart process ใด process หนึ่ง
docker exec xauusd-trading powershell -Command "pm2 restart main"
docker exec xauusd-trading powershell -Command "pm2 restart dashboard"

# หยุดทั้งหมด
docker compose -f docker-compose.windows.yml down
```

### เปรียบเทียบ 2 โหมด

| | โหมด A (Linux) | โหมด B (Windows) |
|---|---|---|
| **คำสั่ง** | `docker compose up -d` | `docker compose -f docker-compose.windows.yml up -d` |
| **Trading Bot** | ต้องรันแยกบน host | รันในตัว |
| **Image size** | ~500 MB | ~5-7 GB |
| **Build time** | ~2-5 นาที | ~15-30 นาที |
| **MetaTrader5** | ไม่รองรับ | รองรับ (Windows IPC) |
| **Docker mode** | Linux (default) | Windows containers |

---

## Environment Variables

### Required

| Key | รายละเอียด |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — [console.anthropic.com](https://console.anthropic.com) |
| `MT5_LOGIN` | MT5 account number |
| `MT5_PASSWORD` | MT5 password |
| `MT5_SERVER` | Broker server name (เช่น `ICMarketsAu-Demo`) |
| `DATABASE_URL` | PostgreSQL connection string |

### X/Twitter (ใช้สำหรับ sentiment — optional)

| Key | รายละเอียด |
|---|---|
| `X_USERNAME` | X (Twitter) username |
| `X_PASSWORD` | X password |
| `X_EMAIL` | X email (สำหรับ 2FA) |

### Trading Config

| Key | Default | รายละเอียด |
|---|---|---|
| `SYMBOL` | `XAUUSD` | Trading symbol (XM Global ใช้ `GOLD#`) |
| `START_BALANCE` | `3000` | ทุนเริ่มต้น (สกุลเงินของ account — บาท/USD ขึ้นกับ broker) |
| `LOT_MODE` | `auto` | `auto` = คำนวณตาม risk / `fixed` = ใช้ FIXED_LOT |
| `FIXED_LOT` | `0.01` | ใช้เมื่อ LOT_MODE=fixed |
| `MIN_LOT` | `0.01` | Lot size ต่ำสุด |
| `MAX_LOT` | `0.01` | Lot size สูงสุด |
| `RISK_PER_TRADE` | `0.50` | % risk ต่อ trade (0.50 = 0.5%) |
| `MAX_DAILY_LOSS` | `1.00` | % loss สูงสุดต่อวัน |
| `MAX_OPEN_TRADES` | `4` | จำนวน trade สูงสุดที่เปิดพร้อมกัน |
| `DEFAULT_SL_PIPS` | `255` | SL default (pips) — ใช้เมื่อคำนวณ SL ไม่ได้ (≈ 30% ของทุน 3000) |
| `DEFAULT_TP_PIPS` | `765` | TP default (pips) — 3.0× SL (R:R 3:1) |
| `MIN_RR_RATIO` | `2.0` | R:R ขั้นต่ำ (breakeven WR = 33%) |
| `HEDGE_BUFFER_PIPS` | `1000` | ช่องไฟก่อนเปิด hedge order (pips) |

### Position Sizing (Confidence-based)

| Key | Default | รายละเอียด |
|---|---|---|
| `CONF_FULL_SIZE_AT` | `80` | Confidence % ที่ได้ full position size |
| `CONF_MIN_SCALE` | `0.5` | Scale ต่ำสุด (conf ต่ำ = ครึ่ง size) |

ตัวอย่าง: conf=50% → 0.63× size, conf=65% → 0.81× size, conf≥80% → 1.0× size

### Pending Orders

| Key | Default | รายละเอียด |
|---|---|---|
| `MAX_PENDING_BUY` | `4` | Pending buy orders สูงสุด |
| `MAX_PENDING_SELL` | `4` | Pending sell orders สูงสุด |
| `PENDING_EXPIRY_HOURS` | `48` | หมดอายุ pending order (ชั่วโมง) |

### Streak & Portfolio Protection

| Key | Default | รายละเอียด |
|---|---|---|
| `PORTFOLIO_PROTECTION` | `true` | เปิด/ปิดระบบป้องกัน (daily loss limit, max trades) |
| `STREAK_PROTECTION` | `true` | เปิด/ปิดระบบป้องกัน losing streak |
| `MAX_LOSING_STREAK` | `5` | จำนวน loss ติดกันก่อน raise threshold |
| `STREAK_MIN_CONFIDENCE` | `62` | Confidence ขั้นต่ำเมื่อ streak triggered |

### Dynamic Features

| Key | Default | รายละเอียด |
|---|---|---|
| `DYNAMIC_TP` | `true` | ขยับ TP อัตโนมัติเมื่อ momentum แรงและราคาใกล้ TP |
| `NO_TP_ON_EVENT` | `true` | เปิด order ไม่ตั้ง TP เมื่อมี high-impact event |
| `NO_TP_EVENT_MINS` | `20` | ถ้า event อยู่ในช่วง X นาที → no TP |
| `NO_TP_WAIT_MINUTES` | `30` | รอ X นาทีหลัง event ก่อนตั้ง TP |

### X Accounts & Keywords

| Key | Default | รายละเอียด |
|---|---|---|
| `X_ACCOUNTS_TO_FOLLOW` | `kun_purich,cnnbrk,...` | X accounts ที่ติดตามสำหรับ sentiment |
| `X_KEYWORDS` | `XAUUSD,gold,XAU,...` | Keywords กรอง tweet |

ดูทั้งหมดได้ใน [`.env.example`](.env.example)

---

## โครงสร้างไฟล์

```
├── main.py                    # Entry point — trading loop (ทุก 300s)
├── config.py                  # โหลด config จาก .env + reload_config()
├── ecosystem.config.js        # PM2 config
├── Dockerfile                 # Linux image — dashboard เท่านั้น
├── Dockerfile.windows         # Windows image — bot + dashboard
├── docker-compose.yml         # Linux mode (dashboard + postgres)
├── docker-compose.windows.yml # Windows containers mode (ระบบเต็ม)
├── docker-start.ps1           # Startup script สำหรับ Windows container
├── start.bat                  # One-click startup สำหรับ Windows host
│
├── agents/
│   ├── chart_watcher.py       # วิเคราะห์ H4/H1/M15, หา setup, คำนวณ SL/TP
│   ├── market_advisor.py      # วิเคราะห์ market regime
│   ├── analyst.py             # วิเคราะห์ sentiment จากข่าว + X
│   ├── decision_maker.py      # 12 Python gates → Claude (8-line summary)
│   ├── pending_manager.py     # จัดการ pending orders
│   ├── news_gatherer.py       # รวบรวมข่าว
│   ├── reporter.py            # บันทึกผลการเทรด
│   ├── accountant.py          # คำนวณสถิติ P&L
│   └── news_cache.py          # Cache ข่าว
│
├── connectors/
│   ├── mt5_connector.py       # MT5 order management + lot sizing
│   ├── price_feed.py          # ดึงราคาและ indicator จาก MT5
│   ├── web_news.py            # ForexFactory + Investing.com
│   └── twitter_client.py      # X/Twitter client
│
├── db/
│   ├── schema.sql             # สร้าง tables (trades, agent_usage, cycles)
│   ├── connection.py          # สร้าง DB connection
│   ├── writer.py              # upsert trades, insert cycles
│   ├── reader.py              # query trades, accounting
│   ├── sync.py                # sync JSON → DB
│   └── migrate.py             # migrate JSON → Supabase
│
├── dashboard/
│   ├── app.py                 # Flask app (port 5050)
│   └── templates/
│       └── index.html
│
├── utils/
│   ├── market_clock.py        # คำนวณ interval + market sleep
│   └── display.py             # Rich terminal UI
│
├── agents/prompts/
│   ├── chart_watcher.md       # Prompt: chart analysis + scoring rules
│   ├── decision_maker.md      # Prompt: execute/skip quality check
│   ├── market_advisor.md      # Prompt: regime analysis
│   └── analyst.md             # Prompt: sentiment analysis
│
├── backtest/
│   └── monte_carlo.py         # Monte Carlo simulation (ไม่ใช้ historical data)
│
├── .env.example               # Template config
├── requirements.txt
├── SUPABASE.md                # คู่มือ Supabase setup
└── CHANGELOG.md
```

---

## ฟีเจอร์หลัก

### Entry Signal

- **Multi-timeframe analysis** — H4 (major S/R zones), H1 (minor zones + structure), M15 (entry trigger)
- **4-component H4 trend bias** — Price vs EMA200, H4 EMA50 slope, H1 EMA stack, H4 swing structure (ต้อง ≥3/4 ตัว จึงเป็น BULLISH/BEARISH)
- **Signal types**: SR_ZONE, STRUCTURE_PULLBACK, EMA_PULLBACK, BREAKOUT_RETEST, ENGULFING, DOJI_AT_ZONE, MOMENTUM_BREAKOUT
- **H1 structure confirmation** — ตรวจ higher lows / lower highs จาก swing จริง (+8-10 pts)
- **Bollinger Band squeeze** — BB reversal signals มี edge เฉพาะเมื่อ squeeze ก่อน
- **Fibonacci confluence** — +5–15 pts เมื่อ price อยู่ที่ key Fib + zone

### Risk Management

- **ATR-based SL floor** — SL = max(wick distance, 1.0× H4 ATR) ป้องกัน SL โดน H4 noise
- **SL range**: 500–3500 pips (XAU: 1 pip = $0.01)
- **Min R:R ratio**: 2.0 (breakeven WR = 33%)
- **Confidence-based position sizing** — conf 50%→0.63× size, conf 65%→0.81×, conf ≥80%→1.0×
- **Daily loss limit** — หยุดเทรดเมื่อถึง max_daily_loss %

### Decision Layer

- **12 Python gates** (gate 1–12) ก่อนเรียก Claude — filter quantitative conditions ทั้งหมด
- **Claude รับแค่ 8 บรรทัด** clean summary — ถามแค่ "setup quality ดีพอไหม?"
- **Input tokens ~150** ต่อ call (ลดจาก ~600)
- **Prompt caching** — ลดค่า Claude API ~80-90%

### Trade Management

- **Dynamic TP** — ขยับ TP อัตโนมัติเมื่อ momentum แรงและราคาใกล้ TP
- **Breakeven management** — ขยับ SL to BE หลัง price เคลื่อนพอ
- **Hedge buffer** — เปิด order ตรงข้ามได้เมื่อ price สวนทาง ≥ hedge_buffer_pips
- **Pending orders** — BUY_STOP / SELL_STOP วาง limit order ล่วงหน้า
- **Weekly calendar pending** — วาง pending ทุกวันจันทร์ตามปฏิทินข่าว

### Infrastructure

- **Market sleep** — หยุดอัตโนมัติ เสาร์-อาทิตย์ และช่วงตลาดปิด
- **Portfolio protection** — daily loss limit, losing streak protection
- **PostgreSQL / Supabase** — เก็บ trades, agent usage, cost tracking
- **Strategy versioning** — trades ใหม่ทุกตัวมี `strategy_version=2` แยกจาก data เก่า
- **Dashboard** — Flask web UI port 5050 พร้อม economic calendar
- **PM2 process manager** — auto-restart, เปลี่ยน config ได้ live ผ่าน dashboard

---

## Monte Carlo Simulation

ทดสอบ robustness ของ strategy โดยไม่ใช้ historical trade data (ใช้ assumed parameters แทน):

```bash
# ดูผลทุก WR ในตารางเดียว (แนะนำ)
python -m backtest.monte_carlo --sweep

# ทดสอบ config เฉพาะ
python -m backtest.monte_carlo --wr 0.42 --rr 2.0 --trades 200

# ดู options ทั้งหมด
python -m backtest.monte_carlo --help
```

ผลตัวอย่าง (R:R=2.0, risk=0.5%):

| WR | P(ruin >10%) | สรุป |
|---|---|---|
| 35% | 21% | อันตราย |
| 38% | 6% | borderline |
| 40% | 2.3% | ยอมรับได้ |
| 42%+ | <1% | ปลอดภัย |

ระบบต้องการ **WR ≥ 40%** (breakeven = 33.3% แต่ต้องการ margin เพิ่ม)

---

## Multi-User Setup (ใช้ DB ร่วมกัน)

ระบบรองรับ **หลาย user รันพร้อมกันบน Supabase เดียวกัน** — ทุก trade/cycle จะมี `account_login` (MT5 account number) ระบุว่าเป็นของใคร

### วิธีตั้งค่า

1. **Owner**: สร้าง Supabase project → รัน migration → แชร์ `SUPABASE_URL` และ `SUPABASE_KEY` ให้ user แต่ละคน
2. **แต่ละ user**: ใส่ใน `.env` ของตัวเอง — ไม่ต้องตั้งค่าเพิ่ม (ใช้ MT5_LOGIN เป็น identifier อัตโนมัติ)

```env
# ทุก user ใช้ค่าเดียวกัน
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiJ9...

# MT5_LOGIN ของแต่ละคนต่างกัน → DB แยก trades อัตโนมัติ
MT5_LOGIN=381706956
```

### Dashboard — ดูทุก account พร้อมกัน

```
# ดูเฉพาะตัวเอง (default)
http://localhost:5050

# ดูทุก user รวมกัน (owner analytics)
http://localhost:5050  →  API: /api/data?account=all
                           API: /api/accounting?account=all
```

### Migration สำหรับ DB เก่า

รัน SQL ทั้ง 2 ไฟล์ใน Supabase SQL Editor (หรือ psql):

```bash
psql $DATABASE_URL < db/migration_add_account_login.sql
psql $DATABASE_URL < db/migration_add_api_keys.sql
```

---

## API Proxy (ส่ง key ให้ user อย่างปลอดภัย)

แทนที่จะแชร์ Supabase key ตรงๆ — owner deploy proxy บน Render.com (ฟรี) แล้วออก key แยกให้แต่ละ user

### Architecture

```
User Bot → HTTPS + API_KEY → Render Proxy → Supabase (service key)
Owner Bot ──────────────────────────────→ Supabase (direct)
```

### Deploy Proxy (Owner ทำครั้งเดียว)

1. **Fork / push โค้ดนี้ไป GitHub**
2. ไปที่ [render.com](https://render.com) → New → Web Service → เลือก repo
3. ตั้งค่า:
   - **Root Directory**: `api_proxy`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. เพิ่ม Environment Variables บน Render:
   - `SUPABASE_URL` = Supabase project URL
   - `SUPABASE_SERVICE_KEY` = service_role key (Supabase → Settings → API)
5. Deploy → ได้ URL เช่น `https://xauusd-proxy.onrender.com`

### ออก API Key ให้ User

```bash
# รันบนเครื่อง owner — ต้องมี .env พร้อม SUPABASE credentials
python scripts/manage_api_keys.py
```

เลือก "2) สร้าง key ใหม่" → ใส่ MT5 login + ชื่อ user → ได้ key → ส่งให้ user

### User ตั้งค่า .env

```env
# User ใส่แค่นี้ — ไม่เห็น Supabase key เลย
TRADING_API_URL=https://xauusd-proxy.onrender.com
TRADING_API_KEY=key_ที่ได้รับจาก_owner
```

---

## Migrate ข้อมูลเก่า (JSON → Database)

ถ้ามีข้อมูล trade เก่าใน `logs/trades.json`:

```bash
# sync ไป PostgreSQL local
python db/sync.py

# sync ไป Supabase
python db/migrate.py
```

### อัปเกรด DB ที่มีอยู่แล้ว (เพิ่ม strategy_version)

ถ้ามี Supabase / PostgreSQL ที่สร้าง schema ไว้ก่อนหน้า รัน SQL นี้ครั้งเดียว:

```sql
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_version SMALLINT DEFAULT 1;
```

trades เก่าจะได้ `strategy_version=1` (legacy), trades ใหม่จะเป็น `2` โดยอัตโนมัติ

---

## ค่า Trading Parameters ปัจจุบัน

| Parameter | ค่าปัจจุบัน | เหตุผล |
|---|---|---|
| `min_rr_ratio` | **2.0** | Breakeven WR = 33% |
| `default_sl_pips` | **255** | ≈ 30% ของทุน 3,000 บาท ที่ 0.01 lot |
| `default_tp_pips` | **765** | R:R 3:1 (3× SL) |
| `hedge_buffer_pips` | **1000** | ต้องสวน 1000 pips ก่อน hedge ได้ |
| `SL_MIN_PIPS` | **500** | รองรับ scalp setup |
| `SL_MAX_PIPS` | **3500** | รองรับ volatile session |
| `ATR_SL_MULT` | **1.0** | SL ไม่ต่ำกว่า 1× H4 ATR |
| `CONF_FULL_SIZE_AT` | **80** | Full size เมื่อ confidence ≥ 80% |
| `CONF_MIN_SCALE` | **0.5** | Half size ที่ confidence ต่ำสุด |
