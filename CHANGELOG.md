# Changelog

## v0.4.0 — News-First Decision Layer + Anti-fade Guards (2026-06-11)

> ที่มา: บอท SELL รัวสวนข่าว ceasefire (gold rally) จน port เสียหาย → ยกเครื่อง decision layer
> ให้ "ดูข่าว macro ก่อน → หา price action → วิเคราะห์ → เข้า order" และพิสูจน์ gate ด้วย replay 489 ไม้จริง

### เพิ่ม — Anti-fade Guards (`agents/decision_maker.py`)
- **Counter-spike guard** — ห้ามเข้าสวน fast move สด ≥ `COUNTER_SPIKE_PIPS` (500)
- **News-first block** — analyst bias conf ≥ 55 → hard-block เข้าทิศตรงข้ามข่าว
- **HTF-fade block** — ห้าม SELL ที่ D1/W1 SUPPORT / BUY ที่ RESISTANCE
- **Option C (news override)** — เข้าสวน H4 trend ได้เมื่อทิศตรงข่าว + spike ยืนยัน ≥ 500p หรือมี HTF zone หนุน
- `fast_move_pips` ใน chart_watcher (M15 3 แท่งล่าสุด, มีเครื่องหมาย) ป้อน guard

### เพิ่ม — Replay-proven Quality Gates
- **Confidence floor 62** (`MIN_TECH_CONF`) — replay พบ band 50-59 ขาดทุนสุทธิ
- **Asian floor 72** (`ASIAN_MIN_CONF`) — ก่อน 07:00 UTC
- ผล replay บนประวัติ: ตัดขาดทุน −4,292 แลกกำไรที่เสียไป +332
- NNLB mode ข้าม money-management ได้ แต่**ไม่ข้าม** quality gates + guards แล้ว

### เพิ่ม — Infrastructure
- **Capital floor** — equity < `MIN_AI_EQUITY` (150) → ไม่รัน AI pipeline เลย (`main.py`)
- **Close-reason registry** — MT5 ตีทุกการปิดของบอทเป็น MANUAL → บอทบันทึกเอง
  (`logs/close_reasons.json`: MOMENTUM_EXIT / ZONE_BREAK / CONFLICT_CLOSE) + reporter sync ใช้ registry ก่อน
- **Config centralization + live-reload** — gate knobs 13 ตัวรวมใน `config.py`,
  `reload_config()` อ่านใหม่ทุกต้น cycle → แก้ .env มีผลรอบถัดไปไม่ต้อง restart
- **Multi-provider prereq** — `agents/llm_models.py` (`model_for()` + `MODEL_<AGENT>` env),
  `_normalize_usage()` ใน accountant รองรับ usage shape ของ Anthropic / OpenAI-compatible / LangChain
- **ATR sanity clamp** — clamp ATR เข้า [0.4×, 2.5×] ของ median 20 แท่ง กัน SL เพี้ยน
- **Word-boundary keyword filter** — news_gatherer ใช้ regex `\b...\b` ("war" ไม่ match "forward")
- X_KEYWORDS defaults เพิ่ม: Iran, Israel, ceasefire, war, oil, crude, CPI, rate cut, Hormuz, CENTCOM
- `agents/prompts/macro_regime.md` — regime override ของ analyst (INVERT geopolitics→gold mapping ได้)
- Scripts: `diagnose_trades.py` (segment 489 ไม้), `smoke_test.py` (8 checks), `check_recent.py` (ไม้ 48h)

### แก้ไข
- `scripts/auto_deploy.ps1` — derive repo path จาก `$PSScriptRoot` แทน hardcode
- README.md ยกเครื่อง decision layer + ตาราง 13 knobs; `.env.example` เพิ่ม section gates
- gate 5 SIDEWAYS เงื่อนไขซ้ำซ้อนถูกตัด, gate 9 dead code ถูกลบ, momentum override floor = 62

---

## v0.3.0 — Multi-System Architecture (2026-05-04)

### เพิ่ม
- **Multi-system support** — รองรับหลาย trading system (XAUUSD, BTC) จาก codebase เดียว
- `agents/accountant.py` — เพิ่ม `get_summary_by_symbol(symbol)` สำหรับ filter cost ตาม symbol
- `dashboard/app.py` — `/api/data?system=xauusd|btcusd` อ่าน log file ตาม system
- `dashboard/app.py` — `/api/accounting?system=xauusd|btcusd|all` filter cost ตาม symbol
- `dashboard/templates/index.html` — ปุ่ม [XAUUSD] [BTC] ใน header, `switchSystem()` สลับ context
- Log file routing อัตโนมัติ: `XAUUSD → logs/trades.json`, อื่นๆ → `logs/{symbol}_trades.json`

### แก้ไข
- `agents/reporter.py` — เพิ่ม `"symbol"` field ใน trade entry ทุกประเภท
- `agents/reporter.py` — `_log_file()` derive path จาก `config.SYMBOL` แทน hardcode
- `config.py` — `MONEY_MANAGEMENT` ใช้ `os.getenv("KEY") or default` แทน `os.getenv("KEY", default)` ป้องกัน empty string crash

### แก้บัก
- `config.py` — crash เมื่อ env var ตั้งค่าเป็น empty string (เช่น `HEDGE_BUFFER_PIPS=`)
- `.env` — `SYMBOL=GOLD#` มี `#` ต่อท้ายทำให้ symbol ผิด

---

## v0.2.0 — PostgreSQL + Accounting Dashboard (2026-05-02)

### เพิ่ม
- **DB Layer** — `db/schema.sql`, `db/connection.py`, `db/writer.py`, `db/migrate.py`
  - ตาราง `trades`, `agent_usage`, `cycles` พร้อม indexes และ auto-updated_at trigger
- **Write-through** — `agents/accountant.py` และ `agents/reporter.py` บันทึกทั้ง JSON + PostgreSQL
- **Dashboard tab: Accounting** — summary cards (today/all-time cost), daily cost bar chart (14 วัน, Chart.js), agent breakdown + cache hit progress bars, model badges
- `docker-compose.yml` — เพิ่ม `postgres:16-alpine` service + named volume + health check
- `/api/accounting` endpoint ใน dashboard

### รองรับ Migration ไป Supabase
- เปลี่ยนแค่ `DATABASE_URL` ใน `.env` — schema เหมือนกันทุกอย่าง

---

## v0.1.0 — Phase 1 Accounting (2026-04-30)

### เพิ่ม
- `agents/accountant.py` — บันทึก token usage + cost (USD) ต่อ agent ต่อ cycle
- `logs/accounting.json` — เก็บ summary, per-agent aggregate, daily breakdown, cycle history
- Support Claude Haiku 4.5 และ Sonnet 4.6 pricing
- Cache hit rate tracking per agent
- `record_cycle(symbol, agent_usages, ticket, latencies_ms)` เรียกจาก `main.py` ทุก cycle

---

## v0.0.3 — Trading Logic Enhancements (2026-04-29)

### เพิ่ม
- **Breakeven management** — ขยับ SL หน้าทุนอัตโนมัติเมื่อกำไรถึง 1000 pips
- **Dynamic TP extension** — ขยับ TP ออกเมื่อ momentum แรงและราคาใกล้ TP (max 2 ครั้ง)
- **Post-event TP** — ตั้ง TP ภายหลังสำหรับ order ที่เปิดแบบ No-TP
- **Hedge buffer** — ป้องกันการเปิด order สวนทางเมื่อมี losing position เกิน buffer pips
- **Protected slots** — position ที่ SL อยู่หน้าทุนแล้วได้ extra slot
- **Auto-pending orders** — วาง limit orders อัตโนมัติที่ key S/R zones
- **Weekly calendar pending** — วาง orders ตาม economic calendar ทุกวันจันทร์
- **Pending manager** — ติดตาม fill / expire / cancel pending orders
- **Manual order detection** — ตรวจ order ที่เปิดเองใน MT5 และบันทึก context
- `scan_entry_setups()` — 9 setup types: SR_ZONE, EMA200_TOUCH, BB_LOWER/UPPER, EMA_PULLBACK, EMA_CROSS, MACD_CROSS, RSI_EXTREME, EMA50_PULLBACK, MOMENTUM_BREAKOUT
- Fibonacci retracement confluence (H4 + H1)
- Momentum analysis per timeframe (H4, H1, M15)

### แก้ไข
- SL คำนวณจาก wick แท่งก่อนหน้า M15 แทน default pips
- Losing streak protection — เพิ่ม confidence threshold เมื่อแพ้ติดกัน

---

## v0.0.2 — Dashboard + Docker (2026-04-27)

### เพิ่ม
- `dashboard/app.py` — Flask dashboard (port 5050)
- Trade log viewer พร้อม filter source/direction/status/result
- Portfolio bar — Balance, Equity, P&L แปลงเป็น THB อัตโนมัติ
- Equity curve chart (Chart.js)
- Settings panel — แก้ trading config ผ่าน UI ได้ (write to .env + PM2 restart)
- Economic calendar tab — ดึงจาก ForexFactory
- MT5 sync — อัปเดต trade status/PnL จาก MT5 โดยตรง
- `docker-compose.yml` — รัน dashboard ใน Docker
- `Dockerfile` + `Dockerfile.windows`

---

## v0.0.1 — Initial Release (2026-04-26)

### เพิ่ม
- Agent pipeline: ChartWatcher → MarketAdvisor → NewsGatherer → Analyst → DecisionMaker → Reporter
- `connectors/mt5_connector.py` — connect, open/close orders, get positions, history
- `connectors/price_feed.py` — OHLCV, tick price
- `connectors/twitter_client.py` — ดึง tweets จาก X/Twitter
- `connectors/web_news.py` — ForexFactory calendar scraper
- Technical indicators: EMA(20/50/200), RSI, MACD, Bollinger Bands, ATR
- S/R detection: swing highs/lows, PDH/PDL, round numbers
- Candle pattern detection: Hammer, Shooting Star, Engulfing, Doji, Strong candle
- `config.py` — ทุก parameter อ่านจาก `.env`
- PM2 process management (`ecosystem.config.js`)
- `logs/trades.json` — บันทึก trade history พร้อม context
- `utils/display.py` — Rich terminal UI
- `utils/market_clock.py` — ตรวจตลาดปิด + adaptive interval
