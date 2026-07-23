"""agents/shadow_resolve.py — pure, symbol-parameterized signal→outcome resolver (Batch B, T-01).

Generalizes agents/algo_journal._resolve / _close so the same battle-tested logic works for ANY
symbol: the gold-specific POINT (0.01) and COST_PIPS (30) become parameters. No I/O, no config, no
MT5, no numpy — a pure function over price arrays, so it is trivially unit-testable and reused by the
multi-pair shadow engine.

Contract (frozen — docs/ARCHITECTURE_batchB.md §4.5):
  resolve_signal(rec, high, low, close, times, *, point, cost_pips, max_hold_bars, price_digits=2)
    → NEW outcome dict (terminal result TP/SL/TIMEOUT, or running result OPEN),
      or None when the signal bar is out of the current bar window (caller keeps prior state).

Rules (identical to algo_journal, verified bit-for-bit by tests/test_shadow_resolve.py):
  · resolve only from the bar AFTER the signal bar (no look-ahead)
  · SL-first on ambiguous bars: if a bar touches both SL and TP → assume SL (pessimistic)
  · TIMEOUT at max_hold_bars → mark-to-market on that bar's close
  · realized_R = r_gross − cost_pips / sl_pips   (cost subtracted once, at close)
  · MFE/MAE accumulated in R units across every walked bar
Only outcome["resolved_at"] is wall-clock (non-deterministic); everything else is pure.
"""
from datetime import datetime, timezone


def _iso(ts):
    """unix epoch → UTC ISO string, or None if unrepresentable."""
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _close_outcome(result, r_gross, bars, exit_px, exit_ts, mfe, mae, sl_pips, cost_pips, price_digits):
    """Build a terminal outcome dict (mirrors algo_journal._close, parameterized)."""
    cost_R = cost_pips / sl_pips if sl_pips else 0.0
    return {
        "result": result,
        "realized_R": round(r_gross - cost_R, 3),        # net of cost
        "realized_R_gross": round(r_gross, 3),
        "bars_held": int(bars),
        "mfe_R": round(mfe, 3), "mae_R": round(mae, 3),
        "exit_px": round(float(exit_px), price_digits), "exit_ts": _iso(exit_ts),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_signal(rec, high, low, close, times, *,
                   point, cost_pips, max_hold_bars, price_digits=2):
    """Resolve one shadow/journal record against forward bars. Pure. See module docstring.

    rec must carry: entry, dir ("BUY"/"SELL"), sl_pips, tp_pips, bar_ts (ISO of the signal bar).
    rec["outcome"] (if present) seeds the running MFE/MAE. Returns the NEW outcome dict, or None
    when the signal bar is not in `times` (out of window) or sl_pips is non-positive.
    """
    dir_ = rec["dir"]
    sl_pips = rec["sl_pips"]
    risk = sl_pips * point
    if risk <= 0:
        return None
    entry = rec["entry"]
    sign = 1 if dir_ == "BUY" else -1
    sl = entry - sign * sl_pips * point
    tp = entry + sign * rec["tp_pips"] * point

    # locate the signal bar in the current window by matching bar_ts
    i0 = None
    for k in range(len(times)):
        if _iso(times[k]) == rec["bar_ts"]:
            i0 = k
            break
    if i0 is None:
        return None                                      # signal bar fell out of window → caller keeps state

    prev = rec.get("outcome") or {}
    mfe = prev.get("mfe_R", 0.0) or 0.0
    mae = prev.get("mae_R", 0.0) or 0.0
    for j in range(i0 + 1, len(close)):                  # bar AFTER the signal onward
        hi, lo = float(high[j]), float(low[j])
        fav = (hi - entry) if dir_ == "BUY" else (entry - lo)
        adv = (entry - lo) if dir_ == "BUY" else (hi - entry)
        mfe = max(mfe, fav / risk)
        mae = min(mae, -adv / risk)
        hit_sl = (lo <= sl) if dir_ == "BUY" else (hi >= sl)
        hit_tp = (hi >= tp) if dir_ == "BUY" else (lo <= tp)
        if hit_sl and hit_tp:                            # ambiguous bar → SL-first (pessimistic)
            return _close_outcome("SL", -1.0, j - i0, close[j], times[j], mfe, mae, sl_pips, cost_pips, price_digits)
        if hit_sl:
            return _close_outcome("SL", -1.0, j - i0, close[j], times[j], mfe, mae, sl_pips, cost_pips, price_digits)
        if hit_tp:
            return _close_outcome("TP", rec["tp_pips"] / sl_pips, j - i0, close[j], times[j], mfe, mae, sl_pips, cost_pips, price_digits)
        if (j - i0) >= max_hold_bars:
            r_gross = sign * (float(close[j]) - entry) / risk
            return _close_outcome("TIMEOUT", r_gross, j - i0, close[j], times[j], mfe, mae, sl_pips, cost_pips, price_digits)

    # not resolved — running OPEN with current MFE/MAE
    return {"result": "OPEN", "bars_held": len(close) - 1 - i0,
            "mfe_R": round(mfe, 3), "mae_R": round(mae, 3)}
