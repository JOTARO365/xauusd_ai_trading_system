"""agents/loss_adaptive.py — loss-streak → เช็คข่าวใหม่ → ปรับ algo (user 08-08).

เจอไม้ algo ขาดทุนติดกัน → force refresh sentiment (ข่าว+econ สด) แล้วตัดสิน 2 กรณี:
  1. ทิศไม้ที่แพ้ **สวน** sentiment แรง (|score|>TH) → ปรับ algo_dir ให้ตรงข่าว (bearish→allow SELL, bullish→allow BUY)
  2. ทิศ **ตรง** sentiment แต่ยังแพ้ → algo นั้นผิด regime/ห่วง → **pause (SHADOW)** ชั่วคราว (cooldown)

⚠️ adaptive บน loss = เสี่ยง flip-flop/chase → conservative (widen ไม่ flip สุด) + cooldown + shadow-log ก่อน (LOSS_ADAPTIVE_LIVE).
ใช้ data เดิม: MT5 history (นับ loss ต่อ magic) + sentiment_score (force) + algo_dir/shadow_switches (ปรับ). fail-soft.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

_BASE = Path(__file__).resolve().parent.parent
_STATE = _BASE / "data" / "loss_adaptive_state.json"
_JOURNAL = _BASE / "data" / "loss_adaptive_journal.jsonl"

# magic offset → algo_id (ตรง multi_symbol_executor._ALGO_MAGIC + 0=gold base)
_MAGIC_ALGO = {0: "regime_momentum", 1: "regime_momentum", 2: "mean_reversion", 3: "tsmom_d1",
               4: "regime_momentum_fvg", 5: "sweep_reversal", 6: "macro_momentum", 8: "confluence_15m"}


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


def _journal(rec):
    try:
        with open(_JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _streaks():
    """คืน {(algo_id, symbol): {streak, last_dir}} — จำนวนไม้ขาดทุนติดกันล่าสุด ต่อ (algo,symbol) จาก MT5 history."""
    import MetaTrader5 as mt5
    from connectors.mt5_connector import SYSTEM_MAGIC
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=14), now) or []
    closed = [d for d in deals if SYSTEM_MAGIC <= d.magic <= SYSTEM_MAGIC + 9999 and d.entry == 1]
    closed.sort(key=lambda x: x.time)
    by = {}
    for d in closed:
        off = int(d.magic) - SYSTEM_MAGIC
        algo = _MAGIC_ALGO.get(off, "regime_momentum")
        key = (algo, d.symbol)
        st = by.setdefault(key, {"streak": 0, "last_dir": None})
        if d.profit < 0:
            st["streak"] += 1
            st["last_dir"] = "SELL" if d.type == 0 else "BUY"   # close deal type ตรงข้ามทิศ position: close BUY=SELL deal(type0)→pos BUY
        else:
            st["streak"] = 0
    return by


def _logical(symbol):
    """broker symbol → logical (XAUUSD, XAGUSD, ...) แบบหยาบ."""
    s = symbol.upper()
    for lg in ("XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "BTCUSD", "WTIUSD"):
        if lg[:3] in s and (lg[3:6] in s or lg == "XAUUSD" and "GOLD" in s):
            return lg
    if "GOLD" in s:
        return "XAUUSD"
    if "SILVER" in s:
        return "XAGUSD"
    return symbol


def tick():
    """เรียกทุก cycle (throttle). loss-streak → เช็ค sentiment → ปรับ/pause. shadow-log ถ้า LOSS_ADAPTIVE_LIVE=false. fail-soft."""
    try:
        n_trig = int(_cfg("LOSS_STREAK_RECHECK", 3))
        cool = float(_cfg("LOSS_ADAPTIVE_COOLDOWN_MIN", 240)) * 60
        th = int(_cfg("SENTIMENT_BLOCK_ABOVE", 60)) or 60
        live = bool(_cfg("LOSS_ADAPTIVE_LIVE", False))
        state = _load()
        now = time.time()
        if now - float(state.get("_last_run", 0)) < 300:      # throttle 5 นาที
            return None
        state["_last_run"] = now
        streaks = _streaks()
        acted = []
        for (algo, sym), st in streaks.items():
            if st["streak"] < n_trig:
                continue
            ck = "%s:%s" % (algo, sym)
            if now - float(state.get(ck, {}).get("cooldown_until", 0) if isinstance(state.get(ck), dict) else 0) < 0:
                continue
            # cooldown check
            cd = state.get(ck, {}) if isinstance(state.get(ck), dict) else {}
            if now < float(cd.get("cooldown_until", 0)):
                continue
            # force sentiment (gold-relevant; อื่นใช้ score เดียวกันเป็น macro tone)
            from agents.sentiment_score import get_score
            score = int((get_score(force=True) or {}).get("score", 0))
            lastd = st["last_dir"]
            sent_dir = "BUY" if score > 0 else "SELL" if score < 0 else None
            strong = abs(score) >= th
            rec = {"algo": algo, "symbol": sym, "streak": st["streak"], "last_dir": lastd,
                   "sentiment": score, "sent_dir": sent_dir, "live": live}
            if strong and lastd and sent_dir and lastd != sent_dir:
                # กรณี 1: ทิศแพ้ สวน sentiment แรง → ปรับ dir ให้ตรงข่าว
                rec["action"] = "adjust_dir→both (แพ้สวน sentiment %s)" % sent_dir
                if live:
                    try:
                        from agents import algo_dir as ad
                        ad.set_mode(algo, "both")          # widen (ไม่ flip สุด) — ให้เข้าทิศข่าวได้
                    except Exception:
                        pass
            else:
                # กรณี 2: ทิศตรง sentiment (หรือ sentiment อ่อน) แต่ยังแพ้ → algo ผิด regime → pause (SHADOW)
                rec["action"] = "pause→SHADOW (แพ้ %d ติด, ทิศตรง/ข่าวอ่อน = algo ผิดจังหวะ)" % st["streak"]
                if live:
                    try:
                        from agents import shadow_switches as sw
                        sw.set_state(algo, _logical(sym), sw.SHADOW)
                    except Exception:
                        pass
            state[ck] = {"cooldown_until": now + cool, "last_action": rec["action"], "at": datetime.now(timezone.utc).isoformat()}
            _journal(rec)
            logger.warning("[LOSS-ADAPT] %s:%s แพ้ %d ติด · sentiment %d → %s%s" % (
                algo, sym, st["streak"], score, rec["action"], "" if live else " (shadow)"))
            acted.append(rec)
        _save(state)
        return {"acted": acted} if acted else None
    except Exception as e:
        logger.debug("[LOSS-ADAPT] fail-soft: %s" % e)
        return None


def snapshot():
    """dashboard — streak ปัจจุบัน + action ล่าสุด."""
    try:
        streaks = _streaks()
        hot = [{"algo": a, "symbol": s, "streak": st["streak"], "last_dir": st["last_dir"]}
               for (a, s), st in streaks.items() if st["streak"] >= 2]
        hot.sort(key=lambda x: -x["streak"])
        return {"ok": True, "live": bool(_cfg("LOSS_ADAPTIVE_LIVE", False)), "streaks": hot[:10]}
    except Exception:
        return {"ok": False}
