"""agents/shadow_engine.py — Batch B (T-04): multi-pair shadow engine.

Each cycle, for every (algo, pair) whose switch state is SHADOW: fetch that pair's H1 bars, ask the
algo for a VirtualOrder, log a new signal (dedup per bar_ts), and resolve open signals against the
real bars (SL-first, per-pair measured cost). Sends NOTHING to MT5 — this is a paper record only.

Storage: one JSONL per combo, logs/shadow/<algo_id>__<symbol>.jsonl (record schema = ARCHITECTURE §4.3).
Whole-file rewrite on change (outcomes mutate in place), same as algo_journal.

Reuses: algo_registry (signals), shadow_switches (state), shadow_cost (per-pair cost), shadow_resolve
(the parity-tested resolver), pair_collector._broker_map (logical→broker symbol), price_feed.get_ohlcv.
The XAUUSD live pipeline and algo_journal are NOT touched.

Wiring (T-05): trading_graph.node_position_mgmt calls tick() every cycle, gated by config.SHADOW_ENGINE.
"""
import json
import os
from datetime import datetime, timezone

from loguru import logger

from agents import algo_registry as _reg
from agents import shadow_switches as _sw
from agents import shadow_cost as _cost
from agents.shadow_resolve_managed import resolve_managed   # paper order ผ่าน BE+trailing (สถิติสมจริง)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGDIR = os.path.join(_BASE, "logs", "shadow")
_DEFAULT_MAX_HOLD = 48
_BARS_COUNT = 600


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _logpath(algo_id, symbol):
    return os.path.join(_LOGDIR, f"{algo_id}__{symbol}.jsonl")


def _read_rows(path):
    out = []
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return out


def _write_rows(path, rows):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _new_record(vo, cost_pips, point, digits):
    """Build an OPEN signal record from a VirtualOrder (schema §4.3). Outcome filled by first resolve."""
    sign = 1 if vo["dir"] == "BUY" else -1
    entry, slp, tpp = vo["entry"], vo["sl_pips"], vo["tp_pips"]
    return {
        "algo_id": vo["algo_id"], "symbol": vo["symbol"], "klass": vo["klass"],
        "kind": "signal", "logged_at": _iso_now(), "bar_ts": vo["bar_ts"],
        "regime": vo["regime"], "dir": vo["dir"], "entry": entry,
        "sl": round(entry - sign * slp * point, digits),
        "tp": round(entry + sign * tpp * point, digits),
        "sl_pips": slp, "tp_pips": tpp,
        "cost_pips": cost_pips, "point": point, "price_digits": digits,
    }


def _resolve_tsmom_flip(rec, high, low, close, times, *, point, cost_pips, digits, lookbacks=(63, 126, 252)):
    """paper resolve สำหรับ tsmom_d1 = exit-on-flip (มิเรอร์ scripts.tsmom_pairs_screen / tsmom_manager):
    เดินหน้าจากบาร์เข้า → ปิดเมื่อ ensemble vote กลับข้าง หรือ disaster SL (3×ATR ตั้งตอนเข้า) โดน.
    map flip→TP/SL ตาม R (schema by_result). net cost ×1 (round-trip เก็บใน cost_pips). คืน outcome หรือ OPEN(tail)."""
    import numpy as np
    from datetime import datetime, timezone
    direction = rec["dir"]; entry_px = float(rec["entry"])
    sl_dist = float(rec.get("sl_pips", 0)) * point
    if sl_dist <= 0:
        return None
    try:
        entry_ep = int(datetime.fromisoformat(rec["bar_ts"]).timestamp())
    except Exception:
        return None
    i0 = next((k for k in range(len(times) - 1, -1, -1) if int(times[k]) == entry_ep), None)
    if i0 is None:
        return None
    is_buy = direction == "BUY"
    sign = 1 if is_buy else -1
    sl = entry_px - sl_dist if is_buy else entry_px + sl_dist
    cost = cost_pips * point
    n = len(close)
    mfe = mae = 0.0

    def _out(result, exit_px, j):
        r = (sign * (exit_px - entry_px) - cost) / sl_dist
        ts = datetime.fromtimestamp(int(times[j]), timezone.utc).isoformat()
        return {"result": result, "realized_R": round(r, 3), "realized_R_gross": round(r, 3),
                "bars_held": int(j - i0), "exit_price": round(float(exit_px), digits), "exit_ts": ts,
                "mfe_R": round(mfe, 2), "mae_R": round(mae, 2)}

    for j in range(i0 + 1, n):
        fav = sign * (float(high[j] if is_buy else low[j]) - entry_px) / sl_dist
        adv = sign * (float(low[j] if is_buy else high[j]) - entry_px) / sl_dist
        mfe = max(mfe, fav); mae = min(mae, adv)
        if (is_buy and float(low[j]) <= sl) or ((not is_buy) and float(high[j]) >= sl):
            return _out("SL", sl, j)                          # disaster SL โดน
        votes = sum(int(np.sign(close[j] - close[j - L])) for L in lookbacks if j - L >= 0)
        newdir = "BUY" if votes > 0 else ("SELL" if votes < 0 else None)
        if newdir and newdir != direction:                   # flip → ปิดที่ close
            exit_px = float(close[j])
            r = (sign * (exit_px - entry_px) - cost) / sl_dist
            return _out("TP" if r >= 0 else "SL", exit_px, j)
    return {"result": "OPEN", "bars_held": n - 1 - i0}        # tail: ยังไม่จบ


def _resolve_cdc_flip(rec, high, low, close, times, *, point, cost_pips, digits):
    """paper resolve สำหรับ cdc_zone = exit-on-flip: ปิดเมื่อ CDC Action Zone กลับข้าง (fast<slow สำหรับ long)
    หรือ disaster SL (2×ATR ตอนเข้า) โดน. มิเรอร์ _resolve_tsmom_flip แต่ flip = CDC zone (close-source)."""
    from datetime import datetime, timezone
    import regime_lib as _R
    direction = rec["dir"]; entry_px = float(rec["entry"])
    sl_dist = float(rec.get("sl_pips", 0)) * point
    if sl_dist <= 0:
        return None
    try:
        entry_ep = int(datetime.fromisoformat(rec["bar_ts"]).timestamp())
    except Exception:
        return None
    i0 = next((k for k in range(len(times) - 1, -1, -1) if int(times[k]) == entry_ep), None)
    if i0 is None:
        return None
    is_buy = direction == "BUY"; sign = 1 if is_buy else -1
    sl = entry_px - sl_dist if is_buy else entry_px + sl_dist
    cost = cost_pips * point; n = len(close); mfe = mae = 0.0
    fast, slow = _R.cdc_zone(close)

    def _out(result, exit_px, j):
        r = (sign * (exit_px - entry_px) - cost) / sl_dist
        ts = datetime.fromtimestamp(int(times[j]), timezone.utc).isoformat()
        return {"result": result, "realized_R": round(r, 3), "realized_R_gross": round(r, 3),
                "bars_held": int(j - i0), "exit_price": round(float(exit_px), digits), "exit_ts": ts,
                "mfe_R": round(mfe, 2), "mae_R": round(mae, 2)}

    for j in range(i0 + 1, n):
        fav = sign * (float(high[j] if is_buy else low[j]) - entry_px) / sl_dist
        adv = sign * (float(low[j] if is_buy else high[j]) - entry_px) / sl_dist
        mfe = max(mfe, fav); mae = min(mae, adv)
        if (is_buy and float(low[j]) <= sl) or ((not is_buy) and float(high[j]) >= sl):
            return _out("SL", sl, j)                          # disaster SL โดน
        newdir = "BUY" if fast[j] > slow[j] else "SELL"
        if newdir != direction:                              # zone พลิก → ปิดที่ close
            exit_px = float(close[j])
            r = (sign * (exit_px - entry_px) - cost) / sl_dist
            return _out("TP" if r >= 0 else "SL", exit_px, j)
    return {"result": "OPEN", "bars_held": n - 1 - i0}        # tail: ยังไม่จบ


def _apply(algo_id, symbol, bars, point, digits, cost_pips, max_hold=_DEFAULT_MAX_HOLD):
    """Pure-ish core (no MT5): capture new signal + resolve open ones for ONE combo. Returns a summary.
    Testable directly with injected bars. Each signal resolves at the cost/point stored on its record."""
    high, low, close, times = bars
    path = _logpath(algo_id, symbol)
    rows = _read_rows(path)
    seen = {r.get("bar_ts") for r in rows if r.get("kind") == "signal"}
    changed = False
    new = 0

    # 1) capture new signal at the last closed bar (dedup per bar_ts)
    algo = _reg.get(algo_id)
    vo = algo.evaluate(symbol, bars, point=point) if algo else None
    if vo and vo.get("bar_ts") and vo["bar_ts"] not in seen:
        rows.append(_new_record(vo, cost_pips, point, digits))
        changed = True
        new = 1

    # 2) resolve every open record against forward bars (per-algo: tsmom = exit-on-flip · อื่น = managed BE/trail)
    mgmt = getattr(algo, "mgmt", "managed")
    resolved = 0
    for rec in rows:
        if rec.get("kind") != "signal":
            continue
        res = (rec.get("outcome") or {}).get("result")
        if res in ("TP", "SL", "TIMEOUT"):
            continue                                     # terminal — skip
        if mgmt == "tsmom_flip":
            out = _resolve_tsmom_flip(rec, high, low, close, times,
                                      point=rec.get("point", point),
                                      cost_pips=rec.get("cost_pips", cost_pips),
                                      digits=rec.get("price_digits", digits))
        elif mgmt == "cdc_flip":
            out = _resolve_cdc_flip(rec, high, low, close, times,
                                    point=rec.get("point", point),
                                    cost_pips=rec.get("cost_pips", cost_pips),
                                    digits=rec.get("price_digits", digits))
        else:
            out = resolve_managed(rec, high, low, close, times,
                                  point=rec.get("point", point),
                                  cost_pips=rec.get("cost_pips", cost_pips),
                                  max_hold_bars=max_hold,
                                  price_digits=rec.get("price_digits", digits))
        if out is not None and out != rec.get("outcome"):
            rec["outcome"] = out
            changed = True
            if out.get("result") in ("TP", "SL", "TIMEOUT"):
                resolved += 1

    if changed:
        _write_rows(path, rows)
    return {"combo": f"{algo_id}:{symbol}", "new": new, "resolved": resolved, "rows": len(rows)}


def _bars(broker_symbol, tf="H1", count=None):
    """(high, low, close, times) ตาม timeframe ของ algo (H1 default · D1 = tsmom). fail-soft → None."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        tfmap = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
        if tf not in tfmap:                                   # FIX: unknown TF = skip ชัดเจน (เดิม fallback เงียบ H1 → confluence_15m ถูกเทสเป็น H1)
            return None
        mt5_tf = tfmap[tf]
        if count is None:
            count = 400 if tf == "D1" else _BARS_COUNT
        min_bars = 282 if tf == "D1" else 520
        rates = get_ohlcv(symbol=broker_symbol, timeframe=mt5_tf, count=count)
        if rates is None or len(rates) < min_bars:
            return None
        return (rates["high"].astype(float), rates["low"].astype(float),
                rates["close"].astype(float), rates["time"])
    except Exception:
        return None


def _symbol_meta(broker_symbol):
    """(point, digits) for a broker symbol, or (None, None) if unavailable."""
    try:
        import MetaTrader5 as mt5
        info = mt5.symbol_info(broker_symbol)
        if info and info.point:
            return float(info.point), int(info.digits)
    except Exception:
        pass
    return None, None


def tick(force=False):
    """Every-cycle entry. Gated by config.SHADOW_ENGINE (or force=True for tests). fail-soft; 0 orders.
    Returns a summary dict, or None when gated off."""
    import config as _cfg
    if not force and not getattr(_cfg, "SHADOW_ENGINE", False):
        return None
    universe = getattr(_cfg, "SHADOW_UNIVERSE", None) or _reg.UNIVERSE
    max_hold = getattr(_cfg, "SHADOW_MAX_HOLD_BARS", _DEFAULT_MAX_HOLD)
    eligible = _reg.combos(universe)

    active = _sw.combos_in(_sw.SHADOW, eligible)
    live = _sw.combos_in(_sw.LIVE, eligible)
    if getattr(_cfg, "MULTI_SYMBOL_LIVE", False):
        # executor (multi_symbol_executor) เป็นเจ้าของ combo LIVE แล้ว → อย่า paper-fill ซ้ำ (กัน double-count)
        for a, s in live:
            logger.debug(f"[SHADOW] {a}:{s} state=LIVE → executor จัดการ (ข้าม paper-fill)")
    else:
        # master OFF: ไม่มี live path → รัน LIVE เป็น shadow (เก็บ data ต่อ) + เตือน
        for a, s in live:
            logger.warning(f"[SHADOW] {a}:{s} state=LIVE แต่ MULTI_SYMBOL_LIVE=off → running as SHADOW")
        active = active + live
    if not active:
        return {"combos": 0, "new": 0, "resolved": 0}

    from connectors.pair_collector import _broker_map
    bmap = _broker_map()

    n_new = n_res = ok = 0
    for algo_id, symbol in active:
        try:
            broker = bmap.get(symbol, symbol)
            _algo = _reg.get(algo_id)
            bars = _bars(broker, getattr(_algo, "timeframe", "H1"))
            if bars is None:
                continue
            point, digits = _symbol_meta(broker)
            if point is None:
                continue
            r = _apply(algo_id, symbol, bars, point, digits, _cost.cost_pips(symbol), max_hold)
            n_new += r["new"]; n_res += r["resolved"]; ok += 1
        except Exception as e:
            logger.debug(f"[SHADOW] {algo_id}:{symbol} fail-soft: {e}")
    if n_new or n_res:
        logger.info(f"[SHADOW] tick: combos={ok}/{len(active)} new={n_new} resolved={n_res}")
    return {"combos": ok, "new": n_new, "resolved": n_res}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa: F401 (load .env)
    r = tick(force=True)
    print("shadow tick:", r)
