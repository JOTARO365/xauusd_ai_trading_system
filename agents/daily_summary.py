"""agents/daily_summary.py — สรุปเทรดรายวัน: เทคนิค · สภาพตลาด · กำไร/ขาดทุน · ทำไมเข้า · ทำไมขาดทุน. 0 token.

รวมไม้จาก logs/trades.json (MANUAL owner + legacy system + ALGO) → aggregate ต่อวัน. attribute technique +
regime จาก entry_type/comment; why-loss จาก heuristic (counter-trend / สวน sentiment / conf ต่ำ / SL).
ALGO trades enrich regime/exit จาก entry_type (ALGO-mom=TREND momentum / ALGO-PF=RANGE fade). display-only.

CLI: python agents/daily_summary.py   ·   dashboard: /api/daily-summary (analytics tab)
"""
import json
import os
from collections import defaultdict, Counter

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# entry_type / comment → (technique, regime-hint)
_TECH = {
    "ALGO-mom": ("Momentum breakout", "TREND"),
    "ALGO-P": ("Momentum breakout (pending)", "TREND"),
    "ALGO-PF": ("Fade S/R (pending)", "RANGE"),
    "SR_ZONE": ("S/R zone", "RANGE"),
    "EMA_PULLBACK": ("EMA pullback", "TREND"),
    "PENDING": ("Pending", "—"),
    "MANUAL": ("Manual (owner)", "—"),
}


def _tech(t):
    """technique + regime-hint จาก comment (ALGO) หรือ entry_type."""
    cmt = str(t.get("comment") or "")
    for k, v in _TECH.items():
        if cmt.startswith(k):
            return v
    return _TECH.get(t.get("entry_type"), (t.get("entry_type") or "unknown", "—"))


def _why_loss(t):
    """heuristic ว่าทำไมขาดทุน (จาก field ที่มี). คืน str สั้น."""
    d = str(t.get("direction") or "").upper()
    trend = str(t.get("trend") or "").upper()
    sent = str(t.get("sentiment") or "").upper()
    conf = t.get("technical_confidence")
    reasons = []
    if trend and ((d == "BUY" and "BEAR" in trend) or (d == "SELL" and "BULL" in trend)):
        reasons.append("สวนเทรนด์")
    if sent and ((d == "BUY" and "BEAR" in sent) or (d == "SELL" and "BULL" in sent)):
        reasons.append("สวน sentiment")
    if conf is not None and conf < 60:
        reasons.append(f"conf ต่ำ ({conf}%)")
    zone = t.get("sr_zone")
    if zone:
        reasons.append(f"เข้าที่ {zone} ทะลุ")
    return " · ".join(reasons) or "ราคาไปสวนทาง (SL)"


def build_daily_summary(days=30, tech="all"):
    """คืน {days, totals, techniques_all, filter} — สรุปต่อวัน (ล่าสุดก่อน). tech=filter เทคนิค. 0 token, fail-soft."""
    try:
        d = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
        trades = d if isinstance(d, list) else d.get("trades", [])
    except (OSError, json.JSONDecodeError):
        return {"days": [], "totals": {}, "techniques_all": [], "filter": tech}
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None
              and t.get("timestamp")]
    techs_all = sorted({_tech(t)[0] for t in closed})
    if tech and tech != "all":                              # filter เฉพาะเทคนิคที่เลือก
        closed = [t for t in closed if _tech(t)[0] == tech]
    byday = defaultdict(list)
    for t in closed:
        byday[str(t["timestamp"])[:10]].append(t)

    out = []
    for date in sorted(byday, reverse=True)[:days]:
        rows = byday[date]
        pnls = [float(t.get("pnl") or 0) for t in rows]
        wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
        techs = Counter(_tech(t)[0] for t in rows)
        regimes = Counter(_tech(t)[1] for t in rows if _tech(t)[1] != "—")
        trends = Counter(str(t.get("trend") or "").upper() for t in rows if t.get("trend"))
        # ไม้ขาดทุนหนักสุด + เหตุผล
        losers = sorted((t for t in rows if float(t.get("pnl") or 0) <= 0),
                        key=lambda t: float(t.get("pnl") or 0))
        worst = losers[0] if losers else None
        why_agg = Counter(_why_loss(t) for t in losers)
        detail = [{
            "time": str(t.get("timestamp"))[11:16],
            "tech": _tech(t)[0], "dir": t.get("direction"),
            "pnl": round(float(t.get("pnl") or 0), 2),
            "why_in": (t.get("manual_reason") or t.get("entry_type") or "—"),   # ทำไมเข้า
            "why_out": (_why_loss(t) if float(t.get("pnl") or 0) <= 0 else "กำไร (TP/manual)"),  # ทำไมออก/ขาดทุน
        } for t in sorted(rows, key=lambda t: str(t.get("timestamp")))]
        out.append({
            "date": date,
            "n": len(rows), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(rows), 3) if rows else 0,
            "net_pnl": round(sum(pnls), 2),
            "gross_win": round(sum(wins), 2), "gross_loss": round(sum(losses), 2),
            "techniques": dict(techs.most_common()),
            "regime": (regimes.most_common(1)[0][0] if regimes else
                       (trends.most_common(1)[0][0] if trends else "—")),
            "worst": ({"technique": _tech(worst)[0], "pnl": round(float(worst.get("pnl") or 0), 2),
                       "dir": worst.get("direction"), "why": _why_loss(worst)} if worst else None),
            "why_loss": dict(why_agg.most_common(3)),
            "trades": detail,
        })
    tot_pnl = sum(x["net_pnl"] for x in out)
    tot_n = sum(x["n"] for x in out); tot_w = sum(x["wins"] for x in out)
    return {"days": out, "techniques_all": techs_all, "filter": tech,
            "totals": {"n": tot_n, "net_pnl": round(tot_pnl, 2),
                       "win_rate": round(tot_w / tot_n, 3) if tot_n else 0}}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _tf = sys.argv[1] if len(sys.argv) > 1 else "all"     # filter เทคนิค (arg) เช่น "Manual (owner)"
    s = build_daily_summary(tech=_tf)
    print(f"filter: {_tf}  |  เทคนิคที่มี: {', '.join(s.get('techniques_all', []))}\n")
    print(f"{'date':>11} {'n':>3} {'W/L':>6} {'net฿':>9}  {'regime':>7}  technique · why-loss")
    print("-" * 90)
    for x in s["days"][:20]:
        techs = ", ".join(f"{k}×{v}" for k, v in list(x["techniques"].items())[:2])
        why = " / ".join(x["why_loss"].keys()) if x["why_loss"] else ""
        print(f"{x['date']:>11} {x['n']:>3} {x['wins']:>2}/{x['losses']:<2} {x['net_pnl']:>+9.0f}  "
              f"{x['regime']:>7}  {techs}{'  · ' + why if why else ''}")
    t = s["totals"]
    print("-" * 90)
    print(f"รวม {t.get('n')} ไม้ · net {t.get('net_pnl'):+.0f}฿ · WR {t.get('win_rate',0)*100:.0f}%")
