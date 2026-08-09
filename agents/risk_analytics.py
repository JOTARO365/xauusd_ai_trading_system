"""agents/risk_analytics.py — SAT-derived portfolio risk metrics (user 08-09, จาก quant-sat ch12/13).

คำนวณจากไม้ปิดจริง (DB trades → fallback logs/trades.json): equity curve, annualised Sharpe (ch12),
max drawdown + duration + underwater series (ch12), VaR 95/99 historical+parametric (ch13).
display-only · 0 token (compute-in-code) · fail-soft · n<MIN → คืน collecting.

Consumed by /api/risk-sat + /api/equity-curve. Import-safe.
"""
import json
import math
import os
from datetime import datetime

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MIN_N = 15                                   # ต่ำกว่านี้ = ยังเชื่อ metric ไม่ได้ (collecting)


def _closed_trades():
    """ไม้ปิดเรียงตามเวลา: [(dt, pnl)]. DB ก่อน (ประวัติเต็ม) → fallback logs/trades.json."""
    out = []
    try:                                       # DB (ประวัติเต็ม) — get_trades ต่อ symbol ใน universe
        from db.reader import get_trades
        from agents import algo_registry as _reg
        seen = set()
        for lg in getattr(_reg, "UNIVERSE", ["XAUUSD"]):
            for t in (get_trades(symbol=lg) or []):
                if not isinstance(t, dict):
                    continue
                tk = t.get("ticket")
                if tk in seen:
                    continue
                seen.add(tk)
                p = t.get("pnl", t.get("profit"))
                ts = t.get("close_time")
                if p is not None and ts and str(t.get("status", "")).upper() == "CLOSED":
                    out.append((_parse(ts), float(p)))
    except Exception:
        pass
    if len(out) < 2:                           # fallback ไฟล์
        try:
            d = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
            for t in d.get("trades", []):
                if str(t.get("status", "")).upper() == "CLOSED":
                    p = t.get("pnl", t.get("profit"))
                    ts = t.get("close_time") or t.get("timestamp")
                    if p is not None and ts:
                        out.append((_parse(ts), float(p)))
        except Exception:
            pass
    out = [x for x in out if x[0] is not None]
    out.sort(key=lambda z: z[0])
    return out


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _equity_anchor():
    """ยอด balance ปัจจุบัน (anchor equity curve). fallback 10000."""
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            a = mt5.account_info()
            if a:
                return float(a.balance)
    except Exception:
        pass
    return 10000.0


def equity_curve():
    """equity curve + underwater (drawdown over time). คืน list ของ point."""
    tr = _closed_trades()
    if not tr:
        return {"ok": True, "n": 0, "points": [], "note": "ยังไม่มีไม้ปิด"}
    total = sum(p for _, p in tr)
    eq = _equity_anchor() - total              # ย้อนกลับหา balance เริ่มต้น (anchor = ปัจจุบัน)
    pts = []
    run = eq; peak = eq
    for dt, p in tr:
        run += p; peak = max(peak, run)
        dd = (peak - run) / peak * 100 if peak > 0 else 0
        pts.append({"t": dt.isoformat()[:16], "equity": round(run, 2), "dd_pct": round(dd, 2)})
    return {"ok": True, "n": len(tr), "start_equity": round(eq, 2), "points": pts}


def _var(pnls, conf):
    """historical + parametric VaR (บาท, ค่าบวก=ขาดทุนคาด). ch13."""
    if not pnls:
        return None, None
    import numpy as np
    a = np.array(pnls, float)
    hist = -float(np.percentile(a, (1 - conf) * 100))          # historical percentile
    z = 1.645 if conf == 0.95 else 2.326
    param = -(float(a.mean()) - z * float(a.std(ddof=1) if len(a) > 1 else 0))
    return round(max(hist, 0), 2), round(max(param, 0), 2)


def summary():
    """SAT risk summary: Sharpe (ch12) · maxDD+duration (ch12) · VaR (ch13). fail-soft."""
    try:
        import numpy as np
        tr = _closed_trades()
        n = len(tr)
        if n < _MIN_N:
            return {"ok": True, "n": n, "min_n": _MIN_N, "collecting": True,
                    "note": "เก็บไม้ปิด %d/%d ก่อนคำนวณ metric เชื่อถือได้" % (n, _MIN_N)}
        pnls = [p for _, p in tr]
        anchor = _equity_anchor(); eq0 = anchor - sum(pnls)
        # per-trade return (fraction ของ equity ก่อนไม้นั้น) → Sharpe
        rets = []; run = eq0
        for p in pnls:
            rets.append(p / run if run > 0 else 0.0); run += p
        r = np.array(rets, float)
        # annualise: ประมาณไม้/ปี จากช่วงเวลาจริง
        span_days = max(1.0, (tr[-1][0] - tr[0][0]).total_seconds() / 86400)
        tr_per_year = n / span_days * 365.25
        sharpe = (float(r.mean()) / float(r.std(ddof=1)) * math.sqrt(tr_per_year)) if r.std() > 0 else 0.0
        # max drawdown + duration จาก equity curve
        run = eq0; peak = eq0; maxdd = 0.0; dd_start = tr[0][0]; worst_dur = 0.0; cur_start = None
        for (dt, p) in tr:
            run += p
            if run >= peak:
                peak = run; cur_start = None
            else:
                if cur_start is None:
                    cur_start = dt
                dur = (dt - cur_start).total_seconds() / 86400
                worst_dur = max(worst_dur, dur)
            dd = (peak - run) / peak if peak > 0 else 0
            maxdd = max(maxdd, dd)
        v95h, v95p = _var(pnls, 0.95); v99h, v99p = _var(pnls, 0.99)
        wins = sum(1 for p in pnls if p > 0)
        return {"ok": True, "n": n, "collecting": False,
                "sharpe": round(sharpe, 2), "trades_per_year": round(tr_per_year, 0),
                "max_dd_pct": round(maxdd * 100, 1), "max_dd_days": round(worst_dur, 1),
                "var95_hist": v95h, "var95_param": v95p, "var99_hist": v99h, "var99_param": v99p,
                "total_pnl": round(sum(pnls), 2), "wr": round(wins / n * 100, 1),
                "span_days": round(span_days, 0),
                "note": "SAT ch12/13 · net ไม้ปิดจริง · VaR สมมติ normal (understate tail) → ดู maxDD ควบ"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
