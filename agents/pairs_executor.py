"""agents/pairs_executor.py — XAU-XAG stat-arb pairs-trade (2-leg market-neutral). user 08-07.

edge (backtest rolling-β causal + z-stop + cost): spread z-fade WR57% OOS+2.45 t1.89 = +EV แรงสุด market-neutral.
long-spread (BUY XAU + SELL XAG) เมื่อ z<−Z_IN · short-spread (SELL XAU + BUY XAG) เมื่อ z>Z_IN.
exit: |z|≤Z_OUT (กลับ mean) หรือ |z|≥Z_STOP (spread เบี่ยงต่อ = cointegration พัง, cut).

Safeguards (เงินจริง):
- gate PAIRS_LIVE (default false) → ไม่ทำงานเลยจนเปิด
- atomic 2-leg: ถ้า leg 2 fail → ปิด leg 1 ทันที (ไม่มีขาโดด)
- β-hedge sizing จาก contract_size จริง (dollar-neutral) — ไม่ใช่เดา
- disaster SL/ขา (backstop) + z-stop (ปกติปิดก่อน) + state persist (กัน entry ซ้ำ)
- own magic (SYSTEM_MAGIC+7) แยกจาก engine อื่น
hook: trading_graph.node_position_mgmt ทุก cycle. fail-soft.
"""
import json
import math
import os
from pathlib import Path

import numpy as np
from loguru import logger

_BASE = Path(__file__).resolve().parent.parent
_STATE = _BASE / "data" / "pairs_state.json"


def _cfg(name, default):
    import config as _c
    return getattr(_c, name, default)


def _pair_syms():
    raw = str(_cfg("PAIRS_SYMBOLS", "XAUUSD:XAGUSD")).split(":")
    return (raw[0].strip(), raw[1].strip()) if len(raw) == 2 else ("XAUUSD", "XAGUSD")


def _load():
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"open": False}


def _save(d):
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _magic():
    from connectors.mt5_connector import SYSTEM_MAGIC
    return SYSTEM_MAGIC + 7                               # PAIRS leg magic (offset 7; MSE ใช้ 1-6)


def _aligned(mt5, a, b, count):
    ra = mt5.copy_rates_from_pos(a, mt5.TIMEFRAME_H1, 0, count)
    rb = mt5.copy_rates_from_pos(b, mt5.TIMEFRAME_H1, 0, count)
    if ra is None or rb is None:
        return None, None
    mb = {int(t): float(c) for t, c in zip(rb["time"], rb["close"])}
    xa = []; xb = []
    for t, c in zip(ra["time"], ra["close"]):
        if int(t) in mb:
            xa.append(float(c)); xb.append(mb[int(t)])
    if len(xa) < 50:
        return None, None
    return np.array(xa, float), np.array(xb, float)


def _positions(mt5, magic):
    return [p for p in (mt5.positions_get() or []) if p.magic == magic]


def _close(mt5, pos):
    """ปิด position (market opposite)."""
    tick = mt5.symbol_info_tick(pos.symbol)
    if not tick:
        return False
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
           "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": pos.ticket, "price": tick.bid if pos.type == 0 else tick.ask,
           "deviation": 30, "magic": pos.magic, "comment": "PAIRS-close",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)


def _open_leg(mt5, sym, direction, lot, magic):
    """เปิด 1 ขา market + disaster SL (backstop กว้าง). คืน ticket หรือ None."""
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    if not info or not tick:
        return None
    from scripts.regime_lib import atr as _atr  # noqa
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 60)
    av = 0.0
    if rates is not None and len(rates) > 20:
        a = _atr(rates["high"].astype(float), rates["low"].astype(float), rates["close"].astype(float))
        av = float(a[-2]) if a[-2] == a[-2] else 0.0
    px = tick.ask if direction == "BUY" else tick.bid
    dis = (av * float(_cfg("PAIRS_DISASTER_ATR", 6.0))) or (px * 0.03)   # disaster SL ~6×ATR (z-stop ปิดก่อน)
    sl = px - dis if direction == "BUY" else px + dis
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot,
           "type": mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL,
           "price": px, "sl": round(sl, info.digits), "deviation": 30, "magic": magic,
           "comment": "PAIRS-%s" % ("XAU" if "XAU" in sym else "XAG"),
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return r.order
    logger.warning(f"[PAIRS] open leg {sym} {direction} fail: {getattr(r,'comment','?')} retcode={getattr(r,'retcode','?')}")
    return None


def _hedge_lots(mt5, xau_sym, xag_sym, beta):
    """β-hedge sizing (dollar-neutral) จาก contract_size จริง. xag_lot = xau_lot·(cXAU/cXAG)·|β|."""
    xl = float(_cfg("PAIRS_XAU_LOT", 0.0)) or float(_cfg("MIN_LOT", 0.02))
    ia = mt5.symbol_info(xau_sym); ib = mt5.symbol_info(xag_sym)
    ca = getattr(ia, "trade_contract_size", 100) or 100
    cb = getattr(ib, "trade_contract_size", 5000) or 5000
    raw = xl * (ca / cb) * abs(beta)
    step = getattr(ib, "volume_step", 0.01) or 0.01
    xag_lot = round(round(raw / step) * step, 2)
    xag_lot = max(getattr(ib, "volume_min", 0.01) or 0.01, min(xag_lot, getattr(ib, "volume_max", 100) or 100))
    return round(xl, 2), xag_lot


def tick(force=False):
    """เรียกทุก cycle. gate PAIRS_LIVE. fail-soft. คืน summary หรือ None."""
    try:
        if not _cfg("PAIRS_LIVE", False):
            return None
        import MetaTrader5 as mt5
        from connectors.pair_collector import _broker_map
        lg_a, lg_b = _pair_syms()
        bm = _broker_map() or {}
        xau = bm.get(lg_a, lg_a); xag = bm.get(lg_b, lg_b)
        mt5.symbol_select(xau, True); mt5.symbol_select(xag, True)
        win = int(_cfg("PAIRS_WIN", 120))
        y, x = _aligned(mt5, xau, xag, win + 400)
        if y is None or len(y) < win + 2:
            return {"ok": False}
        beta = float(np.polyfit(x[-win:], y[-win:], 1)[0])
        spread = y[-win:] - beta * x[-win:]
        m, sd = float(spread.mean()), float(spread.std())
        if sd <= 0:
            return {"ok": False}
        z = (float(y[-1]) - beta * float(x[-1]) - m) / sd
        mag = _magic()
        pos = _positions(mt5, mag)
        st = _load()
        z_in = float(_cfg("PAIRS_Z_IN", 2.0)); z_out = float(_cfg("PAIRS_Z_OUT", 0.5)); z_stop = float(_cfg("PAIRS_Z_STOP", 3.5))

        # ── มี position อยู่ → เช็ค exit ──
        if pos:
            side = st.get("dir")                          # 'long_spread' / 'short_spread'
            if len(pos) < 2:                              # ขาหาย (SL/manual) → ปิดที่เหลือ reset (กัน naked)
                for p in pos:
                    _close(mt5, p)
                logger.warning("[PAIRS] ขาไม่ครบ 2 → ปิดที่เหลือ reset")
                _save({"open": False}); return {"ok": True, "action": "repair-close"}
            hit_stop = abs(z) >= z_stop
            hit_out = abs(z) <= z_out
            if hit_stop or hit_out:
                okc = all(_close(mt5, p) for p in pos)
                logger.info(f"[PAIRS] EXIT {side} z={z:+.2f} ({'STOP' if hit_stop else 'revert'}) closed={okc}")
                _save({"open": False}); return {"ok": True, "action": "exit", "z": round(z, 2)}
            return {"ok": True, "action": "hold", "z": round(z, 2)}

        # ── flat → เช็ค entry ──
        if st.get("open"):                                # state บอก open แต่ไม่มี pos → reset
            _save({"open": False})
        if abs(z) < z_in:
            return {"ok": True, "action": "flat", "z": round(z, 2)}
        # z>z_in: spread สูง → short spread (SELL XAU + BUY XAG); z<−z_in → long spread
        short_spread = z > 0
        xau_dir = "SELL" if short_spread else "BUY"
        xag_dir = "BUY" if short_spread else "SELL"
        xl, bl = _hedge_lots(mt5, xau, xag, beta)
        t1 = _open_leg(mt5, xau, xau_dir, xl, mag)
        if not t1:
            return {"ok": False, "action": "entry-fail-leg1"}
        t2 = _open_leg(mt5, xag, xag_dir, bl, mag)
        if not t2:                                        # atomic: leg2 fail → ปิด leg1 ทันที
            for p in _positions(mt5, mag):
                _close(mt5, p)
            logger.warning("[PAIRS] leg2 fail → ปิด leg1 (atomic, ไม่มีขาโดด)")
            _save({"open": False}); return {"ok": False, "action": "entry-atomic-abort"}
        _save({"open": True, "dir": "short_spread" if short_spread else "long_spread",
               "entry_z": round(z, 2), "beta": round(beta, 2), "xau_lot": xl, "xag_lot": bl,
               "xau_ticket": t1, "xag_ticket": t2})
        logger.info(f"[PAIRS] ENTRY {'short' if short_spread else 'long'}-spread z={z:+.2f} β={beta:.1f} "
                    f"XAU {xau_dir} {xl} + XAG {xag_dir} {bl}")
        return {"ok": True, "action": "entry", "z": round(z, 2)}
    except Exception as e:
        logger.debug(f"[PAIRS] tick fail-soft: {e}")
        return None


def snapshot():
    """สถานะสด (dashboard/debug) — z, β, position. 0 order."""
    try:
        import MetaTrader5 as mt5
        from connectors.pair_collector import _broker_map
        lg_a, lg_b = _pair_syms(); bm = _broker_map() or {}
        xau = bm.get(lg_a, lg_a); xag = bm.get(lg_b, lg_b)
        win = int(_cfg("PAIRS_WIN", 120))
        y, x = _aligned(mt5, xau, xag, win + 400)
        if y is None:
            return {"ok": False}
        beta = float(np.polyfit(x[-win:], y[-win:], 1)[0])
        sp = y[-win:] - beta * x[-win:]; sd = float(sp.std())
        z = (float(y[-1]) - beta * float(x[-1]) - float(sp.mean())) / sd if sd else 0.0
        st = _load()
        return {"ok": True, "z": round(z, 2), "beta": round(beta, 2), "live": bool(_cfg("PAIRS_LIVE", False)),
                "position": st.get("dir") if st.get("open") else None, "entry_z": st.get("entry_z")}
    except Exception:
        return {"ok": False}
