import json
import os
import subprocess
import sys
from datetime import datetime, date, timedelta
from flask import Flask, render_template, jsonify, make_response, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False
    class _MT5Stub:
        """Stub สำหรับ non-Windows (Docker/Linux) — ทุก call คืน None/empty"""
        def __getattr__(self, _):
            return lambda *a, **kw: None
    mt5 = _MT5Stub()

import urllib.request
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL

app = Flask(__name__)

_BASE = os.path.dirname(__file__)

# ── Opt-in HTTP Basic Auth (defense-in-depth เสริม Tailscale) ─────────────────
# ตั้ง DASHBOARD_USER + DASHBOARD_PASS ใน .env เพื่อเปิด auth ทุก route.
# ไม่ตั้ง = ปิด (โหมด Tailscale-only เดิม) — กันล็อกตัวเองออกตอน rollout.
import secrets as _secrets


@app.before_request
def _require_auth():
    user = os.getenv("DASHBOARD_USER")
    pw   = os.getenv("DASHBOARD_PASS")
    if not user or not pw:
        return  # auth disabled
    a = request.authorization
    if not a or a.username != user or not _secrets.compare_digest(a.password or "", pw):
        return make_response("Authentication required", 401,
                             {"WWW-Authenticate": 'Basic realm="XAUUSD dashboard"'})

# ── Simple in-process cache to avoid hammering Supabase on every 10s poll ──
import time as _time_mod
import threading as _threading
_data_cache: dict = {}       # key -> (timestamp, payload)
_cache_refreshing: set = set()  # keys currently being refreshed in background
_DATA_CACHE_TTL = 20         # seconds

def _cached(key: str, fn, ttl: int = _DATA_CACHE_TTL):
    """Stale-while-revalidate cache.

    - Fresh entry  → return it.
    - Stale entry  → return the stale value *immediately* and refresh in a
      background thread (so a slow fn never blocks the request).
    - No entry yet → compute synchronously (only happens once per key; the
      startup warm-up pays this cost before the frontend ever polls).

    NOTE: the timestamp is stored *after* fn() finishes, so a fn that takes
    longer than ttl does not produce an already-expired entry.
    """
    now = _time_mod.time()
    entry = _data_cache.get(key)
    if entry is not None:
        ts, val = entry
        if now - ts < ttl:
            return val
        # stale → kick off a single background refresh, serve stale meanwhile
        if key not in _cache_refreshing:
            _cache_refreshing.add(key)
            def _refresh():
                try:
                    _data_cache[key] = (_time_mod.time(), fn())
                except Exception:
                    pass
                finally:
                    _cache_refreshing.discard(key)
            _threading.Thread(target=_refresh, daemon=True).start()
        return val
    # cold: compute synchronously
    val = fn()
    _data_cache[key] = (_time_mod.time(), val)
    return val
_SYSTEM_LOGS = {
    "xauusd": os.path.join(_BASE, "../logs/trades.json"),
    "btcusd": os.path.join(_BASE, "../logs/btcusd_trades.json"),
}

def _log_file(system: str = "xauusd") -> str:
    return _SYSTEM_LOGS.get(system.lower(), _SYSTEM_LOGS["xauusd"])

LOG_FILE     = _SYSTEM_LOGS["xauusd"]   # backward-compat alias
SYSTEM_MAGIC = 20260429                 # ต้องตรงกับ mt5_connector.py

# ── §3.2 Atomic JSON I/O helpers (local — no shared module per §5 #4) ─────────
_LOG_DECODE_ERROR = object()  # sentinel: read failed due to JSONDecodeError/ValueError
_LOG_EMPTY = {"trades": [], "summary": {"total": 0, "win": 0, "loss": 0, "total_pnl": 0.0}}


def _read_log_json(path: str):
    """Read trades JSON file safely.
    Returns parsed dict on success, _LOG_DECODE_ERROR on JSONDecodeError/ValueError,
    _LOG_EMPTY on any other read error (e.g. FileNotFoundError)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return _LOG_DECODE_ERROR
    except Exception:
        return _LOG_EMPTY


def _write_log_json(path: str, data: dict) -> None:
    """Atomic write: write to .tmp then os.replace (atomic on NTFS, same-dir)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ── §3.3 Accounting TTL cache (in-memory, keyed (system, account)) ─────────────
_acct_cache: dict = {}  # (system, account) → (timestamp, payload_dict)
ENV_FILE     = os.path.join(_BASE, "../.env")

# ── CONFIG SPEC: single source of truth (fix 07-02) ──────────────────────────
# เดิมมี 3 ลิสต์แยกกัน (_EDITABLE_KEYS / GET defaults / UI fields) ไม่ sync:
# UI มีช่อง HTF_BE_* แต่ POST โดน filter ทิ้งเงียบ + GET defaults ไม่ตรง config.py
# (เช่น MIN_RR 1.5 vs จริง 2.0) → user กด Save = เขียนค่าปลอมทับของจริง.
# spec เดียว: key → default string ที่ "ตรงกับ config.py" — GET/editable สร้างจากตัวนี้
# ⚠️ แก้ default ใน config.py ต้องแก้ที่นี่ด้วย (และ UI ใน index.html ถ้าเพิ่ม key)
_CONFIG_SPEC: dict[str, str] = {
    # ── Core / Money management ──
    "SYMBOL": "XAUUSD", "START_BALANCE": "5000",
    "LOT_MODE": "auto", "FIXED_LOT": "0.01", "MIN_LOT": "0.01", "MAX_LOT": "0.01",
    "RISK_PER_TRADE": "0.50", "MAX_DAILY_LOSS": "1.00", "MAX_OPEN_TRADES": "4",
    "DEFAULT_SL_PIPS": "2000", "DEFAULT_TP_PIPS": "5000", "MIN_RR_RATIO": "2.0",
    "HEDGE_BUFFER_PIPS": "2500",
    "MAX_PENDING_BUY": "4", "MAX_PENDING_SELL": "4", "PENDING_EXPIRY_HOURS": "24",
    "MAX_LOSING_STREAK": "5", "STREAK_MIN_CONFIDENCE": "62",
    "PORTFOLIO_PROTECTION": "true", "STREAK_PROTECTION": "true", "DYNAMIC_TP": "true",
    "LESSON_LEARNING": "true", "DRY_RUN": "false",
    # ── Breakeven / Trailing ──
    "BE_TRIGGER_R": "1.2", "BE_BUFFER_PIPS": "300", "BE_CONFIRM_CYCLES": "2",
    "HTF_BE_TRIGGER_R": "2.0", "HTF_BE_BUFFER_PIPS": "1000",
    "BE_MAX_TRIGGER_PIPS": "1500",
    "TRAILING_STOP": "false", "TRAILING_ATR_TF": "D1", "TRAILING_ATR_MULT": "1.5",
    "TRAILING_MIN_PROFIT_R": "1.5", "TRAILING_LOOKBACK": "6",
    # ── Protection (v0.4) ──
    "MAX_TRADES_PER_DAY": "6", "AUTO_SL_PROTECT": "true",
    "AUTO_SL_PIPS": "0", "SL_MIN_GAP_PIPS": "800", "MOMENTUM_RIDE": "true",
    # ── Decision gates & anti-fade guards (live-reload ทุกตัว) ──
    "MIN_TECH_CONF": "62", "ASIAN_MIN_CONF": "72", "MIN_AI_EQUITY": "150",
    "COUNTER_SPIKE_PIPS": "500",
    "NEWS_FIRST": "true", "NEWS_BIAS_MIN_CONF": "55",
    "HTF_FADE_BLOCK": "true", "HTF_DIRECTION_BLOCK": "true",
    "NEWS_OVERRIDE_TREND": "true", "NEWS_CONFIRM_PIPS": "500",
    "NEWS_OVERRIDE_MIN_CONF": "50", "HTF_REVERSAL_MIN_CONF": "70",
    "EMA_PULLBACK_BLOCK": "true",
    "TREND_CONT_CONF": "65", "TREND_CONT_MAX_DIST_PCT": "0.3", "NNLB_FASTPATH": "true",
    # ── NEWS_GATE (News Impact score → conf floor; flag default OFF, ยังไม่ validate) ──
    "NEWS_GATE": "false", "NEWS_GATE_OPPOSE": "40", "NEWS_OPPOSE_PENALTY": "8",
    "NEWS_AGREE_RELAX": "5", "NEWS_GATE_HARD_FLOOR": "58", "NEWS_GATE_MIN_N": "3",
    "NEWS_GATE_MAX_AGE_MIN": "60",
    # ── NNLB ──
    "NNLB_MODE": "false", "NNLB_BASE_EQUITY": "100",
    "NNLB_EQUITY_PER_LOT": "100", "NNLB_MAX_LOSS_PCT": "25",
    # ── News/Twitter — default ว่าง = ใช้ default ในโค้ด (ค่าใน .env จะ OVERRIDE
    #    ทั้งชุด ไม่ merge! default ปลอมตัวเดิมทำ keyword geopolitics/CPI หายเมื่อกด Save) ──
    "X_ACCOUNTS_TO_FOLLOW": "", "X_KEYWORDS": "",
}
# Keys ที่อนุญาตให้แก้ไขผ่าน dashboard (ไม่รวม credentials) — จาก spec เสมอ
_EDITABLE_KEYS = set(_CONFIG_SPEC)

_usd_thb_cache = {"rate": 33.0, "fetched_at": None}
_login_cache = {"login": None, "fetched_at": None}


def _db_sync_trade(trade: dict) -> None:
    """Sync trade dict to DB (best-effort, silent on failure)"""
    try:
        from db.writer import write_trade
        write_trade(trade)
    except Exception:
        pass


def get_usd_thb() -> float:
    """ดึงอัตราแลกเปลี่ยน USD/THB จาก Yahoo Finance และ cache ไว้ 5 นาที"""
    from datetime import timedelta
    now = datetime.now()
    if _usd_thb_cache["fetched_at"] and (now - _usd_thb_cache["fetched_at"]) < timedelta(minutes=5):
        return _usd_thb_cache["rate"]
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/USDTHB=X?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read())
        rate = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        _usd_thb_cache["rate"] = round(rate, 4)
        _usd_thb_cache["fetched_at"] = now
    except Exception:
        pass
    return _usd_thb_cache["rate"]


def _sync_from_mt5(data: dict) -> bool:
    """
    Pull positions + deal history จาก MT5 แล้ว merge เข้า trades.json (ต้อง initialize MT5 ก่อน)
    - Existing entry: อัปเดต status / pnl / sl / tp / lot
    - New entry ไม่มีใน log: เพิ่มเป็น MANUAL (ไม่มี AI context)
    คืน True ถ้ามีการเปลี่ยนแปลง
    """
    # สร้าง ticket_map โดย prefer SYSTEM over MANUAL เมื่อ ticket ซ้ำกัน
    ticket_map: dict[str, dict] = {}
    for t in data.get("trades", []):
        tk = str(t.get("ticket", ""))
        if not tk:
            continue
        existing = ticket_map.get(tk)
        if existing is None:
            ticket_map[tk] = t
        elif t.get("source") == "SYSTEM" and existing.get("source") != "SYSTEM":
            # SYSTEM entry มาทีหลัง → ให้ทับ MANUAL ที่ซ้ำกัน
            ticket_map[tk] = t
    changed = False

    # ── 1. Open positions ──────────────────────────────────────────
    open_pos = mt5.positions_get(symbol=SYMBOL) or []
    open_ids = {str(p.ticket) for p in open_pos}

    for pos in open_pos:
        tk = str(pos.ticket)
        sl = pos.sl  if pos.sl  != 0 else None
        tp = pos.tp  if pos.tp  != 0 else None

        if tk in ticket_map:
            t = ticket_map[tk]
            floating_pnl = round(pos.profit, 2)
            entry_price  = t.get("entry_price") or pos.price_open
            if (t.get("status") != "OPEN" or t.get("sl") != sl
                    or t.get("tp") != tp or t.get("lot") != pos.volume
                    or t.get("pnl") != floating_pnl
                    or not t.get("entry_price")):
                t.update({"status": "OPEN", "pnl": floating_pnl,
                          "sl": sl, "tp": tp, "lot": pos.volume,
                          "entry_price": entry_price})
                changed = True
        else:
            is_system = pos.magic == SYSTEM_MAGIC
            if is_system:
                # SYSTEM trade ที่ยังไม่อยู่ใน log — main.py จัดการเอง
                # ไม่เพิ่มที่นี่เพื่อป้องกัน race condition ทับข้อมูล AI
                continue
            direction = "BUY" if pos.type == 0 else "SELL"
            entry = {
                "source": "MANUAL", "timestamp": datetime.fromtimestamp(pos.time).isoformat(),
                "ticket": pos.ticket, "direction": direction,
                "lot": pos.volume, "entry_price": pos.price_open,
                "sl": sl, "tp": tp,
                "technical_signal": direction, "technical_confidence": None,
                "trend": None, "sr_zone": None, "sr_strength": None,
                "pa_action": "NONE", "pa_zone": "—", "pa_level": None,
                "pa_patterns": [], "entry_type": "MANUAL", "sentiment": None,
                "manual_analysis": "Detected from MT5",
                "manual_reason": pos.comment or "",
                "status": "OPEN", "pnl": None,
            }
            data["trades"].append(entry)
            ticket_map[tk] = entry
            changed = True

    # ── 2. Closed positions from deal history ──────────────────────
    from_dt = datetime.now() - timedelta(days=7)
    all_deals = mt5.history_deals_get(from_dt, datetime.now()) or []

    deals_by_pos: dict[int, list] = {}
    for d in all_deals:
        if d.symbol != SYMBOL:
            continue
        pid = d.position_id
        if pid not in deals_by_pos:
            deals_by_pos[pid] = []
        deals_by_pos[pid].append(d)

    for pid, pos_deals in deals_by_pos.items():
        tk = str(pid)
        if tk in open_ids:
            continue  # ยังเปิดอยู่ จัดการแล้วข้างบน

        out_deal = next((d for d in pos_deals if d.entry == 1), None)
        if out_deal is None:
            continue  # ยังไม่มี closing deal

        pnl        = round(sum(d.profit + d.swap + d.commission for d in pos_deals), 2)
        close_time = datetime.fromtimestamp(out_deal.time).isoformat()

        if tk in ticket_map:
            t = ticket_map[tk]
            if (t.get("status") != "CLOSED" or t.get("pnl") != pnl):
                t["status"]     = "CLOSED"
                t["pnl"]        = pnl
                t["close_time"] = close_time
                changed         = True
                _db_sync_trade(t)
        else:
            # เพิ่ม closed trade ใหม่ที่ไม่เคยเห็น
            entry_deal = next((d for d in pos_deals if d.entry == 0), None)
            if entry_deal is None:
                continue
            is_system = entry_deal.magic == SYSTEM_MAGIC
            if is_system:
                # SYSTEM trade ที่ปิดแล้วแต่ไม่อยู่ใน log — main.py จัดการเอง ไม่ทับข้อมูล AI
                continue
            direction = "BUY" if entry_deal.type == 0 else "SELL"
            entry = {
                "source": "MANUAL", "timestamp": datetime.fromtimestamp(entry_deal.time).isoformat(),
                "close_time": close_time,
                "ticket": pid, "direction": direction,
                "lot": entry_deal.volume, "entry_price": entry_deal.price,
                "sl": None, "tp": None,
                "technical_signal": direction, "technical_confidence": None,
                "trend": None, "sr_zone": None, "sr_strength": None,
                "pa_action": "NONE", "pa_zone": "—", "pa_level": None,
                "pa_patterns": [], "entry_type": "MANUAL", "sentiment": None,
                "manual_analysis": "Detected from MT5 history",
                "manual_reason": entry_deal.comment or "",
                "status": "CLOSED", "pnl": pnl,
            }
            data["trades"].append(entry)
            ticket_map[tk] = entry
            changed = True
            _db_sync_trade(entry)

    if not changed:
        return False

    # อัปเดต summary
    closed = [t for t in data["trades"] if t.get("status") == "CLOSED"]
    data["summary"] = {
        "total":     len(closed),
        "win":       sum(1 for t in closed if (t.get("pnl") or 0) > 0),
        "loss":      sum(1 for t in closed if (t.get("pnl") or 0) < 0),
        "total_pnl": round(sum(t.get("pnl") or 0 for t in closed), 2),
    }
    # §3.2 guard: pre-read existing file — if it's corrupt (decode error),
    # do NOT overwrite (safety net; keeps potentially-recoverable data intact).
    existing = _read_log_json(LOG_FILE)
    if existing is _LOG_DECODE_ERROR:
        return True  # changes detected but not persisted this round
    try:
        _write_log_json(LOG_FILE, data)
    except Exception:
        pass
    return True


def get_mt5_account(data_to_sync: dict | None = None) -> dict:
    """ดึงข้อมูลบัญชีจาก MT5 — ไม่เรียก shutdown() เพื่อไม่ตัด connection ของ main.py"""
    if not _MT5_AVAILABLE:
        return {}
    try:
        already_init = mt5.terminal_info() is not None
        if not already_init:
            if not mt5.initialize():
                return {}
            if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                return {}
        info = mt5.account_info()
        if info is None:
            return {}
        result = {
            "balance":     info.balance,
            "equity":      info.equity,
            "margin":      info.margin,
            "free_margin": info.margin_free,
            "profit":      info.profit,
            "currency":    info.currency,
        }
        if data_to_sync is not None:
            _sync_from_mt5(data_to_sync)
        if not already_init:
            mt5.shutdown()
        return result
    except Exception:
        return {}


def _get_actual_mt5_login() -> int | None:
    """ดึง account login ที่กำลัง connect อยู่จริงจาก mt5.account_info()
    ถ้า MT5 ยังไม่ init ให้ init/shutdown เอง — fallback เป็น MT5_LOGIN จาก .env
    Cache ผลไว้ 5 นาที — login ไม่เปลี่ยนระหว่าง session และ MT5 init ช้า (~7s)"""
    now = datetime.now()
    if _login_cache["fetched_at"] and (now - _login_cache["fetched_at"]) < timedelta(minutes=5):
        return _login_cache["login"]
    if not _MT5_AVAILABLE:
        _login_cache.update({"login": MT5_LOGIN or None, "fetched_at": now})
        return MT5_LOGIN or None
    result = MT5_LOGIN or None
    try:
        already_init = mt5.terminal_info() is not None
        if not already_init:
            if not mt5.initialize():
                _login_cache.update({"login": result, "fetched_at": now})
                return result
            if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                mt5.shutdown()
                _login_cache.update({"login": result, "fetched_at": now})
                return result
        info = mt5.account_info()
        if not already_init:
            mt5.shutdown()
        result = int(info.login) if info else (MT5_LOGIN or None)
    except Exception:
        pass
    _login_cache.update({"login": result, "fetched_at": now})
    return result


def load_trades(system: str = "xauusd", account_login: int | None = None) -> dict:
    _empty = {"trades": [], "summary": {"total": 0, "win": 0, "loss": 0, "total_pnl": 0.0}}
    try:
        from db.reader import get_trades
        rows = get_trades(system, account_login=account_login) or []
        closed = [t for t in rows if t.get("status") == "CLOSED"]
        summary = {
            "total":     len(closed),
            "win":       sum(1 for t in closed if (t.get("pnl") or 0) > 0),
            "loss":      sum(1 for t in closed if (t.get("pnl") or 0) < 0),
            "total_pnl": round(sum(t.get("pnl") or 0 for t in closed), 2),
        }
        return {"trades": rows, "summary": summary}
    except Exception:
        return _empty


def calc_stats(trades: list) -> dict:
    closed    = [t for t in trades if t.get("status") == "CLOSED"]
    today_str = date.today().isoformat()

    # today = trades ที่ปิดวันนี้ (ใช้ close_time ถ้ามี ไม่งั้น fallback timestamp)
    def _closed_date(t):
        return (t.get("close_time") or t.get("timestamp") or "")[:10]
    today_closed = [t for t in closed if _closed_date(t) == today_str]

    wins   = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) < 0]

    total_pnl = sum(t.get("pnl") or 0 for t in closed)
    today_pnl = sum(t.get("pnl") or 0 for t in today_closed)
    win_rate  = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_win   = round(sum(t.get("pnl", 0) for t in wins)   / len(wins),   2) if wins   else 0
    avg_loss  = round(sum(t.get("pnl", 0) for t in losses) / len(losses), 2) if losses else 0
    profit_factor = round(
        abs(sum(t.get("pnl", 0) for t in wins)) / abs(sum(t.get("pnl", 0) for t in losses)), 2
    ) if losses and sum(t.get("pnl", 0) for t in losses) != 0 else 0

    # Equity curve must be chronological (oldest → newest). The DB returns
    # trades newest-first, so iterating as-is plotted the cumulative curve
    # backwards in time (gains looked like losses and vice versa). Sort by
    # realized close time (fallback to open time) ascending.
    chrono = sorted(closed, key=lambda x: (x.get("close_time") or x.get("timestamp") or ""))
    equity_curve = []
    running = 0
    for t in chrono:
        running += t.get("pnl") or 0
        ts = t.get("close_time") or t.get("timestamp") or ""
        equity_curve.append({"time": ts[:16], "equity": round(running, 2)})

    # Current losing streak = most recent consecutive losses → walk newest first
    # ใช้ close-date (_closed_date) สม่ำเสมอกับ today_pnl ด้านบน (ไม้คร่อมวันนับตามวันที่ปิด)
    today_closed  = [t for t in chrono if _closed_date(t) == today_str]
    losing_streak = 0
    for t in reversed(today_closed):
        if (t.get("pnl") or 0) < 0:
            losing_streak += 1
        else:
            break

    # ── Source breakdown ──────────────────────────────────────────
    sys_trades    = [t for t in closed if t.get("source") == "SYSTEM"]
    manual_trades = [t for t in closed if t.get("source") == "MANUAL"]
    sys_wins      = sum(1 for t in sys_trades    if (t.get("pnl") or 0) > 0)
    manual_wins   = sum(1 for t in manual_trades if (t.get("pnl") or 0) > 0)

    # ── Entry type breakdown (system trades only) ─────────────────
    entry_type_stats: dict[str, dict] = {}
    for t in sys_trades:
        et = t.get("entry_type") or "UNKNOWN"
        if et not in entry_type_stats:
            entry_type_stats[et] = {"count": 0, "wins": 0, "pnl": 0.0}
        entry_type_stats[et]["count"] += 1
        if (t.get("pnl") or 0) > 0:
            entry_type_stats[et]["wins"] += 1
        entry_type_stats[et]["pnl"] = round(entry_type_stats[et]["pnl"] + (t.get("pnl") or 0), 2)

    return {
        "total":          len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       win_rate,
        "total_pnl":      round(total_pnl, 2),
        "today_pnl":      round(today_pnl, 2),
        "today_trades":   len(today_closed),
        "avg_win":        avg_win,
        "avg_loss":       avg_loss,
        "profit_factor":  profit_factor,
        "losing_streak":  losing_streak,
        "equity_curve":   equity_curve,
        # new
        "system_count":   len(sys_trades),
        "manual_count":   len(manual_trades),
        "system_winrate": round(sys_wins   / len(sys_trades)    * 100, 1) if sys_trades    else 0,
        "manual_winrate": round(manual_wins/ len(manual_trades) * 100, 1) if manual_trades else 0,
        "entry_type_stats": entry_type_stats,
    }


def _read_env_file() -> dict[str, str]:
    """อ่าน .env file โดยตรง → dict  (strip quotes, skip comments)"""
    result: dict[str, str] = {}
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, val = stripped.partition("=")
                val = val.strip()
                # strip inline comment (whitespace + #) like python-dotenv does,
                # but preserve values such as SYMBOL=GOLD# (# with no leading space)
                if not (val.startswith('"') or val.startswith("'")):
                    for sep in (" #", "\t#"):
                        ci = val.find(sep)
                        if ci != -1:
                            val = val[:ci].rstrip()
                result[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return result


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """คืน trading config ปัจจุบัน — อ่านจาก .env file โดยตรง (ไม่ใช่ runtime env vars)
    fallback = _CONFIG_SPEC (ตรง config.py) — ไม่มีลิสต์ default แยกอีกแล้ว"""
    env = _read_env_file()
    return jsonify({k: env.get(k, v) for k, v in _CONFIG_SPEC.items()})


@app.route("/api/config", methods=["POST"])
def api_set_config():
    """รับ JSON → อัปเดต .env เฉพาะ trading keys → เขียนคืน
    `_restart: true` = สั่ง pm2 restart ด้วย (default ไม่ restart — knobs ทั้งหมดใน
    _CONFIG_SPEC live-reload ผ่าน reload_config() ทุกต้น cycle อยู่แล้ว; restart ฟรีๆ
    จะล้าง in-memory state เช่น BE confirm counters / partial state โดยไม่จำเป็น)"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "no JSON body"}), 400

    want_restart = str(data.pop("_restart", "")).lower() in ("1", "true", "yes")
    updates = {k.upper(): str(v) for k, v in data.items() if k.upper() in _EDITABLE_KEYS}
    if not updates:
        return jsonify({"error": "no editable keys found"}), 400

    # อ่าน .env ปัจจุบัน (ถ้ามี)
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    # อัปเดต keys ที่มีอยู่แล้ว
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip().upper()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            new_lines.append(line)

    # เพิ่ม keys ใหม่ที่ยังไม่มีใน file
    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}\n")

    try:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # ── PM2 restart เฉพาะเมื่อขอ (_restart=true) ─────────────────────
    if want_restart:
        pm2_ok, pm2_msg = _pm2_restart()
    else:
        pm2_ok, pm2_msg = True, "no restart — live-reload ภายใน 1 cycle"
    return jsonify({"ok": True, "updated": sorted(updates.keys()),
                    "restarted": want_restart, "pm2_ok": pm2_ok, "pm2_msg": pm2_msg})


def _pm2_restart() -> tuple[bool, str]:
    """เรียก pm2 restart ตาม PM2_APP_NAME ใน .env (default: 'main')"""
    app_name = _read_env_file().get("PM2_APP_NAME", os.getenv("PM2_APP_NAME", "main"))
    try:
        result = subprocess.run(
            f"pm2 restart {app_name}",
            shell=True, capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True, f"pm2 restart {app_name} — OK"
        err = (result.stderr or result.stdout).strip().splitlines()[0]
        return False, err or f"exit code {result.returncode}"
    except FileNotFoundError:
        return False, "pm2 not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "pm2 timeout"
    except Exception as e:
        return False, str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    system  = request.args.get("system", "xauusd").lower()
    account = request.args.get("account", "own").lower()
    if account == "all":
        login = None   # ไม่กรอง → เห็นทุก account
    else:
        login = _get_actual_mt5_login() if system == "xauusd" else None
    cache_key = f"trades:{system}:{login}"
    data    = _cached(cache_key, lambda: load_trades(system, account_login=login), ttl=15)
    usd_thb = get_usd_thb()
    # MT5 account + 7-day sync is the slow part — served stale-while-revalidate
    # (background refresh) so the 10s frontend poll never blocks on a fresh sync.
    account = _cached(
        f"mt5acct:{system}",
        lambda: get_mt5_account(data_to_sync=data),
        ttl=30,
    ) if system == "xauusd" else {}
    trades  = data.get("trades", [])
    stats   = calc_stats(trades)

    if account:
        currency = account.get("currency", "USD")
        if currency == "THB":
            account["balance_thb"]     = account["balance"]
            account["equity_thb"]      = account["equity"]
            account["profit_thb"]      = account.get("profit", 0)
            account["free_margin_thb"] = account.get("free_margin", 0)
        else:
            account["balance_thb"]     = round(account["balance"]            * usd_thb, 2)
            account["equity_thb"]      = round(account["equity"]             * usd_thb, 2)
            account["profit_thb"]      = round(account.get("profit", 0)      * usd_thb, 2)
            account["free_margin_thb"] = round(account.get("free_margin", 0) * usd_thb, 2)

    resp = make_response(jsonify({
        "stats":   stats,
        "trades":  list(reversed(trades)),
        "account": account,
        "usd_thb": usd_thb,
    }))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


def _compute_accounting(system: str, login) -> dict:
    """Compute accounting payload — called at most once per TTL (§3.3).
    Response shape frozen: {ok, system, source, summary, agents, today, daily}."""
    try:
        from db.reader import get_accounting
        data = get_accounting(None if system == "all" else system, account_login=login)
        if data is not None:
            for info in data.get("agents", {}).values():
                total_in = (info.get("total_input_tokens", 0)
                          + info.get("total_cache_read_tokens", 0)
                          + info.get("total_cache_write_tokens", 0))
                cr = info.get("total_cache_read_tokens", 0)
                info["avg_cache_hit_rate"] = round(cr / total_in * 100, 1) if total_in > 0 else 0.0
            return {**data, "ok": True, "system": system, "source": "db"}
    except Exception:
        pass
    try:
        from agents.accountant import get_summary, get_summary_by_symbol
        data = get_summary_by_symbol(system.upper()) if system != "all" else get_summary()
        for info in data.get("agents", {}).values():
            total_in = (info.get("total_input_tokens", 0)
                      + info.get("total_cache_read_tokens", 0)
                      + info.get("total_cache_write_tokens", 0))
            cr = info.get("total_cache_read_tokens", 0)
            info["avg_cache_hit_rate"] = round(cr / total_in * 100, 1) if total_in > 0 else 0.0
        return {**data, "ok": True, "system": system, "source": "json"}
    except Exception as e:
        return {"ok": False, "error": str(e), "system": system,
                "summary": {}, "agents": {}, "today": {}, "daily": {}}


@app.route("/api/accounting")
def api_accounting():
    """ค่าใช้จ่าย AI — รองรับ ?system=xauusd|btcusd|all (default=all) และ ?account=all|own
    §3.3: in-memory TTL cache keyed (system, account); response shape unchanged."""
    system  = request.args.get("system", "all").lower()
    account = request.args.get("account", "all").lower()
    login   = None if account == "all" else _get_actual_mt5_login()
    ttl     = int(os.getenv("ACCOUNTING_CACHE_TTL_SEC") or 60)
    now     = _time_mod.time()
    cache_key = (system, account)
    entry = _acct_cache.get(cache_key)
    if entry is not None:
        ts, payload = entry
        if now - ts < ttl:
            return jsonify(payload)
    payload = _compute_accounting(system, login)
    _acct_cache[cache_key] = (now, payload)
    return jsonify(payload)


@app.route("/api/monitor")
def api_monitor():
    """Bot status + pending orders for Monitor tab."""
    # ── bot_status.json ───────────────────────────────────────────
    status_file = os.path.join(_BASE, "../logs/bot_status.json")
    bot_status: dict = {}
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            bot_status = json.load(f)
    except Exception:
        pass

    # ── MT5 pending orders ────────────────────────────────────────
    pending: list[dict] = []
    if _MT5_AVAILABLE:
        try:
            already_init = mt5.terminal_info() is not None
            if not already_init:
                mt5.initialize()
                mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
            orders = mt5.orders_get(symbol=SYMBOL) or []
            _type_map = {2: "BUY_LIMIT", 3: "SELL_LIMIT", 4: "BUY_STOP", 5: "SELL_STOP"}
            for o in orders:
                comment = o.comment or ""
                if comment.startswith("SL-RE"):   tag = "SL-RE"
                elif comment.startswith("RNG-"):   tag = "RNG"
                elif comment.startswith("WK-"):    tag = "WK"
                else:                              tag = "AP"
                pending.append({
                    "ticket":  o.ticket,
                    "type":    _type_map.get(o.type, str(o.type)),
                    "price":   o.price_open,
                    "sl":      o.sl   if o.sl   != 0 else None,
                    "tp":      o.tp   if o.tp   != 0 else None,
                    "comment": comment,
                    "tag":     tag,
                    "expiry":  (datetime.fromtimestamp(o.time_expiration).isoformat()
                                if o.time_expiration else None),
                })
            if not already_init:
                mt5.shutdown()
        except Exception:
            pass

    grouped: dict[str, list] = {}
    for p in pending:
        grouped.setdefault(p["tag"], []).append(p)

    return jsonify({
        "ok":             True,
        "bot_status":     bot_status,
        "pending_orders": pending,
        "pending_grouped": grouped,
    })


def _tsmom_vs_bh(years=None):
    """เทียบ TSMOM (deployed long-short ensemble) vs Buy&Hold ทอง — apples-to-apples (vol-target+cost เท่ากัน).
    ตอบคำถาม audit: TSMOM มี alpha เหนือทองไหม หรือแค่ beta. years=None=ทั้งหมด, 5/10=ช่วงล่าสุด. cache 1ชม."""
    try:
        import numpy as np
        sys.path.insert(0, os.path.join(_BASE, "..", "scripts"))
        import tsmom_develop as TD
        with open(os.path.join(_BASE, "..", "data", "xau_d1.json")) as _f:
            close = np.array(json.load(_f), dtype=float)[:, 4]
        if years:                                                           # ช่วงล่าสุด + buffer สำหรับ lookback L=252
            close = close[-(int(years * 252) + 300):]
        srets = [TD.backtest(close, L, "ls")[0] for L in (63, 126, 252)]     # ensemble ที่ deploy
        mn = min(len(s) for s in srets)
        ens = np.mean([s[-mn:] for s in srets], axis=0)
        bh = TD.backtest(close, 126, "bh")[0][-mn:]                          # buy&hold vol-targeted (benchmark)
        mt, mb = TD._metrics(ens), TD._metrics(bh)
        if not mt or not mb:
            return None
        eq_ts = np.cumprod(1 + ens); eq_bh = np.cumprod(1 + bh)              # equity curve (start=1)
        step = max(1, len(eq_ts) // 150)                                    # downsample ~150 จุด
        curve = {"tsmom": [round(float(x), 3) for x in eq_ts[::step]],
                 "bh": [round(float(x), 3) for x in eq_bh[::step]]}
        return {"tsmom": {"sharpe": round(mt["sharpe"], 2), "cagr": round(mt["cagr"] * 100, 1),
                          "maxdd": round(mt["maxdd"] * 100, 1)},
                "bh": {"sharpe": round(mb["sharpe"], 2), "cagr": round(mb["cagr"] * 100, 1),
                       "maxdd": round(mb["maxdd"] * 100, 1)},
                "alpha_sharpe": round(mt["sharpe"] - mb["sharpe"], 2),
                "has_alpha": bool(mt["sharpe"] > mb["sharpe"]), "years": round(mn / 252, 1),
                "curve": curve}
    except Exception:
        return None


@app.route("/api/worldmonitor")
def api_worldmonitor():
    """live geopolitical/gold signals จาก GDELT (WorldMonitor upstream, ฟรี 0-token). serve file +
    background refresh ถ้า stale (non-blocking). feed globe live risk dots + SELECTION/risk layer."""
    p = os.path.join(_BASE, "..", "data", "worldmonitor.json")
    out = {"ok": False, "events": [], "headlines": [], "attention": None}
    try:
        with open(p, encoding="utf-8") as f:
            out = json.load(f)
    except Exception:
        pass
    # background refresh ถ้า stale (ไม่ block request)
    try:
        stale = (not os.path.exists(p)) or (_time_mod.time() - os.path.getmtime(p) > 1800)
        if stale:
            import threading
            from connectors.worldmonitor import refresh
            threading.Thread(target=refresh, daemon=True).start()
    except Exception:
        pass
    return jsonify(out)


@app.route("/api/tsmom")
def api_tsmom():
    """สถานะ TSMOM-D1 directional engine: signal ensemble + position + state (compute-in-code, 0 token)."""
    import config as _cfg
    vb_years = request.args.get("vb_years", "all")          # toggle: 5 / 10 / all
    _vy = None if vb_years == "all" else float(vb_years)
    out = {"ok": True, "live": bool(getattr(_cfg, "TSMOM_LIVE", False)),
           "shadow": bool(getattr(_cfg, "TSMOM_SHADOW", False)),
           "signal": None, "votes": [], "d1_close": None, "atr_d1": None, "sl_pips": None,
           "position": None, "state": None, "capital_warn": None, "vb_years": vb_years,
           "vs_bh": _cached(f"tsmom-vs-bh:{vb_years}", lambda: _tsmom_vs_bh(_vy), ttl=3600)}
    # ── signal ensemble จาก xau_d1.json (บอทอัปเดตไฟล์) ──
    try:
        import numpy as np
        with open(os.path.join(_BASE, "..", "data", "xau_d1.json")) as _f:
            d = np.array(json.load(_f), dtype=float)
        close, high, low = d[:, 4], d[:, 2], d[:, 3]
        Ls = [int(x) for x in str(getattr(_cfg, "TSMOM_LOOKBACKS", "63,126,252")).split(",")]
        ci = -2; votes_sum = 0
        for L in Ls:
            if len(close) > L - ci + 1:
                s = int(np.sign(close[ci] - close[ci - L]))
                votes_sum += s
                out["votes"].append({"L": L, "sign": s})
        out["signal"] = "BUY" if votes_sum > 0 else ("SELL" if votes_sum < 0 else "FLAT")
        out["d1_close"] = round(float(close[ci]), 2)
        # ATR(D1,22) แท่งปิด
        tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
        atr = float(np.mean(tr[-23:-1]))
        out["atr_d1"] = round(atr, 2)
        fixed = float(getattr(_cfg, "TSMOM_SL_PIPS", 0) or 0)   # respect fixed-SL override
        out["sl_pips"] = int(fixed) if fixed > 0 else int(round(float(getattr(_cfg, "TSMOM_SL_ATR", 3.0)) * atr / 0.01))
    except Exception:
        pass
    # ── capital warning (คล้าย margin call — เตือนถ้าทุนไม่พอ, ไม่บล็อก) ──
    try:
        if out["sl_pips"]:
            from agents.algo_sizing import capital_warning
            warn, wi = capital_warning(out["sl_pips"])
            if warn:
                out["capital_warn"] = {"risk_pct": round(wi["risk_pct"] * 100, 1),
                                       "threshold": round(wi["threshold"] * 100, 1),
                                       "equity": round(wi["equity"]), "needed": round(wi["needed_equity"])}
    except Exception:
        pass
    # ── position ALGO-TSMOM จาก MT5 ──
    if _MT5_AVAILABLE:
        try:
            already = mt5.terminal_info() is not None
            if not already:
                mt5.initialize(); mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
            for p in (mt5.positions_get(symbol=SYMBOL) or []):
                if str(p.comment or "").startswith("ALGO-TSMOM"):
                    out["position"] = {"ticket": p.ticket, "direction": "BUY" if p.type == 0 else "SELL",
                                       "lot": p.volume, "entry": p.price_open, "sl": p.sl or None,
                                       "profit": round(p.profit, 2),
                                       "days": round((datetime.now().timestamp() - p.time) / 86400, 1)}
                    break
            if not already:
                mt5.shutdown()
        except Exception:
            pass
    # ── state ล่าสุด (algo_state.json ถ้าเป็น TSMOM-*) ──
    try:
        with open(os.path.join(_BASE, "..", "data", "algo_state.json"), encoding="utf-8") as _f:
            st = json.load(_f)
        if str(st.get("state") or "").startswith("TSMOM"):
            out["state"] = {"state": st.get("state"), "detail": st.get("detail"), "ts": st.get("ts")}
    except Exception:
        pass
    return jsonify(out)


@app.route("/api/backtest")
def api_backtest():
    """Deep historical breakdown for Backtest tab."""
    system = request.args.get("system", "xauusd").lower()
    login  = _get_actual_mt5_login() if system == "xauusd" else None
    data   = load_trades(system, account_login=login)
    all_trades = [t for t in data.get("trades", []) if t.get("status") == "CLOSED"]

    if not all_trades:
        empty = {"count": 0}
        return jsonify({"ok": True, "trades_count": 0,
                        "tiers": empty, "trends": empty, "entry_types": empty,
                        "sessions": empty, "hold_time": empty, "sr_zones": empty})

    def _tier(conf):
        if conf is None:  return "Unknown"
        if conf >= 65:    return "A+ (≥65)"
        if conf >= 50:    return "B (50-64)"
        return "C (<50)"

    def _session(ts):
        try:
            h = datetime.fromisoformat(ts).hour
            if  7 <= h < 13: return "London"
            if 13 <= h < 22: return "NY"
            return "Asian"
        except Exception:
            return "Unknown"

    def _hold_bucket(t):
        try:
            dt_open  = datetime.fromisoformat(t["timestamp"])
            dt_close = datetime.fromisoformat(t["close_time"])
            mins = (dt_close - dt_open).total_seconds() / 60
            if mins <  30:  return "<30m"
            if mins < 120:  return "30m-2h"
            if mins < 480:  return "2h-8h"
            return ">8h"
        except Exception:
            return "Unknown"

    def _buckets(group_fn, trades_list):
        buckets: dict[str, dict] = {}
        for t in trades_list:
            k   = group_fn(t) or "Unknown"
            pnl = t.get("pnl") or 0.0
            if k not in buckets:
                buckets[k] = {"count": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            buckets[k]["count"]  += 1
            buckets[k]["pnl"]     = round(buckets[k]["pnl"] + pnl, 2)
            if pnl > 0: buckets[k]["wins"]   += 1
            else:       buckets[k]["losses"] += 1
        for v in buckets.values():
            v["win_rate"] = round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0
        return buckets

    sys_trades = [t for t in all_trades if t.get("source") == "SYSTEM"]

    return jsonify({
        "ok":           True,
        "trades_count": len(all_trades),
        "sys_count":    len(sys_trades),
        "tiers":        _buckets(lambda t: _tier(t.get("technical_confidence")), sys_trades),
        "trends":       _buckets(lambda t: t.get("trend"),                        sys_trades),
        "entry_types":  _buckets(lambda t: t.get("entry_type"),                   sys_trades),
        "sr_zones":     _buckets(lambda t: t.get("sr_zone"),                      sys_trades),
        "sessions":     _buckets(lambda t: _session(t.get("timestamp", "")),      all_trades),
        "hold_time":    _buckets(_hold_bucket,                                     all_trades),
    })


_MANUAL_RANGE_FILE = os.path.join(_BASE, "../logs/manual_range.json")


@app.route("/api/manual-range", methods=["GET"])
def api_get_manual_range():
    try:
        with open(_MANUAL_RANGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"ok": True, "active": True, **data})
    except FileNotFoundError:
        return jsonify({"ok": True, "active": False, "high": None, "low": None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/manual-range", methods=["POST"])
def api_set_manual_range():
    body = request.get_json(silent=True) or {}
    try:
        high = float(body.get("high", 0))
        low  = float(body.get("low",  0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "high/low ต้องเป็นตัวเลข"}), 400
    if high <= 0 or low <= 0:
        return jsonify({"ok": False, "error": "ต้องกรอก high และ low"}), 400
    if high <= low:
        return jsonify({"ok": False, "error": "high ต้องมากกว่า low"}), 400
    data = {"high": round(high, 2), "low": round(low, 2),
            "set_at": datetime.now().isoformat(timespec="seconds")}
    try:
        with open(_MANUAL_RANGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/manual-range", methods=["DELETE"])
def api_clear_manual_range():
    try:
        os.remove(_MANUAL_RANGE_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "active": False})


# ── Trade control endpoints (มือถือสั่งผ่าน dashboard → PC ต่อ MT5 ให้) ──
def _ensure_mt5() -> bool:
    """Ensure MT5 is initialized + logged in. Returns True if ready to trade."""
    if not _MT5_AVAILABLE:
        return False
    try:
        if mt5.terminal_info() is not None:
            return True
        if not mt5.initialize():
            return False
        return bool(mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER))
    except Exception:
        return False


def _ticket_from_body() -> tuple[int | None, object]:
    body = request.get_json(silent=True) or {}
    try:
        ticket = int(body.get("ticket", 0))
    except (TypeError, ValueError):
        return None, body
    return (ticket or None), body


def _filling_modes_for(symbol: str) -> list:
    """Return list of ORDER_FILLING_* constants in preference order for symbol.
    Preference: IOC (bit 1 of bitmask) → FOK (bit 0) → RETURN (fallback).
    §3.1 frozen contract: bit0=FOK, bit1=IOC."""
    info = mt5.symbol_info(symbol)
    bm   = int(getattr(info, "filling_mode", 0) or 0) if info is not None else 0
    _FOK    = getattr(mt5, "ORDER_FILLING_FOK",    0)  # MT5 constant = 0
    _IOC    = getattr(mt5, "ORDER_FILLING_IOC",    1)  # MT5 constant = 1
    _RETURN = getattr(mt5, "ORDER_FILLING_RETURN", 2)  # MT5 constant = 2
    modes: list = []
    if bm & 2:       # bit 1 → IOC supported
        modes.append(_IOC)
    if bm & 1:       # bit 0 → FOK supported
        modes.append(_FOK)
    if not modes:    # neither IOC nor FOK → use RETURN
        modes.append(_RETURN)
    return modes


@app.route("/api/close", methods=["POST"])
def api_close_position():
    """ปิด position ตาม ticket (market close) — ใช้ได้ทั้ง SYSTEM และ MANUAL"""
    ticket, _ = _ticket_from_body()
    if not ticket:
        return jsonify({"ok": False, "error": "ต้องระบุ ticket เป็นตัวเลข"}), 400
    if not _ensure_mt5():
        return jsonify({"ok": False, "error": "MT5 not connected"}), 503

    pos_list = mt5.positions_get(ticket=ticket)
    if not pos_list:
        return jsonify({"ok": False, "error": f"ไม่พบ position #{ticket}"}), 404
    pos  = pos_list[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return jsonify({"ok": False, "error": "ไม่สามารถดึงราคาได้"}), 503

    is_buy = pos.type == 0
    modes  = _filling_modes_for(pos.symbol)
    last_err = "no filling mode available"
    for mode in modes:
        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       pos.volume,
            "type":         mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position":     pos.ticket,
            "price":        tick.bid if is_buy else tick.ask,
            "deviation":    20,
            "comment":      "DASHBOARD_CLOSE",
            "type_filling": mode,
        })
        if result is None:
            last_err = str(mt5.last_error())
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return jsonify({"ok": True, "ticket": ticket, "closed_pnl": round(pos.profit, 2)})
        if result.retcode == 10030:   # TRADE_RETCODE_INVALID_FILL → try next mode
            last_err = f"retcode=10030 filling_mode={mode} rejected, trying next"
            continue
        # Other error — do not retry
        last_err = f"retcode={result.retcode} {result.comment}"
        return jsonify({"ok": False, "error": last_err}), 500
    return jsonify({"ok": False, "error": last_err}), 500


@app.route("/api/cancel-pending", methods=["POST"])
def api_cancel_pending_order():
    """ยกเลิก pending order ตาม ticket"""
    ticket, _ = _ticket_from_body()
    if not ticket:
        return jsonify({"ok": False, "error": "ต้องระบุ ticket เป็นตัวเลข"}), 400
    if not _ensure_mt5():
        return jsonify({"ok": False, "error": "MT5 not connected"}), 503

    result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = mt5.last_error() if result is None else f"retcode={result.retcode} {result.comment}"
        return jsonify({"ok": False, "error": str(err)}), 500
    return jsonify({"ok": True, "ticket": ticket})


@app.route("/api/modify", methods=["POST"])
def api_modify_position():
    """ปรับ SL/TP ของ position (ส่ง 0 = ไม่ตั้ง)"""
    ticket, body = _ticket_from_body()
    if not ticket:
        return jsonify({"ok": False, "error": "ต้องระบุ ticket เป็นตัวเลข"}), 400
    try:
        sl = float(body.get("sl") or 0)
        tp = float(body.get("tp") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "sl/tp ต้องเป็นตัวเลข"}), 400
    if not _ensure_mt5():
        return jsonify({"ok": False, "error": "MT5 not connected"}), 503

    pos_list = mt5.positions_get(ticket=ticket)
    if not pos_list:
        return jsonify({"ok": False, "error": f"ไม่พบ position #{ticket}"}), 404
    pos = pos_list[0]
    result = mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   pos.symbol,
        "position": pos.ticket,
        "sl":       sl,
        "tp":       tp,
    })
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = mt5.last_error() if result is None else f"retcode={result.retcode} {result.comment}"
        return jsonify({"ok": False, "error": str(err)}), 500
    return jsonify({"ok": True, "ticket": ticket, "sl": sl, "tp": tp})


@app.route("/api/gate-blocks")
def api_gate_blocks():
    """block ล่าสุดจาก logs/gate_blocks.jsonl — Why-No-Entry panel (Live tab)
    ตอบคำถาม 'ทำไมบอทไม่เข้า order' ได้จากหน้าจอ ไม่ต้องไล่ log"""
    try:
        p = os.path.join(_BASE, "../logs/gate_blocks.jsonl")
        with open(p, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        rows = [json.loads(l) for l in lines[-120:] if l.strip()]
        rows = rows[-25:]
        rows.reverse()   # ใหม่สุดก่อน
        return jsonify({"ok": True, "blocks": rows})
    except FileNotFoundError:
        return jsonify({"ok": True, "blocks": []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "blocks": []})


@app.route("/api/ride-stats")
def api_ride_stats():
    """ผล cohort ไม้ MOMENTUM_RIDE (entry comment ขึ้นต้น 'RIDE') จาก MT5 —
    หน้าปัดการทดลอง: cohort นี้แพ้เมื่อไหร่ = ปิด MOMENTUM_RIDE knob"""
    def _compute():
        if not _MT5_AVAILABLE or not _ensure_mt5():
            return {"ok": False, "error": "MT5 not connected"}
        from collections import defaultdict
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=90), datetime.now()) or []
        pos = defaultdict(lambda: {"in": None, "pnl": 0.0, "closed": False})
        for d in deals:
            if d.symbol != SYMBOL:
                continue
            p = pos[d.position_id]
            p["pnl"] += d.profit + d.swap + d.commission
            if d.entry == 0 and p["in"] is None:
                p["in"] = d
            elif d.entry in (1, 2):
                p["closed"] = True
        rides = []
        for pid, p in pos.items():
            e = p["in"]
            if e is None or not str(e.comment or "").startswith("RIDE"):
                continue
            rides.append({"time": datetime.fromtimestamp(e.time).isoformat()[:16],
                          "dir": "BUY" if e.type == 0 else "SELL",
                          "pnl": round(p["pnl"], 2), "closed": p["closed"]})
        n_open  = sum(1 for r in rides if not r["closed"])
        closed  = [r for r in rides if r["closed"]]
        wins    = sum(1 for r in closed if r["pnl"] > 0)
        return {"ok": True, "n_closed": len(closed), "n_open": n_open,
                "wr": round(wins / len(closed) * 100, 1) if closed else None,
                "pnl": round(sum(r["pnl"] for r in closed), 2),
                "recent": sorted(rides, key=lambda r: r["time"], reverse=True)[:5]}
    return jsonify(_cached("ride-stats", _compute, ttl=60))


@app.route("/api/algo-status")
def api_algo_status():
    """สถานะระบบใหม่ (header): REGIME_LIVE mode + regime ปัจจุบัน + algo signal + disabled. 0 token."""
    def _c():
        import config as _cfg
        try:
            _cfg.reload_config()
        except Exception:
            pass
        live = getattr(_cfg, "REGIME_LIVE", False)
        tsmom = getattr(_cfg, "TSMOM_LIVE", False)          # TSMOM = engine → momentum/fade stand-down
        mode = "TSMOM-D1 (daily)" if tsmom else (
            ("pending" if getattr(_cfg, "REGIME_PENDING", False)
             else ("per-tick" if getattr(_cfg, "REGIME_LIVE_TICK", False) else "per-cycle")) if live else "OFF")
        regime = None; signal = None
        try:
            from agents.regime_shadow import _bars_from_feed, compute_shadow_signal
            bars = _bars_from_feed()
            if bars:
                rec = compute_shadow_signal(*bars)
                regime = rec.get("regime"); signal = rec.get("signal")
        except Exception:
            pass
        try:
            from agents.regime_adaptive import disabled_strategies
            disabled = disabled_strategies()
        except Exception:
            disabled = []
        if tsmom:                                            # โหมด TSMOM: momentum/fade ปิด → ไม่โชว์ signal เก่า
            signal = None
            disabled = list(disabled) + ["momentum-intraday", "fade-pending"]
        return {"regime_live": live, "mode": mode, "regime": regime, "signal": signal, "disabled": disabled}
    return jsonify(_cached("algo-status", _c, ttl=15))


@app.route("/api/cluster-map")
def api_cluster_map():
    """Price-Cluster decision-support (Monitor tab) — คำนวณสด dwell-zone S/R จาก MT5 H1.
    บอทคำนวณให้ owner ตัดสินใจ (กฎ fade อัตโนมัติไม่มี edge; วิจารณญาณ owner มี). display-only, 0 token."""
    def _c():
        from agents.cluster_map import from_mt5
        return from_mt5()
    return jsonify(_cached("cluster-map", _c, ttl=20))


@app.route("/api/macro-quant")
def api_macro_quant():
    """Macro/News quant (ข่าว + เศรษฐกิจ → gold bias score) — รวมตัวเลขที่ scored ไว้เป็น analysis เดียว.
    news_impact + macro_strip + regime_extra + cot → weighted gold-directional score + breakdown. 0 token."""
    def _c():
        from agents.macro_quant import gold_macro_score
        return gold_macro_score()
    return jsonify(_cached("macro-quant", _c, ttl=15))


@app.route("/api/algo-journal")
def api_algo_journal():
    """Trade score realtime — สรุป algo journal (momentum signal / fade / pending lifecycle จริง):
    win-rate + exp_R + n + pending by_mode/expired. counterfactual + real pending. 0 token."""
    def _c():
        from agents.algo_journal import summary
        return {"ok": True, **summary()}
    return jsonify(_cached("algo-journal", _c, ttl=15))


@app.route("/api/owner-gate")
def api_owner_gate():
    """Owner-gate advisory — เตือนเมื่อ mid-vol / manual short (regime ที่ owner เสียต่อเนื่อง). 0 token."""
    def _c():
        from agents.owner_gate import owner_gate_now
        return owner_gate_now()
    return jsonify(_cached("owner-gate", _c, ttl=20))


@app.route("/api/owner-edge")
def api_owner_edge():
    """Owner edge × vol/market regime — วิเคราะห์ไม้ manual ว่าชนะ/แพ้ regime ไหน (หา alpha จริงของ owner). 0 token."""
    def _c():
        from agents.owner_edge import build_owner_edge
        return build_owner_edge()
    return jsonify(_cached("owner-edge", _c, ttl=120))


@app.route("/api/daily-summary")
def api_daily_summary():
    """สรุปเทรดรายวัน (Analytics): เทคนิค · regime · กำไร/ขาดทุน · ทำไมเข้า/ขาดทุน. จาก trades.json. 0 token."""
    tech = request.args.get("tech", "all")
    def _c():
        from agents.daily_summary import build_daily_summary
        return {"ok": True, **build_daily_summary(days=45, tech=tech)}
    return jsonify(_cached(f"daily-summary:{tech}", _c, ttl=60))


@app.route("/api/liquidity-proxy")
def api_liquidity_proxy():
    """Liquidity/order-flow proxy (volume-profile + cluster + COT). ⚠️ proxy — XAUUSD retail ไม่มี book จริง.
    flow tilt + liquidity magnets (walls/pools). SELECTION guide เท่านั้น, 0 token."""
    def _c():
        from agents.liquidity_proxy import liquidity_score
        try:
            from agents.cluster_map import from_mt5
            cl = from_mt5()
        except Exception:
            cl = None
        return liquidity_score(cluster=cl if (cl or {}).get("ok") else None)
    return jsonify(_cached("liquidity-proxy", _c, ttl=15))


def _scripts_path():
    _sd = os.path.join(_BASE, "../scripts")
    if _sd not in sys.path:
        sys.path.insert(0, _sd)


def _file_fallback(name):
    """อ่านไฟล์ precompute (fallback ถ้า compute live fail) + mark stale."""
    try:
        with open(os.path.join(_BASE, "../data", name), encoding="utf-8") as f:
            return {"ok": True, "stale": True, **json.load(f)}
    except Exception as e:
        return {"ok": False, "error": f"compute+file ไม่ได้: {e}"}


@app.route("/api/regime-monitor")
def api_regime_monitor():
    """Live Monitor — ALGO trades จริง (N-gauge + decay). **compute live** จากไม้ ALGO ใน MT5
    (ไม่อ่านไฟล์ stale). N=0 = ยังไม่มีไม้ ALGO (สดจริง ไม่ใช่ค้าง). 0 LLM."""
    def _c():
        from datetime import datetime, timezone
        _scripts_path()
        try:
            import regime_monitor as RM
            return {"ok": True, "generated": datetime.now(timezone.utc).isoformat(),
                    "strategy": "momentum_breakout (TREND)", "sigma_R": RM.SIGMA_R,
                    **RM.analyze(RM.fetch_algo_trades())}
        except Exception:
            return _file_fallback("regime_monitor.json")
    return jsonify(_cached("regime-monitor", _c, ttl=30))


@app.route("/api/regime-analytics")
def api_regime_analytics():
    """สรุป regime router + weekly (shadow). **compute live** (build_report) — historical backtest +
    weekly shadow สด (ไม่อ่านไฟล์ stale). cache 5 นาที (backtest หนัก). 0 LLM."""
    def _c():
        _scripts_path()
        try:
            import regime_analytics as RA
            return {"ok": True, **RA.build_report()}
        except Exception:
            return _file_fallback("regime_analytics.json")
    return jsonify(_cached("regime-analytics", _c, ttl=300))


_TF_MAP = {}
if _MT5_AVAILABLE:
    _TF_MAP = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
               "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}


@app.route("/api/candles")
def api_candles():
    """แท่งเทียนจาก MT5 สำหรับ price chart (lightweight-charts) — cache 10s"""
    tf = request.args.get("tf", "M15").upper()
    try:
        count = min(int(request.args.get("count", 250)), 500)
    except ValueError:
        count = 250
    if tf not in ("M15", "H1", "H4", "D1"):
        return jsonify({"ok": False, "error": "bad tf", "candles": []}), 400

    def _fetch():
        if not _MT5_AVAILABLE or not _ensure_mt5():
            return {"ok": False, "error": "MT5 not connected", "candles": []}
        rates = mt5.copy_rates_from_pos(SYMBOL, _TF_MAP[tf], 0, count)
        if rates is None:
            return {"ok": False, "error": str(mt5.last_error()), "candles": []}
        return {"ok": True, "tf": tf, "candles": [
            {"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])} for r in rates]}
    return jsonify(_cached(f"candles:{tf}:{count}", _fetch, ttl=10))


@app.route("/api/regime")
def api_regime():
    """สรุป macro regime จาก agents/prompts/macro_regime.md (ไฟล์เดียวกับที่ analyst อ่าน)
    — คืน PHASE line + UPDATED line สำหรับ Regime Strip บนหัว dashboard"""
    try:
        p = os.path.join(_BASE, "../agents/prompts/macro_regime.md")
        with open(p, "r", encoding="utf-8") as f:
            txt = f.read()
        marker = "<!-- REGIME_START -->"
        body = txt.split(marker, 1)[1] if marker in txt else txt
        # ดึงทุกบรรทัดสรุป (PHASE/DRIVERS/FILTER/CATALYSTS/UPDATED) — ticker โชว์ครบทั้งชุด
        fields = {"PHASE": "", "DRIVERS": "", "FILTER": "", "CATALYSTS": "", "UPDATED": ""}
        for line in body.splitlines():
            s = line.strip()
            for key in fields:
                if s.startswith(key + ":") and not fields[key]:
                    fields[key] = s[len(key) + 1:].strip()
        return jsonify({"ok": True,
                        "phase":     fields["PHASE"],
                        "drivers":   fields["DRIVERS"],
                        "filter":    fields["FILTER"],
                        "catalysts": fields["CATALYSTS"],
                        "updated":   fields["UPDATED"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "phase": "", "updated": ""})


@app.route("/api/event-stats")
def api_event_stats():
    """สถิติ event-reaction จาก data/event_stats.json (สร้างโดย scripts/event_reaction_stats.py)
    — ใช้โดย Event Radar บน Live tab (prior + forward projection)"""
    try:
        p = os.path.join(_BASE, "../data/event_stats.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify({"ok": True, **json.load(f)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "events": {}})


@app.route("/api/burn")
def api_burn():
    """AI burn ฿/วัน จาก data/burn_daily.json (สร้างโดย scripts/report_burn.py)
    — display-only, pass-through serve; ถ้าไฟล์หาย → empty payload ไม่ 500 (§3.4, §5 #6)"""
    _empty = {"ok": True, "days": [], "today_thb": 0, "target_min": 150, "target_max": 250}
    try:
        p = os.path.join(_BASE, "../data/burn_daily.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/news-gate")
def api_news_gate():
    """NEWS_GATE cohort — ไม้ที่ผ่านเพราะ news relax เป็นตัวตัดสิน (tag 'NG ')
    จาก data/news_gate.json (scripts/report_news_gate.py). display-only, never 500."""
    _empty = {"ok": True, "n": 0, "win": 0, "loss": 0, "wr": None, "pnl": 0.0, "open": 0, "trades": []}
    try:
        p = os.path.join(_BASE, "../data/news_gate.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/event-scenario")
def api_event_scenario():
    """Event scenario (sign + rubric magnitude) from data/event_scenarios.json
    (built by scripts/build_event_scenarios.py — ARCHITECTURE §4.2, M2).
    — display-only, pass-through serve; file missing → empty payload, never 500."""
    _empty = {"ok": True, "updated": None, "window": None, "min_n": 30, "scenarios": {}}
    try:
        p = os.path.join(_BASE, "../data/event_scenarios.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/news-impact")
def api_news_impact():
    """News Impact snapshot: rolling bull/bear score + scored posts (Feature A, M3).
    Data from data/news_impact.json (written by news_cache.get_news_context after each Haiku call).
    — display-only, pass-through serve; file missing -> empty payload, never 500 (ARCHITECTURE §4.1, §D7)."""
    _empty = {
        "ok": True,
        "updated": None,
        "window_min": 180,
        "aggregate": {
            "score": 0, "label": "neutral gold",
            "n_scored": 0, "provenance": "rubric", "n": 0,
        },
        "filter_stats": {"raw": 0, "kept": 0, "filter_rate_pct": 0},
        "posts": [],
    }
    try:
        p = os.path.join(_BASE, "../data/news_impact.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/impact-calibration")
def api_impact_calibration():
    """News-impact calibration: per-tier hit-rate (predicted magnitude vs realized move).
    Data from data/impact_calibration.json (written by scripts/review_calibration.py — ARCHITECTURE §4.3, M6).
    — display-only, pass-through serve; file missing → empty payload, never 500 (ARCHITECTURE §D7)."""
    _empty = {
        "ok": True,
        "updated": None,
        "min_n": 30,
        "tiers": {
            "1": {"assumed_band_pct": [0.0, 0.4], "hit_rate_pct": None, "n": 0,
                  "mean_realized_abs_move_pct": None},
            "2": {"assumed_band_pct": [0.4, 0.9], "hit_rate_pct": None, "n": 0,
                  "mean_realized_abs_move_pct": None},
            "3": {"assumed_band_pct": [0.9, 9.9], "hit_rate_pct": None, "n": 0,
                  "mean_realized_abs_move_pct": None},
        },
        "status": "collecting",
    }
    try:
        p = os.path.join(_BASE, "../data/impact_calibration.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/regime-state")
def api_regime_state():
    """Regime-shift state from data/regime_state.json (written by scripts/update_regime.py — C12-§3).
    — display-only, pass-through serve; file missing → empty shape, never 500 (mirrors /api/burn)."""
    _empty = {
        "ok": True,
        "updated": None,
        "fed_dir": None,
        "real_rate_sign": None,
        "sentiment_tilt": "neutral",
        "cpi_yoy": None,
        "fed_funds": None,
        "real_rate": None,
        "shift": {"active": False, "kind": [], "from": None, "to": None, "since": None},
        "history": [],
    }
    try:
        p = os.path.join(_BASE, "../data/regime_state.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/calibration")
def api_calibration():
    """Confidence calibration: predicted conf bin -> realized WR/PnL
    Data from data/calibration.json (generated by scripts/report_calibration.py)
    — display-only, pass-through serve; file missing -> empty payload not 500 (§3.5, §5 #6)"""
    _empty = {"ok": True, "bins": [], "updated": None}
    try:
        p = os.path.join(_BASE, "../data/calibration.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/macro-strip")
def api_macro_strip():
    """Macro strip: DXY proxy (UUP), 10Y yield, real yield.
    Data from data/macro_strip.json (generated by scripts/fetch_macro_strip.py, daily).
    — display-only, pass-through serve; file missing → empty payload not 500 (§3.5, §5 #6)"""
    _empty = {"ok": True, "dxy": None, "y10": None, "real_yield": None, "updated": None}
    try:
        p = os.path.join(_BASE, "../data/macro_strip.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/regime-extra")
def api_regime_extra():
    """Tier 2 regime context: VIX + gold/silver ratio (risk-on/off regime).
    Data from data/regime_extra.json (scripts/fetch_regime_extra.py via Yahoo, daily).
    — display-only, pass-through; file missing → empty payload not 500 (same pattern as macro-strip)."""
    _empty = {"ok": True, "vix": None, "gsr": None, "updated": None}
    try:
        p = os.path.join(_BASE, "../data/regime_extra.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/risk-regime")
def api_risk_regime():
    """Cross-asset HMM risk regime (RISK-ON/NEUTRAL/RISK-OFF) from gold+VIX+DXY.
    Data from data/risk_regime_now.json (scripts/fetch_risk_regime.py, daily).
    — display-only, pass-through; validated vol/risk CONTEXT, not a directional signal."""
    _empty = {"ok": True, "regime": None, "vix": None, "gold_ctx_yr": None, "updated": None}
    try:
        p = os.path.join(_BASE, "../data/risk_regime_now.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/cot")
def api_cot():
    """CFTC COT non-commercial gold positioning (weekly).
    Data from data/cot.json (generated by scripts/fetch_cot.py, Fridays).
    — display-only, pass-through serve; file missing → empty payload not 500 (§3.5, §5 #6)"""
    _empty = {
        "ok": True,
        "report_date": None,
        "noncomm_long": None,
        "noncomm_short": None,
        "net": None,
        "net_chg": None,
        "updated": None,
    }
    try:
        p = os.path.join(_BASE, "../data/cot.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(_empty)
    except Exception:
        return jsonify(_empty)


@app.route("/api/calendar")
def api_calendar():
    """Calendar feed: US (USD) = ทั้งหมดของสัปดาห์นี้ (ทุก impact, past+future);
    สกุลอื่น = High/Medium ที่จะเกิดใน 7 วัน (เหมือนเดิม)."""
    try:
        from connectors.web_news import fetch_forexfactory_calendar
        events = fetch_forexfactory_calendar(hours_ahead=168, include_all_us=True)
        events.sort(key=lambda e: e.get("timestamp_iso", ""))
        return jsonify({"events": events, "ok": True})
    except Exception as e:
        return jsonify({"events": [], "ok": False, "error": str(e)})


def _warm_cache() -> None:
    """Pre-load slow MT5 + DB caches at startup so the first frontend poll
    gets data instantly instead of blocking ~40s on a cold MT5 sync."""
    try:
        login = _get_actual_mt5_login()
        data  = _cached("trades:xauusd:None",
                        lambda: load_trades("xauusd", account_login=None), ttl=15)
        _cached("mt5acct:xauusd",
                lambda: get_mt5_account(data_to_sync=data), ttl=30)
        if login:
            key = f"trades:xauusd:{login}"
            _cached(key, lambda: load_trades("xauusd", account_login=login), ttl=15)
        print("[warm_cache] done", flush=True)
    except Exception as e:
        print(f"[warm_cache] error: {e}", flush=True)


if __name__ == "__main__":
    import threading
    threading.Thread(target=_warm_cache, daemon=True).start()
    from waitress import serve
    serve(app, host="0.0.0.0", port=5050, threads=4)
