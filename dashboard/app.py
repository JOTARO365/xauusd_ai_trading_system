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
ENV_FILE     = os.path.join(_BASE, "../.env")

# Keys ที่อนุญาตให้แก้ไขผ่าน dashboard (ไม่รวม credentials)
_EDITABLE_KEYS = {
    "SYMBOL", "START_BALANCE",
    "LOT_MODE", "FIXED_LOT", "MIN_LOT", "MAX_LOT",
    "RISK_PER_TRADE", "MAX_DAILY_LOSS", "MAX_OPEN_TRADES",
    "DEFAULT_SL_PIPS", "DEFAULT_TP_PIPS", "MIN_RR_RATIO", "HEDGE_BUFFER_PIPS",
    "MAX_PENDING_BUY", "MAX_PENDING_SELL", "PENDING_EXPIRY_HOURS",
    "MAX_LOSING_STREAK", "STREAK_MIN_CONFIDENCE",
    "PORTFOLIO_PROTECTION", "STREAK_PROTECTION", "DYNAMIC_TP",
    "LESSON_LEARNING", "DRY_RUN",
    "BE_TRIGGER_R", "BE_BUFFER_PIPS", "BE_CONFIRM_CYCLES",
    "NNLB_MODE", "NNLB_BASE_EQUITY", "NNLB_EQUITY_PER_LOT", "NNLB_MAX_LOSS_PCT",
    "TRAILING_STOP", "TRAILING_ATR_TF", "TRAILING_ATR_MULT",
    "X_ACCOUNTS_TO_FOLLOW", "X_KEYWORDS",
}

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
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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
    today_closed  = [t for t in chrono if t.get("timestamp", "").startswith(today_str)]
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
    """คืน trading config ปัจจุบัน — อ่านจาก .env file โดยตรง (ไม่ใช่ runtime env vars)"""
    defaults = {
        "SYMBOL": "XAUUSD", "START_BALANCE": "2000",
        "LOT_MODE": "auto", "FIXED_LOT": "0.01", "MIN_LOT": "0.01", "MAX_LOT": "0.01",
        "RISK_PER_TRADE": "0.50", "MAX_DAILY_LOSS": "1.00", "MAX_OPEN_TRADES": "4",
        "DEFAULT_SL_PIPS": "1000", "DEFAULT_TP_PIPS": "3000", "MIN_RR_RATIO": "1.5",
        "MAX_PENDING_BUY": "3", "MAX_PENDING_SELL": "3", "PENDING_EXPIRY_HOURS": "48",
        "MAX_LOSING_STREAK": "5", "STREAK_MIN_CONFIDENCE": "62",
        "PORTFOLIO_PROTECTION": "true", "STREAK_PROTECTION": "true", "DYNAMIC_TP": "true",
        "LESSON_LEARNING": "true", "DRY_RUN": "false",
        "BE_TRIGGER_R": "0.8", "BE_BUFFER_PIPS": "200", "BE_CONFIRM_CYCLES": "2",
        "NNLB_MODE": "false", "NNLB_BASE_EQUITY": "100",
        "NNLB_EQUITY_PER_LOT": "100", "NNLB_MAX_LOSS_PCT": "25",
        "TRAILING_STOP": "false", "TRAILING_ATR_TF": "D1", "TRAILING_ATR_MULT": "1.5",
        "X_ACCOUNTS_TO_FOLLOW": "kun_purich,cnnbrk,BBCBreaking,ZeroHedge,markets",
        "X_KEYWORDS": "XAUUSD,gold,XAU,bullion,Fed,inflation",
    }
    env = _read_env_file()
    return jsonify({k: env.get(k, v) for k, v in defaults.items()})


@app.route("/api/config", methods=["POST"])
def api_set_config():
    """รับ JSON → อัปเดต .env เฉพาะ trading keys → เขียนคืน"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "no JSON body"}), 400

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

    # ── PM2 restart (ถ้ามี) ───────────────────────────────────────
    pm2_ok, pm2_msg = _pm2_restart()
    return jsonify({"ok": True, "updated": sorted(updates.keys()),
                    "pm2_ok": pm2_ok, "pm2_msg": pm2_msg})


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


@app.route("/api/accounting")
def api_accounting():
    """ค่าใช้จ่าย AI — รองรับ ?system=xauusd|btcusd|all (default=all) และ ?account=all|own"""
    system  = request.args.get("system", "all").lower()
    account = request.args.get("account", "all").lower()
    login   = None if account == "all" else _get_actual_mt5_login()
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
            return jsonify({**data, "ok": True, "system": system, "source": "db"})
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
        return jsonify({**data, "ok": True, "system": system, "source": "json"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "system": system,
                        "summary": {}, "agents": {}, "today": {}, "daily": {}})


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


@app.route("/api/calendar")
def api_calendar():
    """ดึง economic calendar สัปดาห์นี้ (High + Medium impact events)"""
    try:
        from connectors.web_news import fetch_forexfactory_calendar
        events = fetch_forexfactory_calendar(hours_ahead=168)
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
