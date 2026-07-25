"""scripts/backtest_segment.py — หาว่า "คู่ที่ติดลบ" ทำกำไรใน สภาวะตลาด แบบไหน (segment by condition).

รัน managed backtest (paper order ผ่าน BE+trailing = process จริง) แล้ว tag แต่ละไม้ด้วย condition ตอน entry
(ADX/trend strength · vol percentile · efficiency ratio · session · direction) → แบ่ง bucket → รายงาน
เฉพาะ segment ที่ +exp_R (ส่วนที่เป็นกำไร). READ-ONLY. เขียน docs/reports/backtest_segment.md

⚠️ ระวัง small-n positive (multiple-testing) → รายงาน n ทุก bucket, เชื่อ n มากกว่า. รัน: python scripts/backtest_segment.py
"""
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
sys.path.insert(0, _BASE)

import config  # noqa: E402,F401
import regime_lib as R                                   # noqa: E402
import shadow_backtest as SB                             # noqa: E402
from agents.shadow_resolve_managed import resolve_managed  # noqa: E402
from agents import shadow_cost as SC                     # noqa: E402
from connectors.pair_collector import _broker_map, COLLECT  # noqa: E402

_MIN_N = 15                                              # bucket ต่ำกว่านี้ = noise (ไม่รายงานเป็นกำไรจริง)


def _buckets(adx, volpct, er, hour, direction):
    """คืน list ของ (axis, label) ที่ไม้นี้ตกอยู่."""
    b = []
    b.append(("ADX", "strong ADX≥28" if adx >= 28 else ("mod ADX20-28" if adx >= 20 else "weak ADX<20")))
    b.append(("vol", "high vol≥0.7" if volpct >= 0.7 else ("mid vol0.4-0.7" if volpct >= 0.4 else "low vol<0.4")))
    b.append(("trend", "clean ER≥0.5" if er >= 0.5 else ("mixed ER0.3-0.5" if er >= 0.3 else "choppy ER<0.3")))
    sess = "Asian 0-7" if hour < 7 else ("London 7-13" if hour < 13 else ("NY 13-20" if hour < 20 else "late 20-24"))
    b.append(("session", sess))
    b.append(("dir", direction))
    return b


def segment_pair(logical, broker):
    got = SB._fetch(broker)
    if got is None:
        return None
    rates, point, digits = got
    if point is None:
        return None
    high = rates["high"].astype(float); low = rates["low"].astype(float)
    close = rates["close"].astype(float); times = rates["time"]
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    cost_pips = SC.cost_pips(logical)
    n = len(close); flat_until = -1
    trades = []
    for i in range(SB._MIN_BARS, n - 1):
        regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct, point=point)
        if not sig or sig.get("algo") != "momentum_breakout":
            continue
        if i <= flat_until:
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]), "sl_pips": sig["sl_pips"],
               "tp_pips": sig["tp_pips"], "bar_ts": SB._iso(times[i])}
        out = resolve_managed(rec, high, low, close, times, atr_v, point=point, cost_pips=cost_pips,
                              max_hold_bars=SB.MAX_HOLD, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":
            break
        hour = datetime.fromtimestamp(int(times[i]), timezone.utc).hour
        trades.append({"R": out["realized_R"],
                       "buckets": _buckets(float(adx_v[i]), float(volpct[i]), float(er[i]), hour, sig["dir"])})
        flat_until = i + out["bars_held"]
    return trades


def _seg_stats(trades):
    """{axis: {label: [n, sum_R]}} รวมทุก bucket."""
    agg = {}
    for t in trades:
        for axis, label in t["buckets"]:
            a = agg.setdefault(axis, {}).setdefault(label, [0, 0.0])
            a[0] += 1; a[1] += t["R"]
    return agg


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    bmap = _broker_map()
    L = ["# Backtest Segmentation — คู่ติดลบ ทำกำไรใน สภาวะตลาด แบบไหน (regime_momentum, managed)\n"]
    L.append(f"_generated {datetime.now(timezone.utc).isoformat()[:16]}Z · paper order + BE/trailing · "
             f"รายงานเฉพาะ segment +exp_R (n≥{_MIN_N}) · เชื่อ n มาก > slice บวก n น้อย_\n")
    for logical in COLLECT:
        broker = bmap.get(logical, logical)
        print(f"  · segment {logical} …", flush=True)
        trades = segment_pair(logical, broker)
        if not trades:
            continue
        total = sum(t["R"] for t in trades)
        agg = _seg_stats(trades)
        # profitable segments เรียงตาม sum_R
        prof = []
        for axis, labels in agg.items():
            for label, (n, sr) in labels.items():
                if sr > 0 and n >= _MIN_N:
                    prof.append((axis, label, n, sr, sr / n))
        prof.sort(key=lambda x: -x[3])
        tag = "ทั้งคู่ +EV" if total > 0 else "ทั้งคู่ −EV"
        L.append(f"\n## {logical}  (รวม n={len(trades)} sum_R={total:+.1f} · {tag})\n")
        if not prof:
            L.append("- ไม่มี segment ไหน +exp_R ที่ n เพียงพอ (คู่นี้ไม่มีสภาวะกำไรชัด)\n")
            continue
        L.append("| สภาวะตลาด (segment) | n | exp_R | sum_R |")
        L.append("|---|--:|--:|--:|")
        for axis, label, n, sr, ex in prof:
            L.append(f"| **{label}** ({axis}) | {n} | {ex:+.3f} | {sr:+.1f} |")
    mt5.shutdown()
    out = os.path.join(_BASE, "docs", "reports", "backtest_segment.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
