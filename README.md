# XAUUSD AI Trading System

Automated AI trading system for XAUUSD (Gold), powered by Claude (Anthropic) for multi-agent decision-making and MetaTrader 5 for execution.

---

## Architecture

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
│  Dashboard (port 5050)│  ← can run in Docker
│  Flask + Waitress    │
└──────────────────────┘
```

Each cycle (every ~300s by default, adaptive based on signal strength):

1. **ChartWatcher** — pulls H4/H1/M15 candles from MT5, scores entry setups (multi-timeframe S/R, structure, EMA pullback, breakout/retest, candlestick patterns, Fibonacci confluence), computes SL/TP.
2. **MarketAdvisor** — analyzes market regime (trend/range/volatility) for additional context.
3. **NewsGatherer + Analyst** — gathers tweets/ForexFactory calendar/web articles, summarizes and caches via vector search (Gemini embeddings), then asks Claude to classify sentiment (BULLISH/BEARISH/NEUTRAL) weighted toward hard calendar data over social sentiment.
4. **DecisionMaker** — runs 12 deterministic Python gates (risk limits, slot availability, sentiment alignment, losing-streak protection, etc.) first; only a compact 8-line summary is sent to Claude to make the final EXECUTE/SKIP call. This keeps input tokens around ~150/call and benefits heavily from prompt caching.
5. **MT5 Connector** — sizes the position (confidence-scaled risk or fixed lot), opens the order, and manages it afterward (breakeven, dynamic TP, partial close, hedge).
6. **Reporter / Accountant** — logs the trade and per-agent token cost to PostgreSQL/Supabase (with JSON fallback if the DB is unreachable).

---

## System Requirements

| Component | Requirement |
|---|---|
| **Trading Bot** (`main.py`) | Windows + MetaTrader 5 terminal running and logged in |
| **Dashboard** | Windows / Linux / Docker |
| Python | 3.11+ |
| Node.js | 18+ (for PM2) |
| Database | PostgreSQL 14+ or Supabase |

> ⚠️ The `MetaTrader5` Python library only works on **Windows**. The trading bot itself must run on a Windows host (or Windows container); the dashboard can run anywhere.

---

## Installation

### 1. Clone the repository

```bash
git clone git@github.com:JOTARO365/xauusd_ai_trading_system.git
cd xauusd_ai_trading_system
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

Open `.env` and fill in the required values (see [Environment Variables](#environment-variables) below).

### 4. Set up the database

Pick **one** of the two options below:

#### Option A — Local PostgreSQL (Docker)

```bash
# Start PostgreSQL via docker compose (port 5432)
docker compose up -d postgres

# In .env, use (this is the default):
DATABASE_URL=postgresql://trading:trading@localhost:5432/trading
```

Create the schema:

```bash
psql $DATABASE_URL < db/schema.sql
```

#### Option B — Supabase (Cloud)

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → paste and run the SQL from `SUPABASE.md`
3. In `.env`, update `DATABASE_URL`:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASS@db.xxxx.supabase.co:5432/postgres
```

> See [SUPABASE.md](SUPABASE.md) for details.

---

## Running the System

### Option 1 — PM2 (recommended)

```bash
# Install PM2
npm install -g pm2

# Run the trading bot + dashboard together
pm2 start ecosystem.config.js
pm2 save

# Check status
pm2 list
pm2 logs main
pm2 logs dashboard
```

Common PM2 commands:

```bash
pm2 restart main        # restart trading bot
pm2 restart dashboard   # restart dashboard
pm2 restart all         # restart everything
pm2 stop all            # stop everything
```

### Option 2 — Run directly

```bash
# Terminal 1: Trading bot
python main.py

# Terminal 2: Dashboard
python dashboard/app.py
```

`main.py` also accepts CLI overrides for risk/lot/protection settings — run `python main.py --help` for the full list.

---

## Dashboard

Open your browser to `http://localhost:5050`.

| Page | Description |
|---|---|
| **Overview** | Portfolio stats, trade history, economic calendar |
| **Settings** | Edit config live — changes are saved and PM2 auto-restarts the bot |

---

## Docker

Two modes are available depending on your needs:

### Mode A — Linux containers (Dashboard only)

Uses standard Docker Desktop (Linux mode) — **no mode switch needed**.

```bash
# Create .env first
cp .env.example .env    # Linux/Mac
copy .env.example .env  # Windows

# Run dashboard + postgres
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

- Dashboard available at `http://localhost:5050`
- The trading bot (`main.py`) must be run separately on the Windows host (via PM2 or `python main.py`), since MetaTrader5 doesn't run in a Linux container.

### Mode B — Windows containers (full system — Bot + Dashboard)

The Docker image bundles everything: **Python, Node.js, PM2**, and all Python packages.

**Requirements:**
1. Docker Desktop on Windows
2. Switch to Windows containers mode:
   - right-click the Docker icon in the system tray
   - select **"Switch to Windows containers..."**
3. MetaTrader5 terminal open and logged in on the host

```bash
# Create .env first
copy .env.example .env

# Build and run (first build takes ~15-30 min due to image size)
docker compose -f docker-compose.windows.yml up -d

# View logs in real-time
docker compose -f docker-compose.windows.yml logs -f

# Check PM2 status inside the container
docker exec xauusd-trading powershell -Command "pm2 list"

# Restart a specific process
docker exec xauusd-trading powershell -Command "pm2 restart main"
docker exec xauusd-trading powershell -Command "pm2 restart dashboard"

# Stop everything
docker compose -f docker-compose.windows.yml down
```

### Mode comparison

| | Mode A (Linux) | Mode B (Windows) |
|---|---|---|
| **Command** | `docker compose up -d` | `docker compose -f docker-compose.windows.yml up -d` |
| **Trading Bot** | Must run separately on host | Runs inside the container |
| **Image size** | ~500 MB | ~5-7 GB |
| **Build time** | ~2-5 min | ~15-30 min |
| **MetaTrader5** | Not supported | Supported (Windows IPC) |
| **Docker mode** | Linux (default) | Windows containers |

---

## Environment Variables

### Required

| Key | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — [console.anthropic.com](https://console.anthropic.com) |
| `MT5_LOGIN` | MT5 account number |
| `MT5_PASSWORD` | MT5 password |
| `MT5_SERVER` | Broker server name (e.g. `ICMarketsAu-Demo`) |
| `DATABASE_URL` | PostgreSQL connection string |

### X/Twitter (used for sentiment — optional)

| Key | Description |
|---|---|
| `X_USERNAME` | X (Twitter) username |
| `X_PASSWORD` | X password |
| `X_EMAIL` | X email (for 2FA) |

### Trading Config

| Key | Default | Description |
|---|---|---|
| `SYMBOL` | `XAUUSD` | Trading symbol (some brokers use `GOLD#`) |
| `START_BALANCE` | `5000` | Starting balance (account currency) |
| `LOT_MODE` | `auto` | `auto` = risk-based sizing / `fixed` = use `FIXED_LOT` |
| `FIXED_LOT` | `0.01` | Used when `LOT_MODE=fixed` |
| `MIN_LOT` | `0.01` | Minimum lot size |
| `MAX_LOT` | `0.01` | Maximum lot size |
| `RISK_PER_TRADE` | `0.50` | % risk per trade (0.50 = 0.5%) |
| `MAX_DAILY_LOSS` | `1.00` | Max daily loss % |
| `MAX_OPEN_TRADES` | `4` | Max simultaneous open trades per direction |
| `DEFAULT_SL_PIPS` | `2000` | Fallback SL (pips) when SL can't be computed |
| `DEFAULT_TP_PIPS` | `5000` | Fallback TP (pips) — minimum 2.0× SL |
| `MIN_RR_RATIO` | `2.0` | Minimum Risk/Reward ratio (breakeven WR = 33%) |
| `HEDGE_BUFFER_PIPS` | `2500` | Buffer (pips) before opening a hedge order |

### Position Sizing (Confidence-based)

| Key | Default | Description |
|---|---|---|
| `CONF_FULL_SIZE_AT` | `80` | Confidence % required for full position size |
| `CONF_MIN_SCALE` | `0.5` | Minimum scale (lowest confidence = half size) |

Example: conf=50% → 0.63× size, conf=65% → 0.81× size, conf≥80% → 1.0× size. Note: this scaling only applies in `LOT_MODE=auto` — `fixed` mode ignores confidence entirely.

### Pending Orders

| Key | Default | Description |
|---|---|---|
| `MAX_PENDING_BUY` | `4` | Max pending buy orders |
| `MAX_PENDING_SELL` | `4` | Max pending sell orders |
| `PENDING_EXPIRY_HOURS` | `24` | Pending order expiry (hours) |

### Streak & Portfolio Protection

| Key | Default | Description |
|---|---|---|
| `PORTFOLIO_PROTECTION` | `true` | Enable/disable daily loss limit + max trades guard |
| `STREAK_PROTECTION` | `true` | Enable/disable losing-streak protection |
| `MAX_LOSING_STREAK` | `5` | Consecutive losses before raising the confidence threshold |
| `STREAK_MIN_CONFIDENCE` | `62` | Minimum confidence required once streak protection triggers |

### Dynamic Features

| Key | Default | Description |
|---|---|---|
| `DYNAMIC_TP` | `true` | Automatically extend TP when momentum is strong and price nears TP |
| `NO_TP_ON_EVENT` | `true` | Open without a TP when a high-impact news event is near |
| `NO_TP_EVENT_MINS` | `20` | If an event is within X minutes → skip TP |
| `NO_TP_WAIT_MINUTES` | `30` | Wait X minutes after the event before setting TP |

### X Accounts & Keywords

| Key | Default | Description |
|---|---|---|
| `X_ACCOUNTS_TO_FOLLOW` | `kun_purich,cnnbrk,...` | X accounts followed for sentiment |
| `X_KEYWORDS` | `XAUUSD,gold,XAU,...` | Keywords used to filter tweets |

See the full list in [`.env.example`](.env.example).

---

## Project Structure

```
├── main.py                    # Entry point — trading loop (every ~300s)
├── config.py                  # Loads config from .env + reload_config()
├── ecosystem.config.js        # PM2 config
├── Dockerfile                 # Linux image — dashboard only
├── Dockerfile.windows         # Windows image — bot + dashboard
├── docker-compose.yml         # Linux mode (dashboard + postgres)
├── docker-compose.windows.yml # Windows containers mode (full system)
├── docker-start.ps1           # Startup script for Windows container
├── start.bat                  # One-click startup for Windows host
│
├── agents/
│   ├── chart_watcher.py       # H4/H1/M15 analysis, setup detection, SL/TP
│   ├── market_advisor.py      # Market regime analysis
│   ├── analyst.py             # News + X sentiment analysis
│   ├── decision_maker.py      # 12 Python gates → Claude (8-line summary)
│   ├── pending_manager.py     # Pending order management
│   ├── news_gatherer.py       # News aggregation
│   ├── reporter.py            # Trade result logging
│   ├── accountant.py          # P&L stats + token cost tracking
│   └── news_cache.py          # News cache (TTL + vector search)
│
├── connectors/
│   ├── mt5_connector.py       # MT5 order management + lot sizing
│   ├── price_feed.py          # Price/indicator retrieval from MT5
│   ├── web_news.py            # ForexFactory + Investing.com
│   └── twitter_client.py      # X/Twitter client
│
├── db/
│   ├── schema.sql             # Table definitions (trades, agent_usage, cycles)
│   ├── connection.py          # DB connection factory
│   ├── writer.py              # Upsert trades, insert cycles
│   ├── reader.py               # Query trades, accounting stats
│   ├── sync.py                # Sync JSON → DB
│   └── migrate.py             # Migrate JSON → Supabase
│
├── dashboard/
│   ├── app.py                 # Flask app (port 5050)
│   └── templates/
│       └── index.html
│
├── utils/
│   ├── market_clock.py        # Interval computation + market sleep
│   └── display.py             # Rich terminal UI
│
├── agents/prompts/
│   ├── chart_watcher.md       # Prompt: chart analysis + scoring rules
│   ├── decision_maker.md      # Prompt: execute/skip quality check
│   ├── market_advisor.md      # Prompt: regime analysis
│   └── analyst.md             # Prompt: sentiment analysis
│
├── backtest/
│   └── monte_carlo.py         # Monte Carlo simulation (assumption-based, not historical data)
│
├── .env.example                # Config template
├── requirements.txt
├── SUPABASE.md                 # Supabase setup guide
└── CHANGELOG.md
```

---

## Key Features

### Entry Signal

- **Multi-timeframe analysis** — H4 (major S/R zones), H1 (minor zones + structure), M15 (entry trigger)
- **4-component H4 trend bias** — price vs EMA200, H4 EMA50 slope, H1 EMA stack, H4 swing structure (needs ≥3/4 to confirm BULLISH/BEARISH)
- **Signal types**: SR_ZONE, STRUCTURE_PULLBACK, EMA_PULLBACK, BREAKOUT_RETEST, ENGULFING, DOJI_AT_ZONE, MOMENTUM_BREAKOUT
- **H1 structure confirmation** — checks real higher-low/lower-high swings (+8-10 pts)
- **Bollinger Band squeeze** — BB reversal signals only carry an edge after a squeeze
- **Fibonacci confluence** — +5–15 pts when price sits at a key Fib level + zone

### Risk Management

- **ATR-based SL floor** — SL = max(wick distance, 1.0× H4 ATR) to avoid getting stopped out by H4 noise
- **SL range**: 500–3500 pips (XAU: 1 pip = $0.01)
- **Min R:R ratio**: 2.0 (breakeven WR = 33%)
- **Confidence-based position sizing** — conf 50%→0.63× size, conf 65%→0.81×, conf ≥80%→1.0×
- **Daily loss limit** — trading halts once the max daily loss % is hit

### Decision Layer

- **12 Python gates** (gate 1–12) run before calling Claude — all quantitative filtering happens deterministically in code
- **Claude only sees an 8-line summary** — the only question asked is "is this setup quality good enough?"
- **~150 input tokens** per call (down from ~600)
- **Prompt caching** — cuts Claude API cost by ~80-90%

### Trade Management

- **Dynamic TP** — automatically extends TP when momentum is strong and price is near target
- **Breakeven management** — moves SL to breakeven after price has moved favorably enough
- **Hedge buffer** — allows opening an opposite-direction order once price moves against the position by ≥ `hedge_buffer_pips`
- **Pending orders** — BUY_STOP / SELL_STOP limit orders placed in advance
- **Weekly calendar pending** — places pending orders every Monday based on the economic calendar

### Infrastructure

- **Market sleep** — automatically pauses on weekends and during market closures
- **Portfolio protection** — daily loss limit, losing-streak protection
- **PostgreSQL / Supabase** — stores trades, agent usage, and cost tracking (JSON fallback if DB unreachable)
- **Strategy versioning** — every new trade is tagged `strategy_version=2`, kept separate from legacy data
- **Dashboard** — Flask web UI on port 5050 with an economic calendar view
- **PM2 process manager** — auto-restart, live config changes via the dashboard

---

## Monte Carlo Simulation

Tests strategy robustness using assumed parameters (this is **not** a historical backtest — no tick-level OHLC data is replayed):

```bash
# View results across multiple win rates in one table (recommended)
python -m backtest.monte_carlo --sweep

# Test a specific config
python -m backtest.monte_carlo --wr 0.42 --rr 2.0 --trades 200

# See all options
python -m backtest.monte_carlo --help
```

Example output (R:R=2.0, risk=0.5%):

| WR | P(ruin >10%) | Verdict |
|---|---|---|
| 35% | 21% | dangerous |
| 38% | 6% | borderline |
| 40% | 2.3% | acceptable |
| 42%+ | <1% | safe |

The strategy needs **WR ≥ 40%** (breakeven is 33.3%, but a margin is needed above that).

---

## Migrating Old Data (JSON → Database)

If you have old trade data in `logs/trades.json`:

```bash
# Sync to local PostgreSQL
python db/sync.py

# Sync to Supabase
python db/migrate.py
```

### Upgrading an existing DB (adding strategy_version)

If you already created the schema on an existing Supabase/PostgreSQL instance, run this once:

```sql
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_version SMALLINT DEFAULT 1;
```

Old trades will be tagged `strategy_version=1` (legacy); new trades are tagged `2` automatically.

---

## Current Trading Parameters

| Parameter | Current Value | Rationale |
|---|---|---|
| `min_rr_ratio` | **2.0** | Breakeven WR = 33% (raised from 1.5 for a larger margin) |
| `default_tp_pips` | **5000** | TP = 2.0× SL at a 2500-pip SL |
| `SL_MIN_PIPS` | **500** | Supports scalp setups |
| `SL_MAX_PIPS` | **3500** | Supports volatile sessions |
| `ATR_SL_MULT` | **1.0** | SL never tighter than 1× H4 ATR |
| `CONF_FULL_SIZE_AT` | **80** | Full size once confidence ≥ 80% |
| `CONF_MIN_SCALE` | **0.5** | Half size at the lowest confidence |

---

## Known Limitations

- **Lot sizing depends on the broker's real point value** — `mt5_connector.calculate_lot_size()` uses a `pip_value` constant for `LOT_MODE=auto`; verify it against your own broker's contract spec before going live with real money (a 10x mismatch was previously found and fixed against a live account).
- **Monte Carlo simulation is assumption-based**, not a real historical backtest — there is no tick-level OHLC replay in this repo. Treat its output as a sensitivity check on win-rate/R:R assumptions, not a performance guarantee.
- **News sentiment is cached** (`agents/news_cache.py`, ~1 hour TTL) for cost reasons — technical signals (ChartWatcher/MarketAdvisor) are recomputed fresh every cycle, but sentiment can lag a few cycles behind a sudden price reversal.
- This is an experimental, self-hosted trading system, not a packaged product or investment advice — use at your own risk and validate thoroughly on a demo account first.
