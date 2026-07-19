#!/usr/bin/env python
"""
regime_analytics.py — dashboard Analytics: "regime ไหนของทองเหมาะกับ algo ไหน" + score + สรุปรายสัปดาห์.

2 ชั้น (display-only, 0 LLM — คำนวณในโค้ด ตาม cost discipline):
  1. HISTORICAL — รัน P2 gauntlet (intrabar+cost) บน xau_h1.json → per-regime WR/expR/Sharpe/PSR + **score 0-100**
     (score = สื่อว่า regime นั้น "เทรดได้จริงแค่ไหน"; honest — ตอนนี้ทุกตัว −EV → เกรด C)
  2. WEEKLY LIVE — อ่าน logs/regime_shadow.jsonl → per ISO-week × regime: bar count + signal count
     (ว่างจนกว่าจะเปิด REGIME_SHADOW=true บน VM แล้วบอทเก็บสด)

เขียน data/regime_analytics.json → dashboard /api/regime-analytics อ่าน pass-through.
รัน:  python scripts\\regime_analytics.py   (schedule รายวันผ่าน refresh_dashboard_data / Task Scheduler)
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

COST_PIPS = 30                       # mid ของ sensitivity grid
OUT = os.path.join(_BASE, "data", "regime_analytics.json")
SHADOW_LOG = os.path.join(_BASE, "logs", "regime_shadow.jsonl")


def _score(exp_r):
    """expR → score 0-100 (50 = breakeven; +0.25R→100, −0.25R→0). honest: −EV จะได้ <50."""
    return int(max(0, min(100, round(50 + 200 * exp_r))))


def _grade(score):
    return "A" if score >= 60 else ("B" if score >= 50 else "C")


def compute_historical(tf="h1"):
    """P2 gauntlet ต่อ regime → score. RISK-OFF/NEUTRAL = STAND-DOWN (ไม่มี trade)."""
    p = os.path.join(_BASE, "data", f"xau_{tf}.json")
    rows = json.load(open(p))
    high = np.array([r[2] for r in rows]); low = np.array([r[3] for r in rows]); close = np.array([r[4] for r in rows])
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)

    # regime frequency (ทองอยู่สภาพไหนบ่อยแค่ไหน)
    reg_count = Counter(); start = max(R.VOL_LOOKBACK, R.BRK_WIN, R.ER_WIN) + 2
    for i in range(start, len(close) - 1):
        reg_count[R.route(i, high, low, close, atr_v, er, adx_v, volpct)[0]] += 1
    total = sum(reg_count.values())

    out = []
    for regime in ("TREND", "RANGE", "RISK-OFF", "NEUTRAL"):
        algo = R.REGIME_ALGO.get(regime, "STAND-DOWN")
        freq = round(reg_count[regime] / total * 100, 1) if total else 0
        row = {"regime": regime, "algo": algo, "freq_pct": freq}
        if algo == "STAND-DOWN":
            row.update({"n": 0, "score": None, "grade": "—",
                        "note": "ยืนดู (ไม่เทรด) — ทอง high-vol/ไร้ทิศ = −EV"})
        else:
            trades = BT.run_algo(algo, high, low, close, atr_v, er, adx_v, volpct)
            s = BT.summarize(algo, trades, COST_PIPS)
            sc = _score(s["exp_R"])
            row.update({"n": s["n"], "wr": round(s["wr"], 3), "exp_R": round(s["exp_R"], 3),
                        "sharpe": round(s["sharpe"], 3),
                        "psr0": round(s["psr0"], 3) if s["psr0"] == s["psr0"] else None,
                        "breakeven_wr": round(1 / (1 + s["avg_win"] / abs(s["avg_loss"])), 3) if s["avg_loss"] else None,
                        "score": sc, "grade": _grade(sc),
                        "note": "มี edge" if sc >= 50 else "ยังไม่มี edge (−EV หลัง cost)"})
        out.append(row)
    return {"bars": len(close), "cost_pips": COST_PIPS, "regimes": out}


def compute_weekly_live():
    """อ่าน shadow log → per ISO-week × regime: bars + signals. ว่าง = ยังไม่เปิด REGIME_SHADOW."""
    if not os.path.exists(SHADOW_LOG):
        return {"weeks": [], "note": "ยังไม่มี shadow data — เปิด REGIME_SHADOW=true บน VM เพื่อเริ่มเก็บ"}
    weeks = defaultdict(lambda: defaultdict(lambda: {"bars": 0, "signals": 0}))
    n = 0
    with open(SHADOW_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = rec.get("bar_ts") or rec.get("ts")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            wk = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
            reg = rec.get("regime", "?")
            weeks[wk][reg]["bars"] += 1
            if rec.get("signal"):
                weeks[wk][reg]["signals"] += 1
            n += 1
    out = [{"week": wk, **{r: dict(v) for r, v in regs.items()}} for wk, regs in sorted(weeks.items())]
    return {"weeks": out[-8:], "total_bars_logged": n,
            "note": "shadow track record (ยังไม่ forward-label outcome — P-next)"}


def build_report():
    hist = compute_historical()
    tradeable = [r for r in hist["regimes"] if r.get("score") is not None and r["score"] >= 50]
    verdict = ("มี regime ที่มี edge: " + ", ".join(r["regime"] for r in tradeable)) if tradeable \
        else "ยังไม่มี regime ไหนมี edge (ทุกตัว −EV หลัง cost) — เก็บ shadow ต่อก่อน flip live"
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "instrument": "XAUUSD H1",
        "historical": hist,
        "weekly": compute_weekly_live(),
        "verdict": verdict,
    }


def main():
    rep = build_report()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"✅ wrote {OUT}")
    print(f"\nverdict: {rep['verdict']}\n")
    print(f"{'regime':>9} {'algo':>18} {'freq':>5} {'N':>5} {'WR':>6} {'expR':>7} {'score':>5} {'grade':>5}")
    for r in rep["historical"]["regimes"]:
        wr = f"{r['wr']*100:.1f}%" if "wr" in r else "—"
        ex = f"{r['exp_R']:+.3f}" if "exp_R" in r else "—"
        sc = r["score"] if r["score"] is not None else "—"
        print(f"{r['regime']:>9} {r['algo']:>18} {r['freq_pct']:>4}% {r.get('n',0):>5} {wr:>6} {ex:>7} {str(sc):>5} {r['grade']:>5}")
    wk = rep["weekly"]
    print(f"\nweekly: {len(wk['weeks'])} weeks logged — {wk['note']}")


if __name__ == "__main__":
    main()
