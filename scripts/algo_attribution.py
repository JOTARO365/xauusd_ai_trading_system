"""scripts/algo_attribution.py — แยกผลงาน "บอท (SYSTEM)" ออกจาก "manual (คน)" จาก trades.json.

ตอบคำถาม: บอทกำไร/ขาดทุนเท่าไหร่จริง แยกจากไม้ที่คนเทรดมือ?
อ่านจาก **logs/trades.json (แหล่งเดียวกับตาราง Trade History บน dashboard)** → source=SYSTEM คือบอท,
MANUAL คือคน. ตรงกับที่ผู้ใช้เห็นบนจอ.

⚠️ อย่าใช้ MT5 deal.magic แยก: broker รีเซ็ต magic=0 บน "ไม้ปิด" ที่โดน SL/TP → นับบอทขาดไป
   (bug เดิม 07-25). trades.json บอทเขียน source เอง = เชื่อถือได้กว่า.

+ ดึง algo_journal momentum counterfactual = entry edge เชิงกล (no management) มาเทียบ.
READ-ONLY. เขียน docs/reports/algo_attribution.md

รัน:  ATTR_FROM=2026-07-23 python scripts/algo_attribution.py     (ATTR_DAYS=30 = fallback ถ้าไม่ตั้ง FROM)
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)

DAYS = int(os.getenv("ATTR_DAYS") or 30)
ATTR_FROM = os.getenv("ATTR_FROM")           # ISO date เช่น 2026-07-23 (algo live)


def _since():
    if ATTR_FROM:
        return ATTR_FROM[:10]
    return (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()[:10]


def _load():
    tr = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
    return tr if isinstance(tr, list) else tr.get("trades", [])


def _tdate(t):
    return (t.get("timestamp") or t.get("close_time") or "")[:10]


def _stats(closed):
    """realized stats จากไม้ปิด (pnl)."""
    prof = [t.get("pnl") or 0 for t in closed]
    n = len(prof)
    wins = [p for p in prof if p > 0]
    losses = [p for p in prof if p < 0]
    aw = (sum(wins) / len(wins)) if wins else None
    al = (sum(losses) / len(losses)) if losses else None
    rr = round(abs(aw / al), 2) if (aw and al) else None
    be = round(1 / (1 + rr) * 100, 1) if rr else None
    wr = round(len(wins) / n * 100, 1) if n else None
    top = max(prof) if prof else 0                       # ไม้กำไรใหญ่สุด (เช็ค concentration)
    tot = sum(prof)
    return {"n": n, "wr": wr, "total": round(tot, 2),
            "avg_win": round(aw, 1) if aw else None, "avg_loss": round(al, 1) if al else None,
            "rr": rr, "breakeven_wr": be,
            "ev_verdict": ("+EV" if (wr is not None and be is not None and wr > be) else "−EV") if n else "—",
            "top_trade": round(top, 2),
            "top_share": round(top / tot * 100, 0) if tot > 0 else None}


def split():
    since = _since()
    rows = [t for t in _load() if _tdate(t) >= since]
    out = {"since": since, "n_all": len(rows)}
    for src, key in (("SYSTEM", "algo"), ("MANUAL", "manual")):
        g = [t for t in rows if t.get("source") == src]
        closed = [t for t in g if str(t.get("status", "")).upper() == "CLOSED"]
        openp = [t for t in g if str(t.get("status", "")).upper() == "OPEN"]
        s = _stats(closed)
        s["n_open"] = len(openp)
        s["float"] = round(sum((t.get("pnl") or 0) for t in openp), 2)
        s["total_incl_float"] = round(s["total"] + s["float"], 2)
        out[key] = s
    return out


def mechanical_entry():
    try:
        from agents.algo_journal import summary
        m = (summary() or {}).get("momentum") or {}
        return {"n": m.get("n_closed"), "wr": m.get("win_rate"), "exp_R": m.get("exp_R"),
                "sum_R": m.get("sum_R"), "by_result": m.get("by_result")}
    except Exception as e:
        return {"error": str(e)}


def _report(d, mech):
    L = ["# Algo Attribution — บอท (SYSTEM) vs manual (คน)\n"]
    L.append(f"_generated {datetime.now(timezone.utc).isoformat()[:16]}Z · source = logs/trades.json "
             f"(แหล่งเดียวกับ Trade History) · ตั้งแต่ {d['since']} · SYSTEM=บอท / MANUAL=คน_\n")
    L.append("\n## Realized (ไม้ปิดแล้ว)\n")
    L.append("| กลุ่ม | n | WR% | realized | avgWin | avgLoss | RR | BE-WR | verdict | ไม้ใหญ่สุด (share) |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|:--:|--:|")
    for name, label in (("algo", "**บอท (SYSTEM)**"), ("manual", "manual (คน)")):
        s = d.get(name) or {}
        if not s.get("n"):
            continue
        share = f"{s['top_trade']:+.0f} ({s['top_share']:.0f}%)" if s.get("top_share") is not None else f"{s.get('top_trade')}"
        L.append(f"| {label} | {s['n']} | {s['wr']} | **{s['total']:+.2f}** | {s['avg_win']} | {s['avg_loss']} | "
                 f"{s['rr']} | {s['breakeven_wr']}% | {s['ev_verdict']} | {share} |")
    L.append("\n## + Unrealized (ไม้เปิด · float) = รวม\n")
    for name, label in (("algo", "บอท"), ("manual", "manual")):
        s = d.get(name) or {}
        if s.get("n") or s.get("n_open"):
            L.append(f"- **{label}: realized {s.get('total'):+.2f} + float {s.get('float'):+.2f} "
                     f"(เปิด {s.get('n_open')} ไม้) = รวม {s.get('total_incl_float'):+.2f}**\n")
    L.append("\n## Mechanical entry edge (algo_journal momentum counterfactual — no management)\n")
    if mech.get("error"):
        L.append(f"- {mech['error']}\n")
    else:
        L.append(f"- n={mech.get('n')} · WR={mech.get('wr')} · exp_R={mech.get('exp_R')} · by={mech.get('by_result')} "
                 f"= สัญญาณ entry resolve เชิงกล (no BE/trailing)\n")
    L.append("\n## อ่านผล\n")
    a = d.get("algo") or {}
    if a.get("n"):
        conc = f" · ⚠️ ไม้ใหญ่สุดกิน {a['top_share']:.0f}% ของกำไร" if a.get("top_share") and a["top_share"] > 60 else ""
        L.append(f"- **บอท realized {a['total']:+.2f} ({a['ev_verdict']}, n={a['n']}, WR {a['wr']}%)**{conc}\n")
    L.append(f"- ⚠️ n บอทยังเล็ก ({a.get('n')} ไม้) → ยังไม่พอสรุป edge; ถ้ากำไรมาจากไม้เดียว = ยังพิสูจน์ไม่ได้. "
             "entry เชิงกล (counterfactual) ยังลบ = ต้องเก็บต่อ.\n")
    L.append("- source = trades.json (บอทเขียน source เอง) — อย่าใช้ MT5 deal.magic (broker รีเซ็ต magic บนไม้ปิด SL/TP → นับผิด).\n")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa: F401
    d = split()
    mech = mechanical_entry()
    md = _report(d, mech)
    outdir = os.path.join(_BASE, "docs", "reports")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "algo_attribution.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print("\n→ docs/reports/algo_attribution.md")


if __name__ == "__main__":
    main()
