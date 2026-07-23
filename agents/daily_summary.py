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
    "ALGO-TSMOM": ("TSMOM-D1 (momentum รายวัน)", "TREND"),
    "ALGO-mom": ("Momentum breakout", "TREND"),
    "ALGO-P": ("Momentum breakout (pending)", "TREND"),
    "ALGO-PF": ("Fade S/R (pending)", "RANGE"),
    "SR_ZONE": ("S/R zone", "RANGE"),
    "EMA_PULLBACK": ("EMA pullback", "TREND"),
    "PENDING": ("Pending", "—"),
    "MANUAL": ("Manual (owner)", "—"),
}


def _tech(t):
    """technique + regime-hint จาก comment (ALGO) หรือ entry_type. เช็ค prefix ยาวก่อน (ALGO-PF ก่อน ALGO-P)."""
    cmt = str(t.get("comment") or "")
    for k in sorted(_TECH, key=len, reverse=True):
        if cmt.startswith(k):
            return _TECH[k]
    return _TECH.get(t.get("entry_type"), (t.get("entry_type") or "unknown", "—"))


def _why_loss(t):
    """heuristic ว่าทำไมขาดทุน (จาก field ที่มี). คืน str สั้น."""
    if str(t.get("source")) == "ALGO":                     # ALGO: infer จาก technique
        cmt = str(t.get("comment") or "")
        if "PF" in cmt or "fade" in cmt.lower():
            return "fade แนว S/R — ราคาทะลุ (SL) [−EV per gauntlet]"
        return "momentum breakout ล้มเหลว/reverse (SL)"
    d = str(t.get("direction") or "").upper()
    trend = str(t.get("trend") or "").upper()
    sent = str(t.get("sentiment") or "").upper()
    conf = t.get("technical_confidence")
    reasons = []
    if trend and ((d == "BUY" and "BEAR" in trend) or (d == "SELL" and "BULL" in trend)):
        reasons.append("สวนทางเทรนด์")
    if sent and ((d == "BUY" and "BEAR" in sent) or (d == "SELL" and "BULL" in sent)):
        reasons.append("สวนทาง sentiment")
    if conf is not None and conf < 60:
        reasons.append(f"conf ต่ำ ({conf}%)")
    zone = t.get("sr_zone")
    if zone:
        reasons.append(f"เข้าที่ {zone} ทะลุ")
    return " · ".join(reasons) or "ราคาเคลื่อนสวนทาง (SL)"


def _live_floating():
    """{ticket: floating P/L} จาก MT5 (สำหรับไม้ OPEN). fail-soft → {}."""
    try:
        from connectors.mt5_connector import get_open_positions
        return {p.get("ticket"): float(p.get("profit") or 0) for p in (get_open_positions() or [])}
    except Exception:
        return {}


def _mt5_state(days):
    """(open_tickets:set, realized:{position_id: pnl}, ok:bool) — reconcile trades.json ที่ status ค้าง
    กับ MT5 จริง: ไม้ที่ trades.json บอก OPEN แต่ไม่มีใน positions = ปิดไปแล้ว (reporter ไม่อัปเดต).
    ok=False ถ้า MT5 ต่อไม่ได้ (อย่า reconcile กัน false-close). realized จาก deal history."""
    open_t, realized, ok = set(), {}, False
    try:
        import MetaTrader5 as mt5
        from datetime import datetime, timedelta
        from collections import defaultdict
        if not mt5.initialize():
            return open_t, realized, False
        pos = mt5.positions_get()
        if pos is not None:
            open_t = {p.ticket for p in pos}
            ok = True
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=days), datetime.now()) or []
        agg = defaultdict(lambda: {"pnl": 0.0, "closed": False})
        for d in deals:
            a = agg[d.position_id]
            a["pnl"] += d.profit + d.swap + d.commission
            if d.entry in (1, 2):
                a["closed"] = True
        realized = {pid: round(a["pnl"], 2) for pid, a in agg.items() if a["closed"]}
    except Exception:
        pass
    return open_t, realized, ok


def _algo_trades_from_mt5(days=45):
    """ดึงไม้ ALGO (comment 'ALGO*') จาก MT5 — closed (deal history) + open (positions ปัจจุบัน).
    algo path ไม่เขียน trades.json → ต้องดึงจาก MT5. shape เหมือน trades.json. fail-soft → []."""
    from datetime import datetime, timedelta
    out = []
    try:
        import MetaTrader5 as mt5
        from collections import defaultdict
        if not mt5.initialize():
            return []
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=days), datetime.now()) or []
        pos = defaultdict(lambda: {"pnl": 0.0, "cmt": "", "dir": None, "open_t": None, "close_t": None})
        for d in deals:
            cmt = str(getattr(d, "comment", "") or "")
            if not cmt.startswith("ALGO"):
                continue
            pp = pos[d.position_id]
            pp["pnl"] += d.profit + d.swap + d.commission
            if d.entry == 0:                              # open deal → ทิศ + เวลาเปิด + comment
                pp["cmt"] = cmt; pp["dir"] = "BUY" if d.type == 0 else "SELL"; pp["open_t"] = d.time
            elif d.entry in (1, 2):                       # close deal
                pp["close_t"] = d.time
        for pid, pp in pos.items():
            if pp["close_t"] is None:
                continue
            out.append({"timestamp": datetime.fromtimestamp(pp["close_t"]).isoformat(),
                        "direction": pp["dir"], "comment": pp["cmt"], "entry_type": pp["cmt"],
                        "pnl": round(pp["pnl"], 2), "status": "CLOSED", "source": "ALGO", "ticket": pid})
        for p in (mt5.positions_get() or []):             # open ALGO ปัจจุบัน
            if str(getattr(p, "comment", "") or "").startswith("ALGO"):
                out.append({"timestamp": datetime.fromtimestamp(p.time).isoformat(),
                            "direction": "BUY" if p.type == 0 else "SELL", "comment": p.comment,
                            "entry_type": p.comment, "pnl": None, "status": "OPEN",
                            "source": "ALGO", "ticket": p.ticket})
        for o in (mt5.orders_get() or []):                # pending ALGO ที่ยังรอ fill
            if str(getattr(o, "comment", "") or "").startswith("ALGO"):
                out.append({"timestamp": datetime.fromtimestamp(o.time_setup).isoformat(),
                            "direction": "BUY" if o.type in (2, 4) else "SELL", "comment": o.comment,
                            "entry_type": o.comment, "pnl": None, "status": "PENDING",
                            "source": "ALGO", "ticket": o.ticket, "level": o.price_open})
    except Exception:
        return out
    return out


def build_daily_summary(days=30, tech="all"):
    """คืน {days, totals, techniques_all, filter} — สรุปต่อวัน (ล่าสุดก่อน). รวมไม้ OPEN (วันนี้). 0 token, fail-soft."""
    try:
        d = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
        trades = d if isinstance(d, list) else d.get("trades", [])
    except (OSError, json.JSONDecodeError):
        return {"days": [], "totals": {}, "techniques_all": [], "filter": tech}
    rows_all = [t for t in trades if t.get("timestamp")]     # ทั้ง CLOSED + OPEN (วันนี้)
    rows_all += _algo_trades_from_mt5(days)                   # + ไม้ ALGO จาก MT5 (ไม่อยู่ใน trades.json)
    # ── reconcile: ไม้ที่ trades.json ค้างสถานะ OPEN แต่ปิดไปแล้วจริงบน MT5 → mark CLOSED + realized pnl ──
    _open_tk, _realized, _mt5_ok = _mt5_state(days)
    if _mt5_ok:
        for t in rows_all:
            if t.get("status") == "OPEN" and t.get("ticket") not in _open_tk:
                t["status"] = "CLOSED"
                if t.get("ticket") in _realized:
                    t["pnl"] = _realized[t["ticket"]]
                elif t.get("pnl") is None:
                    t["pnl"] = 0.0                            # ปิดแล้วแต่ไม่พบ deal (เก่ากว่า window) → 0
    techs_all = sorted({_tech(t)[0] for t in rows_all})
    if tech and tech != "all":
        rows_all = [t for t in rows_all if _tech(t)[0] == tech]
    floating = _live_floating()
    byday = defaultdict(list)
    for t in rows_all:
        byday[str(t["timestamp"])[:10]].append(t)

    def _is_closed(t):
        return t.get("status") == "CLOSED" and t.get("pnl") is not None

    out = []
    for date in sorted(byday, reverse=True)[:days]:
        rows = byday[date]
        cl = [t for t in rows if _is_closed(t)]
        op = [t for t in rows if t.get("status") == "OPEN"]
        pend = [t for t in rows if t.get("status") == "PENDING"]
        pnls = [float(t.get("pnl") or 0) for t in cl]
        wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
        techs = Counter(_tech(t)[0] for t in rows)
        regimes = Counter(_tech(t)[1] for t in rows if _tech(t)[1] != "—")
        trends = Counter(str(t.get("trend") or "").upper() for t in rows if t.get("trend"))
        losers = sorted((t for t in cl if float(t.get("pnl") or 0) <= 0), key=lambda t: float(t.get("pnl") or 0))
        worst = losers[0] if losers else None
        why_agg = Counter(_why_loss(t) for t in losers)
        detail = []
        for t in sorted(rows, key=lambda t: str(t.get("timestamp"))):
            closed = _is_closed(t)
            flt = floating.get(t.get("ticket"))
            is_algo = str(t.get("source")) == "ALGO"
            st = t.get("status") or ("CLOSED" if closed else "OPEN")
            why_in = (f"regime {_tech(t)[1]} · algo (deterministic)" if is_algo
                      else (t.get("manual_reason") or t.get("entry_type") or "—"))
            why_out = ("รอ fill @ " + str(round(t.get("level"), 2)) if st == "PENDING" and t.get("level")
                       else "ยังรอ fill" if st == "PENDING"
                       else "ยังเปิดอยู่" if st == "OPEN"
                       else (_why_loss(t) if float(t.get("pnl") or 0) <= 0 else "กำไร (TP algo/manual)"))
            detail.append({
                "time": str(t.get("timestamp"))[11:16], "status": st,
                "tech": _tech(t)[0], "dir": t.get("direction"),
                "pnl": round(float(t.get("pnl") or 0), 2) if closed else (round(flt, 2) if flt is not None else None),
                "why_in": why_in, "why_out": why_out,
            })
        float_open = sum(v for k, v in floating.items() if any(t.get("ticket") == k for t in op))
        out.append({
            "date": date,
            "n": len(rows), "wins": len(wins), "losses": len(losses), "open": len(op), "pending": len(pend),
            "win_rate": round(len(wins) / len(cl), 3) if cl else 0,
            "net_pnl": round(sum(pnls), 2),                  # realized (closed) เท่านั้น
            "float_pnl": round(float_open, 2) if op else 0,  # floating ของไม้ open วันนั้น
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
    print(f"รวม {t.get('n')} ออเดอร์ · net {t.get('net_pnl'):+.0f}฿ · WR {t.get('win_rate',0)*100:.0f}%")
