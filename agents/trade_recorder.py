"""agents/trade_recorder.py — central real-trade recorder แยก edge ต่อ algo จาก comment.

ปัญหา: MT5 ลบ deal.comment ตอนปิด (SL/TP) → trades.json ไม่มี comment → แยก algo ไม่ได้.
วิธี: จับ comment ตอนไม้ **เปิด** (position.comment ยังอยู่) เก็บใน registry → ตอนปิด (ticket หาย)
ดึง realized จาก deal history → attribute algo ตาม comment → เขียน logs/real_fills/<algo>__<symbol>.jsonl
(รูปแบบเดียวกับ MSE → real_edge อ่าน per-algo อยู่แล้ว). ขอบเขต = ทอง (SYMBOL); non-gold MSE บันทึกเอง.
เรียกทุก cycle จาก node_position_mgmt. read-only ต่อ MT5 (เขียนแค่ journal). fail-soft.
"""
import json
import os

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REG = os.path.join(_BASE, "data", "trade_registry.json")
_FILLS = os.path.join(_BASE, "logs", "real_fills")

# comment prefix → algo_id (ตรงกับที่ engine ตั้งตอน open_order)
_COMMENT_ALGO = {"ALGO-mom": "regime_momentum", "ALGO-TSMOM": "tsmom_d1"}


def _algo_of(comment):
    """map comment → algo_id. MSE-* = None (MSE บันทึกเอง). อื่นๆ = decision_ai (AI/legacy/manual-system)."""
    c = (comment or "").strip()
    for k, v in _COMMENT_ALGO.items():
        if c.startswith(k):
            return v
    if c.startswith("MSE-"):
        return None
    return "decision_ai"


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _load_reg():
    try:
        with open(_REG, encoding="utf-8") as f:
            m = json.load(f)
            return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _save_reg(reg):
    try:
        os.makedirs(os.path.dirname(_REG), exist_ok=True)
        with open(_REG, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2, default=str)
    except OSError:
        pass


def _append_fill(algo_id, symbol, rec):
    try:
        os.makedirs(_FILLS, exist_ok=True)
        with open(os.path.join(_FILLS, f"{algo_id}__{symbol}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _fill_has_ticket(algo_id, symbol, ticket):
    fp = os.path.join(_FILLS, f"{algo_id}__{symbol}.jsonl")
    if not os.path.exists(fp):
        return False
    tk = f'"ticket": {int(ticket)}'
    try:
        with open(fp, encoding="utf-8") as f:
            return any(tk in ln for ln in f)
    except OSError:
        return False


def _record(ticket, ctx):
    """ปิดแล้ว → deal history → realized_R (จาก sl แรกที่จับได้) → real_fills ต่อ algo. คืน True ถ้าบันทึก."""
    algo = _algo_of(ctx.get("comment"))
    if algo is None:                                          # MSE — ข้าม (บันทึกเอง)
        return True
    symbol = ctx.get("symbol") or "XAUUSD"
    try:
        import MetaTrader5 as mt5
        if _fill_has_ticket(algo, symbol, ticket):
            return True
        deals = mt5.history_deals_get(position=int(ticket))
        if not deals:
            return False
        profit = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals)
        outs = [d for d in deals if getattr(d, "entry", None) == mt5.DEAL_ENTRY_OUT]
        if outs:
            vol = sum(float(d.volume) for d in outs) or 1.0
            exit_px = sum(float(d.price) * float(d.volume) for d in outs) / vol
        else:
            exit_px = float(deals[-1].price)
        entry = float(ctx.get("entry") or 0.0)
        sl = float(ctx.get("sl") or 0.0)
        is_buy = ctx.get("dir") == "BUY"
        # R เฉพาะเมื่อ sl แรก (ตอนเปิด) ยังฝั่งเสี่ยง; ถ้า 0/ผิดฝั่ง = R วัดไม่ได้ (นับ WR/pnl เท่านั้น)
        bad = sl == 0 or ((sl >= entry) if is_buy else (sl <= entry)) or entry == 0
        dist = abs(entry - sl)
        rr = None if (bad or dist <= 0) else (((exit_px - entry) if is_buy else (entry - exit_px)) / dist)
        _append_fill(algo, symbol, {
            "algo_id": algo, "symbol": symbol, "ticket": int(ticket), "dir": ctx.get("dir"),
            "entry": round(entry, 5), "exit": round(exit_px, 5), "comment": ctx.get("comment"),
            "realized_R": round(rr, 3) if rr is not None else None, "profit": round(profit, 2),
            "opened_ts": ctx.get("opened_ts"), "closed_ts": _now_iso(), "features": {}})
        logger.info(f"[REC] closed {algo}:{symbol} #{ticket} R={round(rr,3) if rr is not None else '—'} pnl={round(profit,2)}")
        return True
    except Exception as e:
        logger.debug(f"[REC] record #{ticket} fail: {e}")
        return False


def tick(force=False):
    """จับไม้ทองเปิด (comment) + บันทึกไม้ปิดต่อ algo. เรียกทุก cycle. fail-soft."""
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYSTEM_MAGIC, SYMBOL
    except Exception:
        return None
    try:
        pos = mt5.positions_get()
        if pos is None:                                      # fetch fail → ข้าม (กัน false-close)
            return None
        reg = _load_reg()
        open_ids = set()
        for p in pos:
            if p.magic != SYSTEM_MAGIC or p.symbol != SYMBOL:   # เฉพาะทอง magic ระบบ (non-gold = MSE)
                continue
            tk = str(p.ticket)
            open_ids.add(tk)
            if tk not in reg:                                # ไม้ใหม่ → จับ comment (ยังอยู่ตอนเปิด)
                reg[tk] = {"comment": p.comment, "symbol": p.symbol, "entry": float(p.price_open),
                           "sl": float(p.sl), "dir": "BUY" if p.type == 0 else "SELL", "opened_ts": _now_iso()}
        closed = [tk for tk in list(reg) if tk not in open_ids]
        done = 0
        for tk in closed:
            ctx = reg[tk]
            if _record(tk, ctx):
                reg.pop(tk, None); done += 1
            else:
                ctx["_tries"] = int(ctx.get("_tries", 0)) + 1
                if ctx["_tries"] >= 6:
                    reg.pop(tk, None)
        _save_reg(reg)
        return {"open": len(open_ids), "closed": done}
    except Exception as e:
        logger.debug(f"[REC] tick fail: {e}")
        return None


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    print("recorder tick:", tick())
