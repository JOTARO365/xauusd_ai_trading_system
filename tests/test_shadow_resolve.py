"""tests/test_shadow_resolve.py — T-01 gate: prove shadow_resolve.resolve_signal reproduces the
battle-tested agents/algo_journal._resolve BIT-FOR-BIT on XAUUSD (point=0.01, cost_pips=30, max_hold=48),
plus symbol-general sanity for a non-gold pair.

Run standalone (no pytest needed): python tests/test_shadow_resolve.py   → prints PASS/FAIL, exit 1 on fail.
Also pytest-discoverable (test_* functions).

Parity comparison excludes outcome["resolved_at"] (wall-clock, non-deterministic by design).
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import algo_journal as AJ          # reference implementation
from agents.shadow_resolve import resolve_signal, _iso

H = 3600
T0 = 1_700_000_000

# gold params = algo_journal module constants (so parity is against the exact live config)
GOLD = dict(point=AJ.POINT, cost_pips=AJ.COST_PIPS, max_hold_bars=AJ.MAX_HOLD_BARS)


def _times(n):
    return [T0 + k * H for k in range(n)]


def _rec(dir_, entry=2000.0, sl_pips=100, tp_pips=200, i0=2):
    return {"kind": "signal", "dir": dir_, "entry": entry,
            "sl_pips": sl_pips, "tp_pips": tp_pips, "bar_ts": _iso(T0 + i0 * H)}


def _strip(o):
    """drop the wall-clock field for deterministic comparison."""
    if not isinstance(o, dict):
        return o
    return {k: v for k, v in o.items() if k != "resolved_at"}


def _parity(name, rec, high, low, close, times, params=GOLD):
    """Assert resolve_signal == algo_journal._resolve on the same inputs (minus resolved_at)."""
    ref_rec = copy.deepcopy(rec)
    changed = AJ._resolve(ref_rec, high, low, close, times)   # mutates ref_rec["outcome"], returns bool
    ref_out = ref_rec.get("outcome")

    mine = resolve_signal(copy.deepcopy(rec), high, low, close, times, **params)

    # out-of-window / non-resolvable: reference returns False and leaves no/prior outcome; mine returns None
    if mine is None:
        assert changed is False, f"[{name}] mine=None but reference changed=True (out={ref_out})"
        assert ref_out is None, f"[{name}] mine=None but reference set outcome={ref_out}"
        print(f"  PASS {name} (no-resolve: both decline)")
        return

    assert _strip(mine) == _strip(ref_out), (
        f"[{name}] MISMATCH\n   mine={_strip(mine)}\n    ref={_strip(ref_out)}")
    # if terminal, both must carry a resolved_at stamp
    if mine.get("result") in ("TP", "SL", "TIMEOUT"):
        assert "resolved_at" in mine and "resolved_at" in (ref_out or {}), f"[{name}] missing resolved_at"
    print(f"  PASS {name} → {mine['result']} realized_R={mine.get('realized_R')}")


# ── scenarios: each crafts forward bars to force one resolution path ──────────

def test_buy_tp():
    t = _times(6); i0 = 2
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    hi[3] = 2002.5; cl[3] = 2002.2                    # >= tp 2002, no SL touch → TP
    _parity("BUY_TP", _rec("BUY", i0=i0), hi, lo, cl, t)


def test_buy_sl():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    lo[3] = 1998.5; cl[3] = 1998.7                    # <= sl 1999, no TP → SL
    _parity("BUY_SL", _rec("BUY"), hi, lo, cl, t)


def test_buy_ambiguous_sl_first():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    hi[3] = 2002.5; lo[3] = 1998.5; cl[3] = 2001.0    # touches BOTH → SL-first
    _parity("BUY_AMBIGUOUS", _rec("BUY"), hi, lo, cl, t)


def test_buy_timeout():
    n = 2 + 1 + AJ.MAX_HOLD_BARS + 1                  # ensure j-i0 reaches MAX_HOLD_BARS
    t = _times(n)
    hi = [2000.5] * n; lo = [1999.5] * n; cl = [2000.3] * n   # never hits sl 1999 / tp 2002
    _parity("BUY_TIMEOUT", _rec("BUY"), hi, lo, cl, t)


def test_buy_open_running():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.1] * 6   # no hit, < max_hold → OPEN
    _parity("BUY_OPEN", _rec("BUY"), hi, lo, cl, t)


def test_sell_tp():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    lo[3] = 1997.5; cl[3] = 1997.8                    # SELL entry 2000, tp 1998 → hit, sl 2001 not touched
    _parity("SELL_TP", _rec("SELL"), hi, lo, cl, t)


def test_sell_sl():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    hi[3] = 2001.5; cl[3] = 2001.2                    # SELL sl 2001 hit
    _parity("SELL_SL", _rec("SELL"), hi, lo, cl, t)


def test_out_of_window():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    rec = _rec("BUY"); rec["bar_ts"] = _iso(T0 - H)   # bar_ts not present in times → cannot resolve
    _parity("OUT_OF_WINDOW", rec, hi, lo, cl, t)


def test_zero_risk():
    t = _times(6)
    hi = [2000.5] * 6; lo = [1999.5] * 6; cl = [2000.0] * 6
    _parity("ZERO_RISK", _rec("BUY", sl_pips=0), hi, lo, cl, t)   # risk<=0 → both decline


def test_symbol_general_eurusd():
    """Non-gold parameterization: point=1e-5, its own cost, price_digits=5. (No AJ parity — AJ is gold-only.)"""
    t = _times(6); i0 = 2
    entry = 1.08000; sl_pips = 100; tp_pips = 200            # risk = 100*1e-5 = 0.001
    rec = {"kind": "signal", "dir": "BUY", "entry": entry, "sl_pips": sl_pips,
           "tp_pips": tp_pips, "bar_ts": _iso(T0 + i0 * H)}
    hi = [1.08010] * 6; lo = [1.07990] * 6; cl = [1.08000] * 6
    hi[3] = 1.08250; cl[3] = 1.08220                        # >= tp 1.082 → TP
    out = resolve_signal(rec, hi, lo, cl, t, point=1e-5, cost_pips=8, max_hold_bars=48, price_digits=5)
    assert out["result"] == "TP", out
    assert out["realized_R"] == round(2.0 - 8 / 100, 3) == 1.92, out    # tp/sl RR=2, cost 0.08R
    assert out["exit_px"] == 1.0822, out                    # rounded to 5 dp
    print(f"  PASS EURUSD_GENERAL → TP realized_R={out['realized_R']} exit_px={out['exit_px']}")


ALL = [test_buy_tp, test_buy_sl, test_buy_ambiguous_sl_first, test_buy_timeout,
       test_buy_open_running, test_sell_tp, test_sell_sl, test_out_of_window,
       test_zero_risk, test_symbol_general_eurusd]


if __name__ == "__main__":
    print("T-01 parity: shadow_resolve.resolve_signal vs algo_journal._resolve")
    failed = 0
    for fn in ALL:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'ALL PASS' if not failed else f'{failed} FAILED'} ({len(ALL) - failed}/{len(ALL)})")
    sys.exit(1 if failed else 0)
