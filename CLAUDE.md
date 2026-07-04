# Project Config — XAUUSD AI Trading System

Extends the global `~/.claude/CLAUDE.md` (pipeline workflow, code style,
sub-agent delegation). This file adds only project-specific facts.

⚠️ **This repo also has `.claude/CLAUDE.md` (startup instructions, Thai).
Its rules take precedence over the generic pipeline flow** — see Overrides.

## Tech Stack

- Python 3.x (Windows-only — depends on the MetaTrader5 package)
- Claude / Anthropic API — agent pipeline: ChartWatcher → MarketAdvisor →
  Analyst → DecisionMaker → MT5
- MetaTrader5 (live trading terminal)
- Flask + Waitress — dashboard on port **5050**
- PostgreSQL (local Docker or Supabase, switched via `DATABASE_URL`);
  tables: `trades`, `agent_usage`, `cycles`
- Project version: v0.4.0

## Commands (PowerShell)

`python` is NOT in PATH on this machine — use the full interpreter path:

```powershell
$PY = "C:\Users\pornnatcha\AppData\Local\Microsoft\WindowsApps\python.exe"

# Run the trading bot
& $PY main.py

# Run the dashboard (port 5050)
& $PY dashboard\app.py

# Tests (no formal runner configured — this is the suite the auditor runs)
& $PY tests\test_all.py

# Process manager / containers
pm2 start ecosystem.config.js
docker compose -f docker-compose.windows.yml up -d
```

Note: some tests in `tests/test_all.py` are time-of-day dependent (session
gates change behavior in Asian/quiet hours). The auditor must compare
failures against a baseline run (`git stash` trick) before blaming a change.

## Folder Structure

```
main.py            entry point (bot loop)
config.py          ALL env/config loading lives here
agents/            AI agents (chart_watcher, analyst, decision_maker, ...)
agents/prompts/    *.json = LIVE prompts the LLM reads; *.md = reference only
connectors/        mt5_connector, price_feed, web_news, twitter_client
db/                connection / reader / writer / schema.sql
dashboard/app.py   Flask dashboard
logs/              trades.json, system.log, accounting.json, bot_status.json
data/              event_stats.json etc.
docs/              pipeline state: PLAN.md, ARCHITECTURE.md, TASKS.md, AUDIT.md
scripts/           one-off utilities
.claude/           context (QUICKREF, continue.md), roles, skills
```

## Domain Context and Constraints

- **This is a LIVE-MONEY trading system.** The bot places real XAUUSD orders
  through MT5. Never start/stop `main.py` or place/close orders as a side
  effect of development work — the user controls the live process.
- Iron rules live in `.claude/roles/role.md`. The load-bearing ones: do not
  change confidence thresholds / SL-TP defaults / anti-fade guards
  (`_run_gates`) without explicit user approval; never bypass DecisionMaker;
  edit prompt `.json` files, not `.md`.
- Token cost is a real constraint (bot pays per Claude call). Prefer
  display-only / computed-in-code features over new AI calls.

## Overrides of Global Rules (and why)

1. **Explain-before-acting comes first.** `.claude/CLAUDE.md` requires
   explaining any logic/architecture change BEFORE writing code. In pipeline
   terms: the architect's ARCHITECTURE.md must be shown to the user for
   approval before workers start. *Why:* live-money system — a wrong design
   executed quickly loses real money.
2. **continue.md logging is mandatory.** Every code edit / bug / fix must
   also be logged in `.claude/context/continue.md` (format defined in
   `.claude/CLAUDE.md`), in addition to TASKS.md status updates. *Why:* it is
   the cross-session memory of this project; docs/ tracks pipeline state,
   continue.md tracks history.
3. **Workers may not touch** `agents/` gate logic, money management, or
   `agents/prompts/*.json` unless the task explicitly whitelists that file
   AND the user approved the design. *Why:* iron rules above.
