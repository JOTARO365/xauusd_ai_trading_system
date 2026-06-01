# XAUUSD AI Trading System

An automated AI trading bot for XAUUSD (Gold) using Claude AI + MetaTrader 5.

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
│  Dashboard (port 5050)│  ← Docker-ready
│  Flask + Waitress    │
└──────────────────────┘
```

---

## How the AI Pipeline Works (LangGraph)

The trading pipeline runs as a **state machine** — each step is a node in a graph, and the system decides which path to take based on real-time conditions.

### Graph Flow

<p align="center">
  <img src="docs/langgraph_state.png" alt="LangGraph state machine" width="360">
</p>

> **Legend** — 🟢 AI nodes (Claude) · 🟠 position-mgmt / reporter / accounting · 🔵 `_entry` router.
> Edge colors = the 3 auto-selected paths: 🟧 **orange** = skip-AI · 🟩 **green** = full cycle · 🟥 **red** = network-degraded.
> Regenerate with `python scripts/gen_graph_png.py` after editing the graph.

<details>
<summary>Text version (ASCII)</summary>

```
Every cycle (~15 min normal / ~5 min with open position)
                        │
                    [_entry]
                   /        \
           skip_ai?          full cycle
               │                  │
        [position_mgmt]       [chart_watcher]
               │                  │
              END             [market_advisor]
                              /           \
                    net_degraded?        OK
                         │                │
                    [accounting]       [news_gatherer]
                         │                │
                        END          [analyst]
                                          │
                                    [decision_maker]
                                          │
                                   [position_mgmt]
                                          │
                                     [reporter]
                                          │
                                    [accounting]
                                          │
                                         END
```

</details>

### What Each Node Does

| Node | Agent | Runs every cycle? | Description |
|---|---|---|---|
| `_entry` | — | Always | Checks whether to skip AI this cycle |
| `chart_watcher` | Claude | Full cycle only | Analyzes H4/H1/M15 charts — finds S/R zones, entry signal, confidence score |
| `market_advisor` | Claude | Full cycle only | Determines market regime (trending/sideways/volatile) and overall bias |
| `news_gatherer` | X/Twitter | Full cycle only | Collects latest tweets related to gold and macro economy |
| `analyst` | Claude | Full cycle only | Analyzes sentiment from news + chart combined |
| `decision_maker` | Claude | Full cycle only | Passes 12 Python gates → decides EXECUTE or SKIP |
| `position_mgmt` | MT5 | **Always** | Manages open positions (breakeven, trailing stop, momentum exit) |
| `reporter` | Claude | Full cycle only | Logs trade result, places pending orders, summarizes P&L |
| `accounting` | DB | Full cycle only | Records token cost and latency to database |

### 3 Paths — Chosen Automatically

**Path 1 — Full AI Cycle** (every ~15 min, or ~5 min when a position is open)
> All nodes run — AI makes the trade decision

**Path 2 — Skip AI** (between full cycles)
> Skips all AI agents → runs only `position_mgmt` to manage open positions
> Saves ~97% of token cost

**Path 3 — Network Degraded** (chart + advisor both fail)
> Halts decision-making → runs `accounting` and exits; no new orders placed

### Smart Skip Gate

To stay within a token budget while running 24/7, the gate **throttles** AI calls — it force-runs AI only on genuine signals, and throttles the rest:

| Condition | Behavior |
|---|---|
| First cycle after start | Always runs |
| Price spike ≥ `AI_SPIKE_PIPS` (500) | Always runs — breaking news / flash crash (overrides throttle) |
| Ready Mode active (price at D1/W1 HTF zone) | Runs AI, but **throttled** to once per `READY_AI_MIN_SECS` (5 min) |
| Price within ≤ `AI_SR_PROXIMITY_PCT` (0.1%) of a **major HTF (D1/W1)** zone | Same 5-min throttle |
| News window (8–9, 13–15, 18–19 UTC) | AI interval reduced to 3 minutes |
| Otherwise | Normal: 15 min idle / 5 min with an open position |

> **Why throttle?** Older builds treated *every* H4/H1 minor S/R level (within 0.3%) **and** Ready Mode as "never skip", so the full 4-agent pipeline fired every ~2 minutes and dominated token cost (~$24/day). The gate now only force-runs on real signals (spikes, major D1/W1 zones) and caps AI frequency to once per 5 min during those windows — the spike override still reacts instantly to fast moves in any session.

### Why LangGraph?

| | Before (sequential) | After (LangGraph) |
|---|---|---|
| State | 6 scattered globals | Single `TradingState` TypedDict |
| Error handling | 6 duplicated try/except blocks | Isolated per node |
| Position mgmt code | Duplicated in 2 places | Single `position_mgmt` node |
| Cross-cycle state | Carried implicitly, easy to leak | Stateless per cycle — `compile()` has **no checkpointer**, so nothing bleeds between cycles; only `_last_chart_data`/`_last_sentiment` are carried forward explicitly |
| Adding a new agent | Edit main.py | One `add_node()` call |

---

## Requirements

| Component | Requirement |
|---|---|
| **Trading Bot** (main.py) | Windows + MetaTrader5 Terminal running |
| **Dashboard** | Windows / Linux / Docker |
| Python | 3.11+ |
| Node.js | 18+ (for PM2) |
| Database | PostgreSQL 14+ or Supabase |

> ⚠️ The `MetaTrader5` Python library only supports **Windows**

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

### 3. Configure .env

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

Open `.env` and fill in the required values (see [Environment Variables](#environment-variables) below).

### 4. Set up Database

Choose **one** of the following options:

#### Option A — Local PostgreSQL (Docker)

```bash
# Start PostgreSQL via docker compose (port 5432)
docker compose up -d postgres

# Use this DATABASE_URL in .env (already the default)
DATABASE_URL=postgresql://trading:trading@localhost:5432/trading
```

Create the schema:

```bash
psql $DATABASE_URL < db/schema.sql
```

#### Option B — Supabase (Cloud)

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → paste the SQL from `SUPABASE.md` and run it
3. Update DATABASE_URL in `.env`:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASS@db.xxxx.supabase.co:5432/postgres
```

> See [SUPABASE.md](SUPABASE.md) for full details.

---

## Running the System

### Option 1 — PM2 (Recommended)

```bash
# Install PM2
npm install -g pm2

# Start trading bot + dashboard together
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

### Option 2 — Direct

```bash
# Terminal 1: Trading bot
python main.py

# Terminal 2: Dashboard
python dashboard/app.py
```

---

## Dashboard

Open your browser at `http://localhost:5050`

| Page | Description |
|---|---|
| **Overview** | Portfolio, statistics, trade history, economic calendar |
| **Settings** | Live config editing — saves and auto-restarts via PM2 |

---

## Docker

Two modes depending on your setup:

### Mode A — Linux containers (Dashboard only)

Standard Docker Desktop (Linux mode) — **no need to switch modes**

```bash
# Create .env first
cp .env.example .env   # Linux/Mac
copy .env.example .env  # Windows

# Start dashboard + postgres
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

- Dashboard available at `http://localhost:5050`
- Trading bot (`main.py`) must run separately on the Windows host via PM2 or `python main.py`

### Mode B — Windows containers (Full system — Bot + Dashboard)

Docker runs everything: **Python, Node.js, PM2** and all Python packages.

**Requirements:**
1. Docker Desktop on Windows
2. Switch to Windows containers mode:
   - Right-click the Docker icon in the system tray
   - Select **"Switch to Windows containers..."**
3. MetaTrader5 terminal must be open and logged in on the host

```bash
# Create .env first
copy .env.example .env

# Build and run (first build takes ~15-30 min due to large image size)
docker compose -f docker-compose.windows.yml up -d

# View real-time logs
docker compose -f docker-compose.windows.yml logs -f

# Check PM2 status inside container
docker exec xauusd-trading powershell -Command "pm2 list"

# Restart a specific process
docker exec xauusd-trading powershell -Command "pm2 restart main"
docker exec xauusd-trading powershell -Command "pm2 restart dashboard"

# Stop everything
docker compose -f docker-compose.windows.yml down
```

### Comparison

| | Mode A (Linux) | Mode B (Windows) |
|---|---|---|
| **Command** | `docker compose up -d` | `docker compose -f docker-compose.windows.yml up -d` |
| **Trading Bot** | Must run separately on host | Included |
| **Image size** | ~500 MB | ~5-7 GB |
| **Build time** | ~2-5 min | ~15-30 min |
| **MetaTrader5** | Not supported | Supported (Windows IPC) |
| **Docker mode** | Linux (default) | Windows containers |

---

## 24/7 Cloud Deployment (GCP Windows VM)

Scripts in `scripts/` provision a Windows VM that runs MT5 + bot 24/7. A Windows host is required because MT5 needs a GUI session (`mt5.initialize()` attaches to a running terminal).

### One-shot (from GCP Cloud Shell)

```bash
# Creates an e2-medium Windows Server 2022 VM (Singapore), then installs
# Python/Git/MT5(XM) + clones the repo via a startup script.
bash scripts/create_vm.sh <github_token> <your_ip>/32
```

> ⚠️ **Security** — always pass `<your_ip>/32` (check at whatismyip.com) to restrict RDP. Open RDP (3389) to `0.0.0.0/0` is a top brute-force target; if you omit the IP, the script now **prompts for confirmation** before exposing it publicly.

### On the VM (after RDP in)

1. Open MT5 (XM) and log in once — the terminal must have run interactively
2. Fill `C:\trading\xauusd_ai_trading_system\.env`
3. Enable 24/7 auto-start (PowerShell **as Administrator**):

```powershell
C:\trading\xauusd_ai_trading_system\scripts\autostart_vm.ps1
```

This registers At-LogOn / Interactive scheduled tasks for the bot + dashboard that restart on crash and survive reboot. Follow the auto-logon note it prints so MT5 has a desktop session after reboots.

> The startup script (`setup_vm_startup.ps1`) is **idempotent** — it skips already-installed components on later boots (markers: `.mt5_installed`, `.deps_installed`). The dashboard port (5050) is **not** opened in the firewall; reach it from mobile over a private network (e.g. Tailscale) rather than exposing it publicly — the dashboard has no auth and can close trades / edit config.

### Auto-deploy & ops scripts

| Script | Purpose |
|---|---|
| `scripts/auto_deploy.ps1` (run via `pm2_autodeploy.js`) | PM2 watcher — every **60 s** runs `git fetch`; if the remote moved, does a stash-safe `git pull` + `pm2 restart main dashboard`. Pushed code reaches the VM automatically. |
| `scripts/health_check.ps1` | One-shot liveness check: process/PID, `bot_status.json` freshness, MT5 + cycle activity, dashboard `200`, today's token cost vs budget. `exit 0` healthy / `1` problem. |
| `scripts/apply_vm_config.ps1` | Safely edit the VM `.env` (e.g. `NNLB_EQUITY_PER_LOT`, `CHART_SHADOW`) — backs up first, edits only the target keys (keeps comments), restarts PM2, then verifies. Use `-DryRun` to preview. |
| `scripts/gen_graph_png.py` | Regenerate the LangGraph diagram (`docs/langgraph_state.png`). |

> ⚠️ **`.env` is git-ignored** — auto-deploy ships *code* only, never your `.env`. Change runtime config on the VM with `apply_vm_config.ps1` (or edit `.env` + `pm2 restart main`); a `git pull` showing "up-to-date" means code is synced, **not** that `.env` values changed.

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

### X/Twitter (for sentiment — optional)

| Key | Description |
|---|---|
| `X_USERNAME` | X (Twitter) username |
| `X_PASSWORD` | X password |
| `X_EMAIL` | X email (for 2FA) |

### Trading Config

| Key | Default | Description |
|---|---|---|
| `SYMBOL` | `XAUUSD` | Trading symbol (XM Global uses `GOLD#`) |
| `START_BALANCE` | `3000` | Starting balance in account currency |
| `LOT_MODE` | `auto` | `auto` = risk-based sizing / `fixed` = use FIXED_LOT |
| `FIXED_LOT` | `0.01` | Used when LOT_MODE=fixed |
| `MIN_LOT` | `0.01` | Minimum lot size |
| `MAX_LOT` | `0.01` | Maximum lot size |
| `RISK_PER_TRADE` | `0.50` | Risk per trade % (0.50 = 0.5%) |
| `MAX_DAILY_LOSS` | `1.00` | Max daily loss % |
| `MAX_OPEN_TRADES` | `4` | Max simultaneous open trades |
| `DEFAULT_SL_PIPS` | `255` | Default SL in pips |
| `DEFAULT_TP_PIPS` | `765` | Default TP in pips (3× SL, R:R 3:1) |
| `MIN_RR_RATIO` | `2.0` | Minimum Risk/Reward ratio (breakeven WR = 33%) |
| `HEDGE_BUFFER_PIPS` | `1000` | Pips before hedge order is allowed |

### Advanced Features

| Key | Default | Description |
|---|---|---|
| `LESSON_LEARNING` | `true` | RAG-based Lesson Retrieval — remembers past mistakes and warns DecisionMaker (requires GEMINI_API_KEY) |
| `DRY_RUN` | `false` | Mock MT5 execution — full pipeline runs but no real orders are sent |
| `NNLB_MODE` | `false` | **No-Risk-No-Lamborghini** — bypasses all gates and money management; lot scales with equity tier |
| `NNLB_BASE_EQUITY` | `100` | NNLB: minimum equity (**USD**) before first order — auto-converted to account currency |
| `NNLB_EQUITY_PER_LOT` | `100` | NNLB: profit (**USD**) per +0.01 lot — e.g. base 25 + per_lot 25 → equity $75 = lot 0.03 |
| `NNLB_MAX_LOSS_PCT` | `25` | NNLB: max loss per trade as % of equity — lot auto-reduced to stay within budget |
| `CHART_SHADOW` | `false` | A/B token test — runs a **terse-output** variant of `chart_watcher` in parallel on the same input, logging a field-by-field comparison to `logs/shadow_chart.jsonl`. Real trading is unaffected (always uses the verbose output). Analyze with `python scripts/shadow_report.py`; switch to terse only if `decision_match ≥ 95%`. |

> **NNLB values are USD-canonical.** `NNLB_BASE_EQUITY` and `NNLB_EQUITY_PER_LOT` are entered in USD and auto-converted to the account currency at runtime (rate derived from gold's pip value: USD → ×1, THB → ×~36). One config set works for USD and THB accounts alike — no per-currency tuning. ⚠️ Also raise `MAX_LOT` (default `0.01` caps all scaling).

### Position Sizing (Confidence-based)

| Key | Default | Description |
|---|---|---|
| `CONF_FULL_SIZE_AT` | `80` | Confidence % for full position size |
| `CONF_MIN_SCALE` | `0.5` | Minimum size scale at low confidence |

Example: conf=50% → 0.63× size, conf=65% → 0.81× size, conf≥80% → 1.0× size

### Pending Orders

| Key | Default | Description |
|---|---|---|
| `MAX_PENDING_BUY` | `4` | Max pending buy orders |
| `MAX_PENDING_SELL` | `4` | Max pending sell orders |
| `PENDING_EXPIRY_HOURS` | `48` | Pending order expiry (hours) |

### Streak & Portfolio Protection

| Key | Default | Description |
|---|---|---|
| `PORTFOLIO_PROTECTION` | `true` | Enable/disable portfolio protection (daily loss limit, max trades) |
| `STREAK_PROTECTION` | `true` | Enable/disable losing streak protection |
| `MAX_LOSING_STREAK` | `5` | Consecutive losses before raising confidence threshold |
| `STREAK_MIN_CONFIDENCE` | `62` | Minimum confidence when streak is triggered |

### Dynamic Features

| Key | Default | Description |
|---|---|---|
| `DYNAMIC_TP` | `true` | Auto-extend TP when momentum is strong and price is near TP |
| `NO_TP_ON_EVENT` | `true` | Open orders without TP during high-impact news events |
| `NO_TP_EVENT_MINS` | `20` | If event is within X minutes, skip TP |
| `NO_TP_WAIT_MINUTES` | `30` | Wait X minutes after event before setting TP |

See all variables in [`.env.example`](.env.example)

---

## File Structure

```
├── main.py                    # Entry point — trading loop (every 300s)
├── config.py                  # Load config from .env + reload_config()
├── ecosystem.config.js        # PM2 config
├── Dockerfile                 # Linux image — dashboard only
├── Dockerfile.windows         # Windows image — bot + dashboard
├── docker-compose.yml         # Linux mode (dashboard + postgres)
├── docker-compose.windows.yml # Windows containers mode (full system)
├── docker-start.ps1           # Startup script for Windows container
├── start.bat                  # One-click startup for Windows host
│
├── agents/
│   ├── chart_watcher.py       # H4/H1/M15 analysis, setup detection, SL/TP calculation
│   ├── market_advisor.py      # Market regime analysis
│   ├── analyst.py             # Sentiment analysis from news + X
│   ├── decision_maker.py      # 12 Python gates → Claude (8-line summary)
│   ├── pending_manager.py     # Pending order management
│   ├── news_gatherer.py       # News aggregation
│   ├── reporter.py            # Trade result logging
│   ├── accountant.py          # P&L statistics
│   └── news_cache.py          # News cache
│
├── connectors/
│   ├── mt5_connector.py       # MT5 order management + lot sizing
│   ├── price_feed.py          # Price and indicator feed from MT5
│   ├── web_news.py            # ForexFactory + Investing.com
│   └── twitter_client.py      # X/Twitter client
│
├── db/
│   ├── schema.sql             # Table definitions (trades, agent_usage, cycles)
│   ├── connection.py          # DB connection
│   ├── writer.py              # Upsert trades, insert cycles
│   ├── reader.py              # Query trades, accounting
│   ├── sync.py                # Sync JSON → DB
│   └── migrate.py             # Migrate JSON → Supabase
│
├── dashboard/
│   ├── app.py                 # Flask app (port 5050)
│   └── templates/
│       └── index.html
│
├── utils/
│   ├── market_clock.py        # Interval calculation + market sleep
│   └── display.py             # Rich terminal UI
│
├── agents/prompts/
│   ├── chart_watcher.md       # Prompt: chart analysis + scoring rules
│   ├── decision_maker.md      # Prompt: execute/skip quality check
│   ├── market_advisor.md      # Prompt: regime analysis
│   └── analyst.md             # Prompt: sentiment analysis
│
├── backtest/
│   └── monte_carlo.py         # Monte Carlo simulation
│
├── .env.example               # Config template
├── requirements.txt
├── SUPABASE.md                # Supabase setup guide
└── CHANGELOG.md
```

---

## Core Features

### Entry Signal

- **Multi-timeframe analysis** — H4 (major S/R zones), H1 (minor zones + structure), M15 (entry trigger)
- **4-component H4 trend bias** — Price vs EMA200, H4 EMA50 slope, H1 EMA stack, H4 swing structure (≥3/4 required for BULLISH/BEARISH)
- **Signal types**: SR_ZONE, STRUCTURE_PULLBACK, EMA_PULLBACK, BREAKOUT_RETEST, ENGULFING, DOJI_AT_ZONE, MOMENTUM_BREAKOUT
- **Trend continuation (NNLB)** — H1+H4 EMA stack alignment triggers SELL/BUY without requiring a D1/W1 zone
- **H1 structure confirmation** — higher lows / lower highs from real swing points (+8-10 pts)
- **Bollinger Band squeeze** — BB reversal signals carry edge only when a squeeze precedes them
- **Fibonacci confluence** — +5-15 pts when price is at a key Fib level + zone

### Risk Management

- **ATR-based SL floor** — SL = max(wick distance, 1.0× H4 ATR) to avoid noise stop-outs
- **SL range**: 500–3500 pips (XAU: 1 pip = $0.01)
- **Min R:R ratio**: 2.0 (breakeven WR = 33%)
- **Confidence-based position sizing** — conf 50%→0.63× size, conf 65%→0.81×, conf ≥80%→1.0×
- **Daily loss limit** — halts trading when max_daily_loss % is reached
- **Momentum exit** — closes positions early when strong counter-momentum detected (loss ≥100 pips + M15 momentum, or M1 spike ≥500 pips)

### Decision Layer

- **12 Python gates** (gates 1–12) before calling Claude — quantitative filters only
- **Claude receives only an 8-line** clean summary — asked only "is the setup quality good enough?"
- **Input tokens ~150** per call (reduced from ~600)
- **Prompt caching** — reduces Claude API cost by ~80-90%

### Trade Management

- **Dynamic TP** — auto-extends TP when momentum is strong and price approaches TP
- **Breakeven management** — moves SL to breakeven after sufficient price movement
- **Zone-break close** — force-closes positions when M15 closes beyond the HTF zone by >300 pips; monitors for false-break re-entry over 4 hours
- **Hedge buffer** — allows counter-direction orders when price moves ≥ hedge_buffer_pips against open position
- **Pending orders** — BUY_STOP / SELL_STOP limit orders placed in advance
- **Weekly calendar pending** — places pending orders every Monday based on news calendar

### Infrastructure

- **Market sleep** — auto-pauses on weekends and when markets are closed
- **Portfolio protection** — daily loss limit, losing streak protection
- **PostgreSQL / Supabase** — stores trades, agent usage, cost tracking
- **Strategy versioning** — all new trades include `strategy_version=2` to distinguish from legacy data
- **Dashboard** — Flask web UI on port 5050 with economic calendar
- **PM2 process manager** — auto-restart, live config changes via dashboard

---

## Monte Carlo Simulation

Tests strategy robustness without historical trade data (uses assumed parameters):

```bash
# View all win rates in one table (recommended)
python -m backtest.monte_carlo --sweep

# Test a specific config
python -m backtest.monte_carlo --wr 0.42 --rr 2.0 --trades 200

# View all options
python -m backtest.monte_carlo --help
```

Sample results (R:R=2.0, risk=0.5%):

| WR | P(ruin >10%) | Assessment |
|---|---|---|
| 35% | 21% | Dangerous |
| 38% | 6% | Borderline |
| 40% | 2.3% | Acceptable |
| 42%+ | <1% | Safe |

The system requires **WR ≥ 40%** (breakeven = 33.3%, but a margin is needed).

---

## Multi-User Setup (Shared Database)

The system supports **multiple users running simultaneously on a single Supabase instance** — every trade and cycle is tagged with `account_login` (MT5 account number) to identify ownership.

### Setup

1. **Owner**: Create a Supabase project → run the migration → share `SUPABASE_URL` and `SUPABASE_KEY` with each user
2. **Each user**: Add to their own `.env` — no additional configuration needed (MT5_LOGIN is used as the identifier automatically)

```env
# All users share the same values
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiJ9...

# Each user's MT5_LOGIN differs → DB separates trades automatically
MT5_LOGIN=381706956
```

### Dashboard — View all accounts

```
# View your own account (default)
http://localhost:5050

# View all users combined (owner analytics)
http://localhost:5050  →  API: /api/data?account=all
                           API: /api/accounting?account=all
```

### Migration for existing databases

Run both SQL files in Supabase SQL Editor (or psql):

```bash
psql $DATABASE_URL < db/migration_add_account_login.sql
psql $DATABASE_URL < db/migration_add_api_keys.sql
```

---

## API Proxy (Distribute keys to users securely)

Instead of sharing the Supabase key directly — the owner deploys a proxy on Render.com (free tier) and issues individual keys to each user.

### Architecture

```
User Bot → HTTPS + API_KEY → Render Proxy → Supabase (service key)
Owner Bot ──────────────────────────────→ Supabase (direct)
```

### Deploy Proxy (Owner does this once)

1. **Fork / push this repo to GitHub**
2. Go to [render.com](https://render.com) → New → Web Service → select the repo
3. Configure:
   - **Root Directory**: `api_proxy`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variables on Render:
   - `SUPABASE_URL` = Supabase project URL
   - `SUPABASE_SERVICE_KEY` = service_role key (Supabase → Settings → API)
5. Deploy → get a URL like `https://xauusd-proxy.onrender.com`

### Issue API keys to users

```bash
# Run on owner's machine — requires .env with SUPABASE credentials
python scripts/manage_api_keys.py
```

Select "Create new key" → enter MT5 login + username → get a key → send to user.

### User .env configuration

```env
# User only needs these — never sees the Supabase key
TRADING_API_URL=https://xauusd-proxy.onrender.com
TRADING_API_KEY=key_received_from_owner
```

---

## Migrate Legacy Data (JSON → Database)

If you have existing trade data in `logs/trades.json`:

```bash
# Sync to local PostgreSQL
python db/sync.py

# Sync to Supabase
python db/migrate.py
```

### Upgrade existing database (add strategy_version)

If you have an existing Supabase / PostgreSQL schema, run this SQL once:

```sql
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_version SMALLINT DEFAULT 1;
```

Old trades will have `strategy_version=1` (legacy), new trades will be `2` automatically.

---

## Current Trading Parameters

| Parameter | Value | Reason |
|---|---|---|
| `min_rr_ratio` | **2.0** | Breakeven WR = 33% |
| `default_sl_pips` | **255** | ~30% of 3,000 THB capital at 0.01 lot |
| `default_tp_pips` | **765** | R:R 3:1 (3× SL) |
| `hedge_buffer_pips` | **1000** | Must move 1000 pips against position before hedge is allowed |
| `SL_MIN_PIPS` | **500** | Supports scalp setups |
| `SL_MAX_PIPS` | **3500** | Supports volatile sessions |
| `ATR_SL_MULT` | **1.0** | SL no lower than 1× H4 ATR |
| `CONF_FULL_SIZE_AT` | **80** | Full size at confidence ≥ 80% |
| `CONF_MIN_SCALE` | **0.5** | Half size at minimum confidence |

---

## Preset for Small Account (~$28 / 1,000 THB)

Use **NNLB mode** to bypass money management gates and scale lot with equity. NNLB
values are **USD** and auto-convert to the account currency, so this same preset
works for a USD or a THB account unchanged:

```env
NNLB_MODE=true
NNLB_BASE_EQUITY=25         # USD — min equity before first order (THB acct → ~900฿)
NNLB_EQUITY_PER_LOT=25      # USD — +0.01 lot per $25 profit above base
NNLB_MAX_LOSS_PCT=30        # Auto-reduce lot so max loss ≤ 30% per trade
MIN_LOT=0.01
MAX_LOT=0.05                # ⚠️ must be > MIN_LOT or lot can never scale up
DEFAULT_SL_PIPS=500         # Tighter SL to keep risk reasonable
DEFAULT_TP_PIPS=1500        # R:R 3:1
START_BALANCE=28
PORTFOLIO_PROTECTION=false  # Disable daily loss gate (too small to keep it enabled)
```

Lot progression with this preset: equity $28 (profit $3) → `lot 0.01`; equity $50
(profit $25) → `lot 0.02`; equity $75 → `lot 0.03` … capped at `MAX_LOT`.

> **Note**: With $28 capital and MIN_LOT=0.01, SL=500 pips — max loss per trade is $50 (178% of capital).
> The system will log an `NNLB ⚠` warning but will still enter since NNLB is explicitly an accept-all-risk mode.
> Recommended minimum for NNLB_MAX_LOSS_PCT to work effectively: **$100+**
