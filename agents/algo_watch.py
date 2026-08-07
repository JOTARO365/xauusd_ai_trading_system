"""agents/algo_watch.py — terminal watch: เมื่อยังไม่มีไม้ ALGO เปิด บอกว่า "อาจเข้า order จุดไหน ด้วย algo อะไร".

log บรรทัดเดียวต่อ throttle ลง system.log/console (heartbeat "จะเข้าตรงไหน") จากการคำนวณ algo จริง:
  - regime_momentum : Donchian breakout (BUY>X / SELL<Y) + regime ปัจจุบัน (เข้าเฉพาะ TREND)
  - tsmom_d1        : D1 ensemble vote + ราคาที่ต้องข้ามเพื่อ flip เป็น BUY/SELL
เคารพ direction mode (algo_dir) — ทิศที่ถูกปิดจะขึ้น "(ปิดโดย mode)". read-only, 0 token, fail-soft.

เรียกจาก trading_graph.node_position_mgmt ทุก cycle; log จริงเมื่อ (ก) ไม่มีไม้ ALGO/TSMOM เปิด + (ข) พ้น throttle.
"""
import time

from loguru import logger

_last = {"t": 0.0, "msg": ""}
_THROTTLE = 300          # log อย่างมากทุก 5 นาที (กัน spam loop 5s) — หรือเมื่อข้อความเปลี่ยน


def _gold_has_algo_position():
    """มีไม้ ALGO/TSMOM เปิดบนทองไหม (ถ้ามี = เข้าแล้ว ไม่ต้อง watch)."""
    try:
        from connectors.mt5_connector import get_open_positions
        for p in (get_open_positions() or []):
            c = str((p.get("comment") if isinstance(p, dict) else getattr(p, "comment", "")) or "")
            if c.startswith("ALGO"):
                return True
    except Exception:
        pass
    return False


def _dir_note(algo_id, direction):
    try:
        from agents import algo_dir as _adir
        return "" if _adir.allowed(algo_id, direction) else " (ปิดโดย mode)"
    except Exception:
        return ""


def _potential():
    """สร้างข้อความ potential-entry ต่อ algo จากข้อมูลสดทอง. คืน str หรือ '' ถ้าคำนวณไม่ได้."""
    import os, sys
    import numpy as np
    import MetaTrader5 as mt5
    import config as _cfg
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import regime_lib as R
    S = _cfg.SYMBOL
    tk = mt5.symbol_info_tick(S)
    if not tk:
        return ""
    px = tk.bid
    parts = [f"ราคา {px:.2f}"]
    # regime_momentum — Donchian breakout + regime
    try:
        h = mt5.copy_rates_from_pos(S, mt5.TIMEFRAME_H1, 0, 400)
        hi, lo, cl = h["high"].astype(float), h["low"].astype(float), h["close"].astype(float)
        i = len(cl) - 2
        reg = R.detect_regime(R.efficiency_ratio(cl)[i], R.adx(hi, lo, cl)[i], R.vol_percentile(cl)[i])
        lv = R.momentum_levels(i, hi, lo, cl, R.atr(hi, lo, cl))
        tag = "" if reg == "TREND" else f" [regime {reg}→standby]"
        parts.append(f"regime_momentum: BUY>{lv['buy_level']:.1f}{_dir_note('regime_momentum','BUY')} / "
                     f"SELL<{lv['sell_level']:.1f}{_dir_note('regime_momentum','SELL')}{tag}")
    except Exception:
        pass
    # tsmom_d1 — D1 vote + flip level
    try:
        d = mt5.copy_rates_from_pos(S, mt5.TIMEFRAME_D1, 0, 300); dc = d["close"].astype(float); j = len(dc) - 2
        vs = {L: int(np.sign(dc[j] - dc[j - L])) for L in (63, 126, 252)}
        s = sum(vs.values())
        cur = "BUY" if s > 0 else "SELL" if s < 0 else "FLAT"
        need = ""
        if cur != "BUY":                                    # ต้องข้าม close ของ window ที่ยังลบ เพื่อ flip ขึ้น
            ups = [dc[j - L] for L in (63, 126, 252) if dc[j] < dc[j - L]]
            if ups:
                need = f" · BUY เมื่อ>{min(ups):.0f}"
        parts.append(f"tsmom_d1: vote {cur}{_dir_note('tsmom_d1', cur if cur!='FLAT' else 'BUY')}{need}")
    except Exception:
        pass
    return "ยังไม่เข้า order | " + " | ".join(parts) if len(parts) > 1 else ""


def snapshot():
    """โอกาสเข้า order ต่อ algo (structured, สำหรับ dashboard). gold: regime_momentum + tsmom_d1.
    คืน {ok, price, algos:[{algo,name,buy,sell,regime,tsmom_vote,flip,dir_mode}]}. read-only, 0 token."""
    out = {"ok": False, "algos": []}
    try:
        import os, sys
        import numpy as np
        import MetaTrader5 as mt5
        import config as _cfg
        from agents import algo_dir as _adir
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
        import regime_lib as R
        S = _cfg.SYMBOL
        tk = mt5.symbol_info_tick(S)
        if not tk:
            return out
        px = tk.bid
        out["ok"] = True; out["price"] = round(px, 2)
        # regime_momentum
        try:
            h = mt5.copy_rates_from_pos(S, mt5.TIMEFRAME_H1, 0, 400)
            hi, lo, cl = h["high"].astype(float), h["low"].astype(float), h["close"].astype(float)
            i = len(cl) - 2
            reg = R.detect_regime(R.efficiency_ratio(cl)[i], R.adx(hi, lo, cl)[i], R.vol_percentile(cl)[i])
            lv = R.momentum_levels(i, hi, lo, cl, R.atr(hi, lo, cl))
            out["algos"].append({"algo": "regime_momentum", "name": "Momentum Breakout",
                                 "buy": round(lv["buy_level"], 2), "sell": round(lv["sell_level"], 2),
                                 "regime": reg, "armed": reg == "TREND", "dir_mode": _adir.mode_of("regime_momentum")})
        except Exception:
            pass
        # tsmom_d1
        try:
            d = mt5.copy_rates_from_pos(S, mt5.TIMEFRAME_D1, 0, 300); dc = d["close"].astype(float); j = len(dc) - 2
            vs = {L: int(np.sign(dc[j] - dc[j - L])) for L in (63, 126, 252)}
            s = sum(vs.values()); vote = "BUY" if s > 0 else "SELL" if s < 0 else "FLAT"
            ups = [dc[j - L] for L in (63, 126, 252) if dc[j] < dc[j - L]]
            out["algos"].append({"algo": "tsmom_d1", "name": "TSMOM-D1", "regime": "D1",
                                 "tsmom_vote": vote, "flip_buy": round(min(ups), 0) if ups else None,
                                 "dir_mode": _adir.mode_of("tsmom_d1")})
        except Exception:
            pass
    except Exception:
        pass
    return out


def tick():
    """เรียกทุก cycle. log potential entry เมื่อยังไม่มีไม้ ALGO + พ้น throttle. fail-soft."""
    try:
        if _gold_has_algo_position():
            return
        now = time.time()
        if now - _last["t"] < _THROTTLE:
            return
        msg = _potential()
        if msg and msg != _last["msg"]:
            logger.info(f"[ALGO-WATCH] {msg}")
            _last["msg"] = msg
        _last["t"] = now
    except Exception:
        pass
