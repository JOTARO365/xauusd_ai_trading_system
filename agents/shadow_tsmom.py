"""agents/shadow_tsmom.py — Batch B / Phase 2: forward TSMOM-D1 shadow tracker (stateful trend-follower).

The discrete-signal shadow_engine fits fixed-RR momentum-breakout, NOT a no-TP trend-follower that holds
for months. This tracks the TSMOM-D1 ensemble (majority vote L=63/126/252, exit-on-flip) as a daily
mark-to-market EQUITY curve per symbol — the fair metric for trend-following (per scripts/tsmom_equity_screen).

Why forward-only: a broker's long BTC D1 history is data-corrupted (backfilled garbage → equity blows
through −100% in backtest). Real-time forward returns are clean, so this is the only honest way to judge
BTC (and to sanity-track gold/silver TSMOM). 0 order, 0 token, flag-gated (SHADOW_TSMOM), fail-soft.
Does NOT touch the live tsmom_manager. Reuses its exact signal.

Log (append-only): logs/shadow/tsmom__<symbol>.jsonl, one record per closed D1 bar:
  { ts, symbol, close, sig_prev, sig_now, pos, ret, cost_applied }   ret = daily mark-to-market, net turnover cost.
Judge via summary(): annualized Sharpe of the ret series, IS/OOS, maxDD, equity.
"""
import json
import os
import sys
from datetime import datetime, timezone

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)

LOOKBACKS = [63, 126, 252]
_LOGDIR = os.path.join(_BASE, "logs", "shadow")
_PROBE = os.path.join(_BASE, "data", "universe_probe.json")
_DEFAULT_UNIVERSE = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD", "USDCHF", "USDJPY",
                     "BTCUSD", "WTIUSD"]                  # ทุกคู่ (data collection; gold = validated ref)


def _iso(ts):
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _logpath(symbol):
    return os.path.join(_LOGDIR, f"tsmom__{symbol}.jsonl")


def _read(path):
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


def _append(path, recs):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _sig(close, i):
    """TSMOM ensemble position at closed bar i (mirrors tsmom_manager._signal). +1/-1/0."""
    import numpy as np
    v = sum(int(np.sign(close[i] - close[i - L])) for L in LOOKBACKS if i - L >= 0)
    return 1 if v > 0 else (-1 if v < 0 else 0)


def _probe():
    try:
        return json.load(open(_PROBE, encoding="utf-8")).get("instruments", {})
    except Exception:
        return {}


def _bars(broker, count=600):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_D1, 0, count)
    if r is None or len(r) < max(LOOKBACKS) + 5:
        return None
    return r


def _track_symbol(logical, broker, point, spread_pts):
    """Append daily mark-to-market records for every new closed D1 bar since the last logged one.
    Anchors on first run (no backfill of corrupted history). Returns count appended."""
    import numpy as np
    r = _bars(broker)
    if r is None:
        return 0
    close = r["close"].astype(float); times = r["time"]
    n = len(close); last_closed = n - 2                  # n-1 is forming
    if last_closed < max(LOOKBACKS):
        return 0
    path = _logpath(logical)
    rows = _read(path)
    cost_pct = (spread_pts * point) / float(np.median(close)) if point else 0.0

    # find where to resume: index just after the last logged bar; else anchor at last_closed (forward-only)
    start = None
    if rows:
        last_ts = rows[-1].get("ts")
        for k in range(n):
            if _iso(times[k]) == last_ts:
                start = k + 1
                break
    if start is None:                                    # empty log or last ts fell out of window → anchor
        anchor = last_closed
        _append(path, [{"ts": _iso(times[anchor]), "symbol": logical, "close": round(float(close[anchor]), 2),
                        "sig_prev": None, "sig_now": _sig(close, anchor), "pos": _sig(close, anchor),
                        "ret": None, "cost_applied": 0.0, "anchor": True}])
        return 0

    recs = []
    for i in range(start, last_closed + 1):
        if close[i - 1] <= 0:
            continue
        sp = _sig(close, i - 1); sn = _sig(close, i)
        turn = abs(sn - sp)
        ret = sp * (close[i] / close[i - 1] - 1.0) - turn * cost_pct
        recs.append({"ts": _iso(times[i]), "symbol": logical, "close": round(float(close[i]), 2),
                     "sig_prev": sp, "sig_now": sn, "pos": sn, "ret": round(ret, 6),
                     "cost_applied": round(turn * cost_pct, 6)})
    if recs:
        _append(path, recs)
    return len(recs)


def tick(force=False):
    """Every-cycle entry (called after shadow_engine.tick). Gated by SHADOW_TSMOM. fail-soft; 0 order."""
    import config as _cfg
    if not force and not getattr(_cfg, "SHADOW_TSMOM", False):
        return None
    uni = getattr(_cfg, "SHADOW_TSMOM_UNIVERSE", None) or _DEFAULT_UNIVERSE
    try:
        from connectors.pair_collector import _broker_map
        bmap = _broker_map()
        import MetaTrader5 as mt5
    except Exception:
        return None
    probe = _probe()
    total = 0
    for logical in uni:
        try:
            broker = bmap.get(logical, logical)
            info = mt5.symbol_info(broker)
            if info is None or not info.point:
                continue
            sp = int((probe.get(logical) or {}).get("spread_points") or 0)
            total += _track_symbol(logical, broker, float(info.point), sp)
        except Exception as e:
            logger.debug(f"[SHADOW-TSMOM] {logical} fail-soft: {e}")
    if total:
        logger.info(f"[SHADOW-TSMOM] +{total} daily bar(s) across {len(uni)} symbols")
    return {"symbols": len(uni), "new_bars": total}


def summary():
    """Per-symbol forward TSMOM equity stats (annualized Sharpe, IS/OOS, maxDD). Import-safe, fail-soft."""
    import config as _cfg
    import numpy as np
    uni = getattr(_cfg, "SHADOW_TSMOM_UNIVERSE", None) or _DEFAULT_UNIVERSE
    out = []
    for logical in uni:
        rows = [r for r in _read(_logpath(logical)) if r.get("ret") is not None]
        rets = np.array([r["ret"] for r in rows], dtype=float)
        row = {"symbol": logical, "n_days": len(rets), "pos": (rows[-1]["pos"] if rows else None)}
        if len(rets) >= 30:
            sd = float(rets.std(ddof=1))
            sr = float(rets.mean()) / sd * np.sqrt(252) if sd > 0 else 0.0
            cut = int(len(rets) * 0.6)

            def _s(x):
                s = float(x.std(ddof=1)) if len(x) > 1 else 0.0
                return round(float(x.mean()) / s * np.sqrt(252), 2) if s > 0 else 0.0
            eq = np.cumprod(1 + rets); peak = np.maximum.accumulate(eq)
            row.update({"sharpe": round(sr, 2), "sr_is": _s(rets[:cut]), "sr_oos": _s(rets[cut:]),
                        "equity": round(float(eq[-1]), 3),
                        "maxdd_pct": round(float(((eq - peak) / peak).min()) * 100, 1),
                        "since": rows[0]["ts"][:10] if rows else None})
        else:
            row["note"] = f"collecting {len(rets)}/30 D1 bars (Sharpe จะขึ้นเมื่อครบ)"
        out.append(row)
    return {"ok": True, "generated": datetime.now(timezone.utc).isoformat()[:16] + "Z",
            "engine_on": getattr(_cfg, "SHADOW_TSMOM", False), "rows": out,
            "note": "forward mark-to-market TSMOM-D1 equity (clean, no backfill). Sharpe annualized; "
                    "judge on OOS>0 + Sharpe. Promotion to LIVE = manual + Batch D."}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa: F401
    print("tick:", tick(force=True))
    import json as _j
    print(_j.dumps(summary(), ensure_ascii=False, indent=2))
