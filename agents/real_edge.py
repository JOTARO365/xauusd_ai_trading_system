"""agents/real_edge.py — edge จริงจากไม้ที่ปิดแล้วบนเงินจริง (ต่างจาก shadow = paper).

อ่าน logs/real_fills/<algo>__<sym>.jsonl (เขียนโดย multi_symbol_executor ตอนไม้ปิด) → สรุปต่อ (algo, symbol):
n, WR, exp_R (net จริง), ΣR, sum_pnl + segment ตาม feature ที่ snapshot ตอนเข้า (regime, session) เพื่อดูว่า
edge จริงกระจุกที่สภาวะไหน. **DISPLAY-ONLY** — ไม่กรอง entry, ไม่มี gate (validated-or-off: n≥100 + gauntlet ก่อน).

เทียบกับ shadow_matrix (paper) ได้: real = เงินจริง n น้อย · shadow = paper n เยอะ. gold basic edge อยู่ที่
algo_attribution.py (source split) แล้ว — ตัวนี้เน้น feature-rich real fills (MSE/คู่ที่ toggle LIVE).
Import-safe, 0 token, read-only. รัน: python agents/real_edge.py
"""
import json
import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILLS = os.path.join(_BASE, "logs", "real_fills")
_RETIRED = {"decision_ai"}                 # algo ปลดระวาง (AI pipeline เลิกใช้ 07-26) — ซ่อนจาก dashboard, ไฟล์ real_fills ยังเก็บไว้เป็นประวัติ
_MIN_SEG = 8                                                # n ขั้นต่ำต่อ bucket ถึงจะโชว์ segment
_SESSIONS = [("Asian", 0, 7), ("London", 7, 13), ("NY", 13, 22), ("Late", 22, 24)]


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


def _session(hour):
    if hour is None:
        return "—"
    for name, a, b in _SESSIONS:
        if a <= hour < b:
            return name
    return "—"


def _stats(recs):
    """n/WR/pnl นับทุกไม้ (win: R>0.05 ถ้ามี R, ไม่งั้น profit>0). exp_R/ΣR เฉพาะไม้ที่ R เชื่อได้
    (ทอง SL ขยับไป BE → R วัดไม่ได้ → นับ WR/pnl แต่ไม่นับ exp_R → กัน exp_R ลบทั้งที่ไม้กำไร)."""
    if not recs:
        return {"n": 0, "wr": None, "exp_R": None, "sum_R": 0.0, "sum_pnl": 0.0, "n_R": 0}
    n = len(recs)
    rvals = [float(r["realized_R"]) for r in recs if r.get("realized_R") is not None]

    def _win(r):
        rr = r.get("realized_R")
        return (rr > 0.05) if rr is not None else ((r.get("profit") or 0) > 0)
    wins = sum(1 for r in recs if _win(r))
    pnl = sum(float(r.get("profit") or 0.0) for r in recs)
    return {"n": n, "wr": round(wins / n * 100, 1),
            "exp_R": round(sum(rvals) / len(rvals), 3) if rvals else None,
            "sum_R": round(sum(rvals), 2) if rvals else 0.0,
            "sum_pnl": round(pnl, 2), "n_R": len(rvals)}


def _segment(recs, key_fn):
    """exp_R ต่อ bucket (regime/session) — เฉพาะ bucket ที่ n ≥ _MIN_SEG."""
    buckets = {}
    for r in recs:
        if r.get("realized_R") is None:
            continue
        k = key_fn(r) or "—"
        buckets.setdefault(k, []).append(float(r["realized_R"]))
    out = {}
    for k, rs in buckets.items():
        if len(rs) >= _MIN_SEG:
            out[k] = {"n": len(rs), "exp_R": round(sum(rs) / len(rs), 3),
                      "wr": round(sum(1 for x in rs if x > 0) / len(rs) * 100, 1)}
    return out


def _gold_real():
    """gold-bot real trades จาก logs/trades.json (source=SYSTEM, ปิดแล้ว) → map เป็น regime_momentum:XAUUSD.
    ทองเทรดผ่าน engine ตัวเอง (ไม่เขียน real_fills) → ดึงจาก trades.json. realized_R = (exit−entry)/|entry−sl|.
    หมายเหตุ: รวมทุก system-gold (momentum+TSMOM+AI) เพราะ trades.json ไม่มี comment แยก — = edge รวมบอททอง."""
    fp = os.path.join(_BASE, "logs", "trades.json")
    recs = []
    try:
        d = json.load(open(fp, encoding="utf-8"))
        rows = d if isinstance(d, list) else d.get("trades", [])
        for r in rows:
            if str(r.get("source", "")).upper() != "SYSTEM":
                continue
            if str(r.get("status", "")).upper() not in ("CLOSED", "CLOSE"):
                continue
            pnl = r.get("pnl")
            if pnl is None:                                   # ต้องมี pnl (นับ WR/pnl ทุกไม้ system-closed ไม่ใช่แค่ที่มี close/sl ครบ)
                continue
            entry = r.get("entry_price"); close = r.get("close_price"); sl = r.get("sl")
            d_ = str(r.get("direction", "")).upper()
            # realized_R คำนวณเฉพาะเมื่อ field ครบ + SL ยังฝั่งเสี่ยง (reporter ทับ sl หลัง BE → R เชื่อไม่ได้)
            rr = None
            if d_ in ("BUY", "SELL") and entry and close and sl and float(entry) != float(sl):
                entry = float(entry); close = float(close); sl = float(sl); is_buy = d_ == "BUY"
                bad_sl = (sl >= entry) if is_buy else (sl <= entry)
                dist = abs(entry - sl)
                if not bad_sl and dist > 0:
                    rr = ((close - entry) if is_buy else (entry - close)) / dist
            recs.append({"realized_R": round(rr, 3) if rr is not None else None,
                         "profit": float(pnl), "features": {}})
    except Exception:
        pass
    return recs


def build():
    """สรุป real edge ต่อ combo + segment. fail-soft."""
    rows = []
    if os.path.isdir(_FILLS):
        for fn in sorted(os.listdir(_FILLS)):
            if not fn.endswith(".jsonl"):
                continue
            recs = _read(os.path.join(_FILLS, fn))
            if not recs:
                continue
            algo, _, sym = fn[:-6].partition("__")
            if algo in _RETIRED:                             # ปลดระวาง (ไม่ใช้แล้ว) → ซ่อนจาก dashboard
                continue
            st = _stats(recs)
            rows.append({"algo_id": algo, "symbol": sym, **st,
                         "by_regime": _segment(recs, lambda r: (r.get("features") or {}).get("regime")),
                         "by_session": _segment(recs, lambda r: _session((r.get("features") or {}).get("hour")))})
    # gold edge แยก algo แล้วผ่าน trade_recorder → real_fills/<algo>__XAUUSD (regime_momentum/tsmom_d1/decision_ai)
    # ไม่ lump trades.json อีก (แยกตาม comment ต่อ algo ตาม design). _gold_real เหลือไว้ fallback debug เท่านั้น
    from datetime import datetime, timezone
    return {"ok": True, "generated": datetime.now(timezone.utc).isoformat()[:16] + "Z",
            "rows": rows,
            "note": "real closed-money edge (net จริง). n น้อย = ยังไม่พอตัดสิน (validated-or-off: n≥100 + gauntlet). "
                    "ไม่กรอง entry — display เทียบ shadow paper."}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    m = build()
    print(f"real edge · {m['generated']} · {len(m['rows'])} combo")
    for r in m["rows"]:
        print(f"  {r['algo_id']}:{r['symbol']:8} n={r['n']:>3} WR={r['wr']} exp_R={r['exp_R']} "
              f"ΣR={r['sum_R']} pnl={r['sum_pnl']} · regime={r['by_regime']}")
    if not m["rows"]:
        print("  (ยังไม่มี real fill — รอ MSE ปิดไม้จริง)")
