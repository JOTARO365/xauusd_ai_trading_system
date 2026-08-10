"""agents/profit_target.py — force-close ทุกไม้เมื่อกำไรถึง X% ของ balance (user 08-08).

โหมด lock กำไร: เมื่อ equity ≥ baseline × (1 + FORCE_CLOSE_PROFIT_PCT/100) → ปิดไม้ระบบทั้งหมด (lock กำไร)
default 100% = equity ถึง 2× baseline → ปิดหมด. หลังปิด reset baseline = balance ใหม่ (roll — lock ทุก +100%).

baseline = balance ตอน enable ครั้งแรก (persist data/profit_target_state.json; reset เมื่อ restart/หลัง trigger).
gated FORCE_CLOSE_PROFIT (default false). ปิดเฉพาะไม้ระบบ (SYSTEM_MAGIC range) — ไม้ manual ไม่แตะ. fail-soft.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

_BASE = Path(__file__).resolve().parent.parent
_STATE = _BASE / "data" / "profit_target_state.json"


def _cfg(n, d):
    import config as _c
    return getattr(_c, n, d)


def _load():
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        _STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _close_pos(mt5, pos, comment="PROFIT-TARGET"):
    tick = mt5.symbol_info_tick(pos.symbol)
    if not tick:
        return False
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
           "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": pos.ticket, "price": tick.bid if pos.type == 0 else tick.ask,
           "deviation": 30, "magic": pos.magic, "comment": comment,
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)


def _eod_flush(mt5, system_magic, st):
    """ทุนน้อยไม่ถือกำไรข้ามวัน: รอบแรกที่เลยชั่วโมง cutoff (BKK, UTC+7) ของแต่ละวัน → ปิดไม้ระบบที่กำไร
    ทั้งหมดครั้งเดียว (lock carry ข้ามคืน). stamp วันที่กัน repeat + กันปิดกำไร intraday ที่เกิดหลัง flush.
    คืน dict เมื่อปิดจริง (short-circuit tick), None เมื่อยังไม่ถึง/flush แล้ว/ไม่มีไม้กำไร (แต่ stamp แล้ว)."""
    hour = int(_cfg("EOD_PROFIT_CLOSE_HOUR_BKK", 2))
    if hour < 0:
        return None                                          # ปิดฟีเจอร์
    from datetime import timedelta
    now_bkk = datetime.now(timezone.utc) + timedelta(hours=7)
    if now_bkk.hour < hour:
        return None                                          # ยังไม่ถึงเวลา cutoff ของวันนี้
    day = now_bkk.date().isoformat()
    if st.get("last_eod_flush") == day:
        return None                                          # flush วันนี้ไปแล้ว
    winners = [p for p in (mt5.positions_get() or [])
               if system_magic <= p.magic <= system_magic + 9999 and float(p.profit) > 0]
    closed = sum(1 for p in winners if _close_pos(mt5, p, comment="EOD-PROFIT"))
    st["last_eod_flush"] = day                               # stamp เสมอ (แม้ 0 ไม้) กัน re-scan + ปิด intraday หลัง flush
    st["last_eod"] = {"at": now_bkk.isoformat(), "hour_bkk": hour, "winners": len(winners), "closed": closed}
    _save(st)
    if closed:
        logger.warning("[EOD-PROFIT] 🌙 %02d:00 BKK — ทุนน้อยไม่ถือกำไรข้ามวัน → ปิด %d/%d ไม้กำไร" % (
            hour, closed, len(winners)))
        return {"ok": True, "eod_flush": True, "closed": closed, "winners": len(winners)}
    return None                                              # ไม่มีไม้กำไร → stamp แล้ว ปล่อย tick ทำ lock-100% ต่อ


def tick():
    """เรียกทุก cycle. ปิดทุกไม้ระบบเมื่อ equity ≥ baseline×(1+PCT/100). fail-soft."""
    try:
        # force-close = บังคับเปิดถาวร (ปิดใน config ไม่ได้ — user 08-08). gate เดียว = capital
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYSTEM_MAGIC
        a = mt5.account_info()
        if not a:
            return None
        min_cap = float(_cfg("FORCE_CLOSE_MIN_CAPITAL", 10000))
        if a.equity >= min_cap:                             # ทุนถึงเกณฑ์เริ่มต้น → ไม่ force-close, ปล่อยกำไรวิ่ง
            return {"ok": True, "equity": round(a.equity, 2), "min_cap": min_cap, "active": False, "reason": "ทุน ≥ เกณฑ์ → ปล่อยวิ่ง"}
        st = _load()
        # ── EOD flush: ทุนน้อยไม่ถือกำไรข้ามวัน — รอบแรกที่เลยชั่วโมง cutoff (BKK) ของวัน → ปิดไม้กำไรทั้งหมดครั้งเดียว ──
        eod = _eod_flush(mt5, SYSTEM_MAGIC, st)
        if eod is not None:
            return eod
        base = float(st.get("baseline", 0) or 0)
        if base <= 0:                                       # capture baseline ครั้งแรก = balance ปัจจุบัน
            base = float(a.balance)
            st["baseline"] = base
            st["baseline_at"] = datetime.now(timezone.utc).isoformat()
            _save(st)
        pct = float(_cfg("FORCE_CLOSE_PROFIT_PCT", 100))
        target = base * (1 + pct / 100.0)
        if a.equity < target:
            return {"ok": True, "equity": round(a.equity, 2), "target": round(target, 2), "hit": False}
        # ── ถึงเป้า → ปิดไม้ระบบทั้งหมด ──
        ps = [p for p in (mt5.positions_get() or []) if SYSTEM_MAGIC <= p.magic <= SYSTEM_MAGIC + 9999]
        closed = sum(1 for p in ps if _close_pos(mt5, p))
        a2 = mt5.account_info()
        new_base = float(a2.balance) if a2 else base
        st["baseline"] = new_base                           # roll: lock รอบถัดไปจาก balance ใหม่
        st["baseline_at"] = datetime.now(timezone.utc).isoformat()
        st["last_trigger"] = {"at": st["baseline_at"], "closed": closed, "equity": round(a.equity, 2),
                              "target": round(target, 2), "new_baseline": round(new_base, 2)}
        _save(st)
        logger.warning("[PROFIT-TARGET] 🎯 equity %.0f ≥ target %.0f (+%.0f%%) → ปิด %d ไม้ · baseline ใหม่ %.0f" % (
            a.equity, target, pct, closed, new_base))
        return {"ok": True, "hit": True, "closed": closed, "new_baseline": new_base}
    except Exception as e:
        logger.debug("[PROFIT-TARGET] fail-soft: %s" % e)
        return None


def snapshot():
    """dashboard — progress ไปเป้า."""
    try:
        import MetaTrader5 as mt5
        a = mt5.account_info()
        st = _load()
        base = float(st.get("baseline", 0) or (a.balance if a else 0))
        pct = float(_cfg("FORCE_CLOSE_PROFIT_PCT", 100))
        target = base * (1 + pct / 100.0)
        eq = float(a.equity) if a else 0
        prog = ((eq - base) / (target - base) * 100) if target > base else 0
        min_cap = float(_cfg("FORCE_CLOSE_MIN_CAPITAL", 10000))
        active = eq < min_cap                                 # บังคับเปิดถาวร — gate เดียว = capital
        return {"ok": True, "enable": True, "min_cap": min_cap,
                "active": active, "baseline": round(base, 2), "equity": round(eq, 2),
                "target": round(target, 2), "progress_pct": round(prog, 1),
                "reason": "lock +100% (ทุน < เกณฑ์ โตไป 10k)" if active else "ปล่อยวิ่ง (ทุน ≥ เกณฑ์)",
                "last_trigger": st.get("last_trigger"),
                "eod_hour_bkk": int(_cfg("EOD_PROFIT_CLOSE_HOUR_BKK", 2)),   # ทุนน้อย: ปิดกำไร carry หลังชั่วโมงนี้ (BKK)
                "last_eod": st.get("last_eod")}
    except Exception:
        return {"ok": False}
