# XAUUSD AI Trading System

ระบบ AI Trading อัตโนมัติสำหรับ XAUUSD (ทองคำ) โดยใช้ Claude AI + MetaTrader 5

---

## สถาปัตยกรรม

```
┌─────────────────────────────────────────────────────────┐
│                   AI Agent Pipeline                      │
│                                                         │
│  ChartWatcher → MarketAdvisor → Analyst → DecisionMaker │
│                                    ↓                    │
│              MT5 Connector (open/close orders)          │
└─────────────────────────────────────────────────────────┘
         ↕ logs/trades.json
┌──────────────────────┐
│  Dashboard (port 5050)│  ← รันใน Docker ได้
│  Flask + Waitress    │
└──────────────────────┘
```

---

## ความต้องการของระบบ

| Component | ความต้องการ |
|---|---|
| **Trading Bot** (main.py) | Windows + MetaTrader5 Terminal |
| **Dashboard** | Windows / Linux / Docker |
| Python | 3.11+ |
| Node.js | 18+ (สำหรับ PM2) |

> ⚠️ `MetaTrader5` Python library รองรับ **Windows เท่านั้น**

---

## ติดตั้ง

### 1. Clone โปรเจกต์

```bash
git clone git@github.com:JOTARO365/xauusd_ai_tranding_system.git
cd xauusd_ai_tranding_system
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

เปิด `.env` แล้วกรอกข้อมูล:

```env
ANTHROPIC_API_KEY=your_key_here
MT5_LOGIN=your_mt5_login
MT5_PASSWORD=your_mt5_password
MT5_SERVER=your_broker_server
X_USERNAME=your_x_username
X_PASSWORD=your_x_password
X_EMAIL=your_x_email
```

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

## Docker (Dashboard เท่านั้น)

```bash
# สร้าง .env ก่อน
cp .env.example .env

# รัน dashboard ใน Docker
docker compose up -d

# ดู logs
docker compose logs -f dashboard
```

> Trading bot ต้องรันบน Windows host แยกต่างหากด้วย PM2

---

## โครงสร้างไฟล์

```
├── main.py                  # Entry point — trading loop
├── config.py                # โหลด config จาก .env
├── ecosystem.config.js      # PM2 config
├── Dockerfile               # Dashboard Docker image
├── docker-compose.yml
│
├── agents/
│   ├── chart_watcher.py     # วิเคราะห์กราฟ + หา setup
│   ├── market_advisor.py    # วิเคราะห์ regime ตลาด
│   ├── analyst.py           # วิเคราะห์ sentiment ข่าว
│   ├── decision_maker.py    # ตัดสินใจเปิด/ปิด order
│   ├── pending_manager.py   # จัดการ pending orders
│   ├── news_gatherer.py     # รวบรวมข่าว
│   └── reporter.py          # บันทึกผลการเทรด
│
├── connectors/
│   ├── mt5_connector.py     # MT5 order management
│   ├── price_feed.py        # ดึงราคาจาก MT5
│   ├── web_news.py          # ForexFactory + Investing.com
│   └── twitter_client.py    # X/Twitter client
│
├── dashboard/
│   ├── app.py               # Flask app (port 5050)
│   └── templates/
│       └── index.html
│
├── utils/
│   ├── market_clock.py      # คำนวณ interval + market sleep
│   └── display.py           # Rich terminal UI
│
├── .env.example             # Template config
└── requirements.txt
```

---

## ฟีเจอร์หลัก

- **Multi-timeframe analysis** — H4, H1, M15
- **Dynamic TP** — ขยับ TP อัตโนมัติเมื่อ momentum แรง
- **Hedge buffer** — เปิด order ตรงข้ามได้เมื่อ price สวนทาง ≤ 1000 จุด
- **Market sleep** — หยุด เสาร์-อาทิตย์ และช่วงตลาดปิด (ตี4-ตี5 BKK)
- **Weekly calendar pending** — วาง BUY_STOP + SELL_STOP ทุกวันจันทร์ตามปฏิทินข่าว
- **Economic calendar** — แสดงข่าว High/Medium impact ใน dashboard
- **Prompt caching** — ลดค่า Claude API ~80-90%
- **Portfolio protection** — daily loss limit, losing streak protection

---

## Environment Variables

| Key | Default | รายละเอียด |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude API key (required) |
| `MT5_LOGIN` | — | MT5 account number (required) |
| `MT5_PASSWORD` | — | MT5 password (required) |
| `MT5_SERVER` | — | Broker server name (required) |
| `SYMBOL` | `XAUUSD` | Trading symbol |
| `START_BALANCE` | `2000` | ทุนเริ่มต้น (USD) |
| `RISK_PER_TRADE` | `0.50` | % risk ต่อ trade |
| `MAX_DAILY_LOSS` | `1.00` | % loss สูงสุดต่อวัน |
| `MAX_OPEN_TRADES` | `4` | จำนวน trade สูงสุด |
| `HEDGE_BUFFER_PIPS` | `1000` | ช่องไฟ hedge (จุด) |
| `PM2_APP_NAME` | `main` | ชื่อ PM2 process |
| `MARKET_CLOSE_UTC` | `21` | ชั่วโมงที่ตลาดปิด (UTC) |
| `MARKET_OPEN_UTC` | `22` | ชั่วโมงที่ตลาดเปิด (UTC) |

ดูทั้งหมดได้ใน [`.env.example`](.env.example)
