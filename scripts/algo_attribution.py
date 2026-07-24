"""scripts/algo_attribution.py — แยกผลงาน "algo (บอท)" ออกจาก "manual (คน)" + เทียบ mechanical vs realized.

ตอบคำถาม: shadow/counterfactual ของ algo ขาดทุน แต่บัญชีกำไร → กำไรมาจาก algo หรือ manual กันแน่?
แยกด้วย **magic number** (บอท = SYSTEM_MAGIC, manual = 0) เพราะ broker ลบ order-comment ตอน execute
(deal.comment ว่าง → ใช้ comment แยกไม่ได้). + ดึง algo_journal momentum counterfactual = entry edge เชิงกล
(no management) มาเทียบว่ากำไร live มาจาก entry หรือ execution layer.

READ-ONLY (mt5.history_deals_get + algo_journal) — ไม่ส่งออเดอร์ / ไม่แตะ config. เขียน docs/reports/algo_attribution.md

รัน:  python scripts/algo_attribution.py            (ATTR_DAYS=60 ปรับช่วงได้)
"""
import os
import sys
from datetime import datetime, timezone, timedelta

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)

import config  # noqa: E402,F401  (loads .env)

DAYS = int(os.getenv("ATTR_DAYS") or 60)
ATTR_FROM = os.getenv("ATTR_FROM")           # ISO date เช่น 2026-07-23 (algo live) — override DAYS window


def _from_dt():
    if ATTR_FROM:
        try:
            return datetime.fromisoformat(ATTR_FROM).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc) - timedelta(days=DAYS)


def _algo_magic():
    try:
        from connectors.mt5_connector import SYSTEM_MAGIC
        return int(SYSTEM_MAGIC)
    except Exception:
        return 20260429


def _stats(profits):
    n = len(profits)
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    aw = (sum(wins) / len(wins)) if wins else None
    al = (sum(losses) / len(losses)) if losses else None
    rr = round(abs(aw / al), 2) if (aw and al) else None
    be = round(1 / (1 + rr) * 100, 1) if rr else None          # breakeven WR = 1/(1+RR)
    wr = round(len(wins) / n * 100, 1) if n else None
    return {"n": n, "wr": wr, "total": round(sum(profits), 2),
            "avg_win": round(aw, 1) if aw else None, "avg_loss": round(al, 1) if al else None,
            "rr": rr, "breakeven_wr": be,
            "ev_verdict": ("+EV" if (wr is not None and be is not None and wr > be) else "−EV") if n else "—"}


def realized_split():
    """แยก realized P&L จาก MT5 history เป็น algo (magic) vs manual (magic 0)."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        return {"error": f"mt5.initialize failed: {mt5.last_error()}"}
    magic = _algo_magic()
    frm = _from_dt()
    deals = [d for d in (mt5.history_deals_get(frm, datetime.now(timezone.utc)) or []) if d.entry == 1]
    # ไม้ algo แรก (auto-detect ช่วง live จริงของบอท)
    algo_deals = [d for d in deals if d.magic == magic]
    first_algo = None
    if algo_deals:
        ts = min(int(d.time) for d in algo_deals)
        first_algo = datetime.fromtimestamp(ts, timezone.utc).isoformat()[:16]
    # unrealized: ไม้ที่ยังเปิดอยู่ (float) — กันพลาดว่า realized-only ทำให้ดูขาดทุน (ต้องดึงก่อน shutdown)
    pos = mt5.positions_get() or []
    open_algo = round(sum(p.profit for p in pos if p.magic == magic), 2)
    open_manual = round(sum(p.profit for p in pos if p.magic == 0), 2)
    n_open_algo = sum(1 for p in pos if p.magic == magic)
    n_open_manual = sum(1 for p in pos if p.magic == 0)
    mt5.shutdown()
    algo = [d.profit for d in algo_deals]
    manual = [d.profit for d in deals if d.magic == 0]
    other = [d.profit for d in deals if d.magic not in (magic, 0)]
    return {"magic": magic, "since": frm.isoformat()[:10], "first_algo_deal": first_algo, "n_all": len(deals),
            "total_all": round(sum(d.profit for d in deals), 2),
            "algo": _stats(algo), "manual": _stats(manual), "other": _stats(other),
            "open_algo": open_algo, "open_manual": open_manual,
            "n_open_algo": n_open_algo, "n_open_manual": n_open_manual}


def mechanical_entry():
    """entry edge เชิงกล (no management) — algo_journal momentum counterfactual (SL/TP-RR2/timeout, net cost)."""
    try:
        from agents.algo_journal import summary
        m = (summary() or {}).get("momentum") or {}
        return {"n": m.get("n_closed"), "wr": m.get("win_rate"), "exp_R": m.get("exp_R"),
                "sum_R": m.get("sum_R"), "by_result": m.get("by_result")}
    except Exception as e:
        return {"error": str(e)}


def _report(rl, mech):
    L = ["# Algo Attribution — บอทกำไรจริงไหม (แยกจาก manual)\n"]
    L.append(f"_generated {datetime.now(timezone.utc).isoformat()[:16]}Z · MT5 history ตั้งแต่ {rl.get('since')} · "
             f"ไม้ algo แรก {rl.get('first_algo_deal') or '—'} · algo = magic {rl.get('magic')} · "
             f"manual = magic 0 (broker ลบ comment → แยกด้วย magic)_\n")
    if rl.get("error"):
        L.append(f"\n⚠️ {rl['error']}\n"); return "\n".join(L)
    L.append("\n## Realized (เงินจริงที่ปิดแล้ว)\n")
    L.append("| กลุ่ม | n | WR% | รวม | avgWin | avgLoss | RR | breakeven WR | verdict |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|:--:|")
    for name, label in (("algo", "**ALGO (บอท)**"), ("manual", "manual (คน)"), ("other", "other magic")):
        s = rl.get(name) or {}
        if not s.get("n"):
            continue
        L.append(f"| {label} | {s['n']} | {s['wr']} | **{s['total']:+.2f}** | {s['avg_win']} | {s['avg_loss']} | "
                 f"{s['rr']} | {s['breakeven_wr']}% | {s['ev_verdict']} |")
    L.append(f"| รวมทุกกลุ่ม | {rl['n_all']} | | **{rl['total_all']:+.2f}** | | | | | |")
    a_tot = (rl.get("algo") or {}).get("total", 0) + rl.get("open_algo", 0)
    m_tot = (rl.get("manual") or {}).get("total", 0) + rl.get("open_manual", 0)
    L.append("\n## Unrealized (ไม้เปิดอยู่ · float) + รวม\n")
    L.append(f"- **ALGO (บอท): realized {(rl.get('algo') or {}).get('total',0):+.2f} + float {rl.get('open_algo',0):+.2f} "
             f"(เปิด {rl.get('n_open_algo',0)} ไม้) = รวม {a_tot:+.2f}**\n")
    L.append(f"- manual (คน): realized {(rl.get('manual') or {}).get('total',0):+.2f} + float {rl.get('open_manual',0):+.2f} "
             f"(เปิด {rl.get('n_open_manual',0)} ไม้) = รวม {m_tot:+.2f}\n")
    L.append("- ⚠️ float ยังไม่ล็อก (ไม้เปิดกลับตัวได้ → กำไรลอยหาย). realized = ที่ booked จริง.\n")
    L.append("\n## Mechanical entry edge (algo_journal momentum counterfactual — no management)\n")
    if mech.get("error"):
        L.append(f"- {mech['error']}\n")
    else:
        L.append(f"- n={mech.get('n')} · WR={mech.get('wr')} · **exp_R={mech.get('exp_R')}** · "
                 f"sum_R={mech.get('sum_R')} · by_result={mech.get('by_result')}\n")
        L.append("- = สัญญาณ entry เดียวกับ live resolve เชิงกล (SL/TP-RR2/timeout, net cost, ไม่มี BE/trailing/momentum-exit)\n")
    L.append("\n## อ่านผล\n")
    a = rl.get("algo") or {}
    m = rl.get("manual") or {}
    if a.get("n"):
        L.append(f"- **บอท: realized {a['total']:+.2f} ({a['ev_verdict']}, closed n={a['n']}, WR {a['wr']}%) "
                 f"แต่ + float = รวม {a_tot:+.2f}** → net {'บวก' if a_tot >= 0 else 'ลบ'} ถ้านับไม้เปิด.\n")
    if m.get("n"):
        L.append(f"- **manual: realized {m['total']:+.2f} ({m['ev_verdict']}, closed n={m['n']}, WR {m['wr']}%)** — กำไรบัญชีส่วนใหญ่มาจากนี่.\n")
    L.append(f"- ⚠️ **n บอทเล็กมาก (closed n={a.get('n')}) → สรุป edge ไม่ได้ทั้ง +/−.** realized ติดลบ ≠ บอทแย่, "
             "float บวก ≠ บอทมี edge (ยังไม่ล็อก). ปล่อยเก็บ n≥100 แล้ว re-run. entry เชิงกล (shadow/counterfactual) "
             "ยังติดลบ = ตรง AUDIT_quant.md.\n")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    rl = realized_split()
    mech = mechanical_entry()
    md = _report(rl, mech)
    outdir = os.path.join(_BASE, "docs", "reports")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "algo_attribution.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"\n→ docs/reports/algo_attribution.md")


if __name__ == "__main__":
    main()
