"""agents/multi_symbol_executor.py — วางออเดอร์จริงบน symbol อื่น (นอกทอง) ต่อ combo ที่ toggle=LIVE.

ที่มา: session พิสูจน์ว่า entry algo บนทอง "ไม่มี edge" (full-history exp_R −0.137) แต่ **WTI momentum
(SL×0.7) = edge แท้** (exp_R +2.4R, t-stat 15, period-stable ทุกยุค, มีเหตุผลโครงสร้าง). บอท v1 เทรด
symbol เดียว (GOLD#) — ไฟล์นี้เพิ่ม "live path" ให้ symbol อื่นโดยไม่แตะ pipeline ทอง.

**2-ชั้น gate (default = 0 order จริง):**
  1. config.MULTI_SYMBOL_LIVE=false (default) → tick() return ทันที
  2. ทุก combo default=SHADOW → ต่อให้เปิด master ก็ยังต้อง toggle combo เป็น LIVE ทีละตัว
เปิดครบ 2 ชั้น → combo นั้นวางออเดอร์จริง; combo อื่นยัง shadow (paper) ที่ shadow_engine เหมือนเดิม.

Entry = signal เดียวกับ shadow (algo_registry.get(algo).evaluate) → open_order(symbol=broker, comment="MSE-<algo>").
Management = **self-contained R/ATR-relative** (BE + trailing เหมือน shadow_resolve_managed) apply บน
position จริงผ่าน TRADE_ACTION_SLTP — *ไม่* เรียก manage_* ของทอง (ค่านั้น hardcode pip-scale ทอง).
fail-soft ทุกจุด: error ที่ combo ไหน = ข้าม, ไม่ล้ม cycle. อ่านโดย trading_graph.node_position_mgmt ทุก cycle.
"""
import json
import os

from loguru import logger

from agents import algo_registry as _reg
from agents import shadow_switches as _sw

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE = os.path.join(_BASE, "data", "mse_state.json")
_FILLS = os.path.join(_BASE, "logs", "real_fills")     # real closed-trade journal ต่อ combo (edge จริงจากเงินจริง)
_BARS_COUNT = 600
_MIN_BARS = 520


# ── SL multiplier ต่อ symbol (WTI 0.7 = validated; ตัวอื่น 1.0) ─────────────
def _sl_mult_map():
    """parse config.ALGO_SL_MULT 'SYM:mult,...' → {sym: float}. fail-soft → {}."""
    import config as _cfg
    raw = getattr(_cfg, "ALGO_SL_MULT", "") or ""
    out = {}
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok or ":" not in tok:
            continue
        sym, _, m = tok.partition(":")
        try:
            out[sym.strip()] = float(m)
        except ValueError:
            pass
    return out


# ── state (dedup entry ต่อ bar + จำ R ต่อ ticket ข้าม cycle) ────────────────
def _load_state():
    try:
        with open(_STATE, encoding="utf-8") as f:
            m = json.load(f)
            return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(_STATE), exist_ok=True)
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    except OSError:
        pass


# ── MT5 helpers (fail-soft) ───────────────────────────────────────────────
def _bars(broker, tf="H1", count=None):
    """(high, low, close, times) ตาม timeframe ของ algo (H1 = regime/mean_rev · D1 = tsmom). หรือ None.

    ⚡ perf: single-attempt copy_rates_from_pos (**ไม่ใช้ get_ohlcv ที่มี sleep-retry 1.5s×2**) —
    เครื่อง/โบรกอื่นที่ symbol map ไม่ตรง → copy_rates ว่าง → block 3s×2/combo/cycle. fail-fast → None → ข้าม combo."""
    try:
        import MetaTrader5 as mt5
        tfmap = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
        mt5_tf = tfmap.get(tf, mt5.TIMEFRAME_H1)
        if count is None:
            count = 400 if tf == "D1" else _BARS_COUNT       # D1 ~400 บาร์พอ L=252 + buffer
        min_bars = 282 if tf == "D1" else _MIN_BARS          # tsmom ต้อง ≥ max(LOOKBACK 252)+30
        mt5.symbol_select(broker, True)                       # ensure subscribed (ครั้งแรก) — ไม่ sleep
        rates = mt5.copy_rates_from_pos(broker, mt5_tf, 0, count)   # single attempt, no sleep-retry
        if rates is None or len(rates) < min_bars:
            return None
        return (rates["high"].astype(float), rates["low"].astype(float),
                rates["close"].astype(float), rates["time"])
    except Exception:
        return None


def _meta(broker):
    """(point, digits) ของ broker symbol หรือ (None, None)."""
    try:
        import MetaTrader5 as mt5
        info = mt5.symbol_info(broker)
        if info and info.point:
            return float(info.point), int(info.digits)
    except Exception:
        pass
    return None, None


def _our_positions(broker):
    """open positions ของ engine นี้บน broker symbol (magic ระบบ). ทองอยู่คนละ symbol → ไม่ปน."""
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYSTEM_MAGIC
        pos = mt5.positions_get(symbol=broker)
        if pos is None:
            return None                                      # fetch fail (terminal hiccup) — แยกจาก "ไม่มีไม้" กัน false-close
        return [p for p in pos if p.magic == SYSTEM_MAGIC]
    except Exception:
        return None


def _total_mse_positions():
    """นับไม้ MSE รวมทุก symbol = magic ระบบ + symbol != ทอง (MSE เปิดเฉพาะ non-gold; ไม่พึ่ง comment ที่ broker อาจลบ)."""
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYSTEM_MAGIC, SYMBOL as GOLD
        pos = mt5.positions_get() or []
        return sum(1 for p in pos if p.magic == SYSTEM_MAGIC and p.symbol != GOLD)
    except Exception:
        return 0


def _protected_mse_positions():
    """นับไม้ MSE (non-gold) ที่ SL พ้นทุนแล้ว (BE±buffer = protected, ไม่เสี่ยงขาดทุน).
    ใช้ขยาย global cap: ไม้ protected ไม่นับกิน slot (trailing แล้วปลอดภัย) — pattern เดียวกับ count_protected_slots ทอง."""
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        from connectors.mt5_connector import SYSTEM_MAGIC, SYMBOL as GOLD
        buf = float(getattr(_cfg, "BE_BUFFER_PIPS", 200))
        n = 0
        for p in (mt5.positions_get() or []):
            if p.magic != SYSTEM_MAGIC or p.symbol == GOLD or p.sl == 0:
                continue
            info = mt5.symbol_info(p.symbol)
            if not info or not info.point:
                continue
            pt = info.point
            is_buy = p.type == mt5.ORDER_TYPE_BUY
            if (is_buy and p.sl >= p.price_open + buf * pt) or (not is_buy and p.sl <= p.price_open - buf * pt):
                n += 1
        return n
    except Exception:
        return 0


def _simple_atr(high, low, close, period=14):
    """ATR(14) Wilder inline (เหมือน shadow_resolve_managed — self-contained)."""
    n = len(close)
    out = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = float(high[i]), float(low[i]), float(close[i - 1])
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    s = 0.0
    for i in range(1, n):
        if i <= period:
            s += tr[i]
            out[i] = s / i
        else:
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def _cfgf(name, default):
    import config as _cfg
    try:
        return float(getattr(_cfg, name, default))
    except Exception:
        return default


def _clamp_sl_atr(sl_pips, bars, point):
    """clamp sl_pips เป็นช่วง [MIN,MAX]×ATR (safety กัน ATR เพี้ยน→SL แคบ/กว้างบ้าๆ).
    ไม่แตะ edge เคสปกติ (WTI SL~1×ATR อยู่กลางช่วง 0.5-4). ATR≤0/ปิด clamp → คืนค่าเดิม."""
    lo = _cfgf("MSE_SL_MIN_ATR", 0.5)
    hi = _cfgf("MSE_SL_MAX_ATR", 4.0)
    if lo <= 0 and hi <= 0:
        return sl_pips
    high, low, close, _t = bars
    atr = _simple_atr(high, low, close)
    atr_v = atr[-1] if atr else 0.0
    if atr_v <= 0 or point <= 0:
        return sl_pips                                   # ไม่มี ATR ที่เชื่อได้ → ไม่ clamp
    atr_pips = atr_v / point
    lo_p = lo * atr_pips if lo > 0 else 0.0
    hi_p = hi * atr_pips if hi > 0 else float("inf")
    clamped = max(lo_p, min(sl_pips, hi_p))
    if abs(clamped - sl_pips) > 1e-9:
        logger.info(f"[MSE] SL clamp {sl_pips:.0f}p → {clamped:.0f}p (ATR={atr_pips:.0f}p · ช่วง {lo}-{hi}×ATR)")
    return clamped


def _apply_structural_sl(direction, entry, bars, point, broker, base_sl_pips, base_tp_pips, algo_id, symbol):
    """flag STRUCTURAL_SL_MSE: วาง SL ที่ปลายไส้ D1 ปิดล่าสุด เสมอ (ไม่ clamp). คง RR (TP recompute).
    default OFF → base เดิม. fail-soft. คืน (sl_pips, tp_pips, force_min_lot)."""
    import config as _cfg
    from agents import structural_sl
    high, low, close, _t = bars
    atr_list = _simple_atr(high, low, close)
    atr = atr_list[-1] if atr_list else 0.0
    sl_pips, tp_pips, meta = structural_sl.live_adjust(
        direction, entry, atr, point, broker, base_sl_pips, base_tp_pips, _cfg,
        enabled=getattr(_cfg, "STRUCTURAL_SL_MSE", False))
    if meta is not None:
        logger.info(f"[MSE] structural SL {algo_id}:{symbol} {meta['base_pips']}p → {meta['struct_pips']}p "
                    f"(ปลายไส้ D1 @ {meta['sl_price']}) → min lot")
    return sl_pips, tp_pips, (meta is not None and meta.get("force_min_lot", False))


def _send_sltp(broker, ticket, new_sl, tp, digits):
    """ขยับ SL ของ position (TRADE_ACTION_SLTP) บน broker symbol ใดก็ได้. คืน ok."""
    try:
        import MetaTrader5 as mt5
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": broker,
               "position": int(ticket), "sl": round(float(new_sl), digits), "tp": round(float(tp), digits)}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            logger.debug(f"[MSE] SLTP fail ticket={ticket}: {r.retcode if r else mt5.last_error()}")
            return False
        return True
    except Exception as e:
        logger.debug(f"[MSE] SLTP exc ticket={ticket}: {e}")
        return False


# ── management: R/ATR-relative BE + trailing (symbol-agnostic) ─────────────
def _manage(broker, positions, bars, point, digits, combo_state):
    """ต่อ position ที่เราถือ → คำนวณ SL เป้าหมาย (BE→trailing, improve-only) แล้ว push ผ่าน SLTP.
    R (=sl_dist) จำจาก state ต่อ ticket (คงที่แม้ย้าย SL ไป BE แล้ว). fail-soft ต่อ position."""
    if not positions:
        return 0
    import MetaTrader5 as mt5
    import config as _cfg
    high, low, close, _times = bars
    atr_v = _simple_atr(high, low, close)
    be_trig_r = _cfgf("BE_TRIGGER_R", 0.8)
    be_buf = _cfgf("BE_BUFFER_PIPS", 200) * point
    tr_on = bool(getattr(_cfg, "TRAILING_STOP", False))
    tr_min_r = _cfgf("TRAILING_MIN_PROFIT_R", 1.5)
    tr_mult = _cfgf("TRAILING_ATR_MULT", 0.8)
    tr_look = int(_cfgf("TRAILING_LOOKBACK", 6))
    tickets = combo_state.setdefault("tickets", {})
    moved = 0

    tick = mt5.symbol_info_tick(broker)
    for p in positions:
        try:
            is_buy = (p.type == mt5.ORDER_TYPE_BUY)
            entry = float(p.price_open)
            key = str(p.ticket)
            ctx = tickets.get(key)
            if ctx and float(ctx.get("sl_dist", 0)) > 0:
                sl_dist = float(ctx["sl_dist"])                 # R เดิม (คงที่)
            else:                                               # restart/orphan → reconstruct จาก SL ปัจจุบัน
                sl_dist = abs(entry - float(p.sl)) if p.sl else 0.0
                if sl_dist <= 0:
                    continue
                tickets[key] = {"sl_dist": sl_dist, "dir": "BUY" if is_buy else "SELL"}
            cur = (tick.bid if is_buy else tick.ask) if tick else float(close[-1])
            prof_r = ((cur - entry) if is_buy else (entry - cur)) / sl_dist

            target = float(p.sl) if p.sl else (entry - sl_dist if is_buy else entry + sl_dist)
            # breakeven
            if prof_r >= be_trig_r:
                be_sl = entry + be_buf if is_buy else entry - be_buf
                target = max(target, be_sl) if is_buy else min(target, be_sl)
            # trailing (swing ± mult×ATR ของ symbol นี้)
            if tr_on and prof_r >= tr_min_r:
                atr = float(atr_v[-1]) if atr_v else 0.0
                if atr > 0 and len(low) > tr_look:
                    buf = tr_mult * atr
                    if is_buy:
                        swing = min(float(low[k]) for k in range(len(low) - tr_look, len(low)))
                        target = max(target, swing - buf)
                    else:
                        swing = max(float(high[k]) for k in range(len(high) - tr_look, len(high)))
                        target = min(target, swing + buf)

            improved = (target > float(p.sl) + point) if is_buy else (target < float(p.sl) - point) if p.sl else True
            if improved and _send_sltp(broker, p.ticket, target, p.tp, digits):
                moved += 1
        except Exception as e:
            logger.debug(f"[MSE] manage fail ticket={getattr(p,'ticket','?')}: {e}")
    return moved


# ── tsmom management: exit-on-flip (ปิดไม้เมื่อสัญญาณ D1 กลับ; ไม่ BE/trail; disaster SL คงเดิม) ──
def _close_position(broker, p, digits):
    """ปิด position ด้วย market order ฝั่งตรงข้าม (TRADE_ACTION_DEAL). คืน ok. fail-soft."""
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYSTEM_MAGIC
        tick = mt5.symbol_info_tick(broker)
        if not tick:
            return False
        is_buy = (p.type == mt5.ORDER_TYPE_BUY)
        try:
            from connectors.mt5_connector import _pick_filling
            filling = _pick_filling(broker)
        except Exception:
            filling = mt5.ORDER_FILLING_IOC
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": broker, "position": int(p.ticket),
               "volume": float(p.volume),
               "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
               "price": tick.bid if is_buy else tick.ask, "deviation": 30,
               "magic": SYSTEM_MAGIC, "comment": "MSE-flip-exit",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            logger.debug(f"[MSE] close fail ticket={p.ticket}: {r.retcode if r else mt5.last_error()}")
            return False
        return True
    except Exception as e:
        logger.debug(f"[MSE] close exc ticket={getattr(p,'ticket','?')}: {e}")
        return False


def _manage_tsmom(algo_id, symbol, broker, positions, bars, point, digits, combo_state):
    """tsmom = ถือจนสัญญาณ D1 กลับ. re-evaluate; ถ้ามีสัญญาณ dir ตรงข้าม → ปิดไม้ (market).
    disaster SL (ตั้งตอนเข้า) คงเดิม — ไม่ BE/trail. FLAT/บาร์ไม่พอ → ถือต่อ (กัน false-close)."""
    if not positions:
        return 0
    import MetaTrader5 as mt5
    algo = _reg.get(algo_id)
    vo = algo.evaluate(symbol, bars, point=point) if algo else None
    new_dir = vo.get("dir") if vo else None
    if not new_dir:                                       # ไม่มีสัญญาณชัด → ถือต่อ (ไม่ปิด)
        return 0
    closed = 0
    tickets = combo_state.get("tickets") or {}
    for p in positions:
        pos_dir = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
        if new_dir != pos_dir and _close_position(broker, p, digits):
            tickets.pop(str(p.ticket), None)
            closed += 1
            logger.info(f"[MSE] tsmom flip → close {algo_id}:{symbol} #{p.ticket} ({pos_dir}→{new_dir})")
    return closed


# ── real closed-trade capture (edge จริงจากไม้ที่ปิดแล้ว — leakage-free features) ──────
def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _entry_features(bars, point):
    """snapshot feature ที่แท่งปิดล่าสุด (รู้ได้ตอนเข้าไม้ = ไม่ leak outcome)."""
    try:
        import regime_lib as R
        high, low, close, times = bars
        er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
        vol = R.vol_percentile(close); atr = R.atr(high, low, close)
        i = len(close) - 2
        from datetime import datetime, timezone
        hour = datetime.fromtimestamp(int(times[i]), timezone.utc).hour
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        return {"er": round(float(er[i]), 4), "adx": round(float(adx[i]), 2),
                "vol_pct": round(float(vol[i]), 3), "atr": round(av, 4),
                "atr_pips": round(av / point, 1) if point else 0, "hour": hour,
                "regime": R.detect_regime(er[i], adx[i], vol[i])}
    except Exception:
        return {}


def _append_fill(algo_id, symbol, rec):
    try:
        os.makedirs(_FILLS, exist_ok=True)
        with open(os.path.join(_FILLS, f"{algo_id}__{symbol}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _fill_has_ticket(algo_id, symbol, ticket):
    """ticket นี้ถูกบันทึกใน journal แล้วหรือยัง (กัน duplicate line ตอน crash-recovery)."""
    fp = os.path.join(_FILLS, f"{algo_id}__{symbol}.jsonl")
    if not os.path.exists(fp):
        return False
    tk = f'"ticket": {int(ticket)}'
    try:
        with open(fp, encoding="utf-8") as f:
            return any(tk in ln for ln in f)
    except OSError:
        return False


def _record_closed(algo_id, symbol, ticket, ctx):
    """ดึง realized จาก deal history by **position_id** (ไม่พึ่ง magic — broker reset magic=0 ตอนปิด SL/TP).
    คำนวณ realized_R เทียบ sl_dist เริ่มต้น → append real-fill journal."""
    try:
        import MetaTrader5 as mt5
        if _fill_has_ticket(algo_id, symbol, ticket):        # กัน dup (crash ระหว่าง append↔pop รอบก่อน)
            return True
        deals = mt5.history_deals_get(position=int(ticket))
        if not deals:
            return False
        profit = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals)
        outs = [d for d in deals if getattr(d, "entry", None) == mt5.DEAL_ENTRY_OUT]   # exit = VWAP ของ OUT deals (partial-close ถูก)
        if outs:
            vol = sum(float(d.volume) for d in outs) or 1.0
            exit_px = sum(float(d.price) * float(d.volume) for d in outs) / vol
        else:
            exit_px = float(deals[-1].price)
        entry = float(ctx.get("entry") or (deals[0].price if deals else 0.0))
        sl_dist = float(ctx.get("sl_dist") or 0.0)
        is_buy = ctx.get("dir") == "BUY"
        rr = (((exit_px - entry) if is_buy else (entry - exit_px)) / sl_dist) if sl_dist > 0 else None
        _append_fill(algo_id, symbol, {
            "algo_id": algo_id, "symbol": symbol, "ticket": int(ticket), "dir": ctx.get("dir"),
            "entry": round(entry, 5), "exit": round(exit_px, 5),
            "realized_R": round(rr, 3) if rr is not None else None, "profit": round(profit, 2),
            "opened_ts": ctx.get("opened_ts"), "closed_ts": _now_iso(),
            "features": ctx.get("features", {})})
        logger.info(f"[MSE] closed {algo_id}:{symbol} #{ticket} R={round(rr,3) if rr is not None else '—'} pnl={round(profit,2)}")
        return True
    except Exception as e:
        logger.debug(f"[MSE] record close #{ticket} fail: {e}")
        return False


def _reconcile_closed(algo_id, symbol, positions, combo_state):
    """ticket ที่เคยถือแต่หายจาก open = ปิดแล้ว → บันทึก real-fill + ลบออกจาก state."""
    tickets = combo_state.get("tickets") or {}
    if not tickets:
        return 0
    open_ids = {str(p.ticket) for p in positions}
    closed = [t for t in list(tickets) if t not in open_ids]
    done = 0
    for tk in closed:
        ctx = tickets[tk]
        if _record_closed(algo_id, symbol, tk, ctx):         # pop เฉพาะเมื่อบันทึกสำเร็จ (กัน fill หายตอน history ยังไม่ sync)
            tickets.pop(tk, None); done += 1
        else:
            ctx["_tries"] = int(ctx.get("_tries", 0)) + 1
            if ctx["_tries"] >= 6:                           # history ไม่มา 6 รอบ → ปล่อย (กัน ctx leak)
                tickets.pop(tk, None)
    return done


# ── entry: signal เดียวกับ shadow → open_order จริง ───────────────────────
def _maybe_enter(algo_id, symbol, broker, bars, point, sl_mult, combo_state, max_pos=1, positions=None):
    """ถ้ายังไม่ครบ max_pos + มี signal ใหม่ (bar_ts ยังไม่เคยเข้า) → open_order จริง. คืน 1 ถ้าเปิด."""
    import config as _cfg
    algo = _reg.get(algo_id)
    if algo is None:
        return 0
    vo = algo.evaluate(symbol, bars, point=point)
    if not vo or not vo.get("bar_ts"):
        return 0
    if vo["bar_ts"] == combo_state.get("last_bar_ts"):
        return 0                                                # เข้าไม้บาร์นี้ **สำเร็จ**ไปแล้ว (dedup ต่อ signal-bar)
    # price-proximity guard: มีไม้ทิศเดียวกันเปิดใกล้ (≤ n×ATR) → skip กัน stack เกาะจุดเดิม
    _gap = float(getattr(_cfg, "ALGO_ENTRY_MIN_GAP_ATR", 0) or 0)
    if _gap > 0 and positions:
        import MetaTrader5 as _mt5
        _dir_t = _mt5.ORDER_TYPE_BUY if vo["dir"] == "BUY" else _mt5.ORDER_TYPE_SELL
        _same = [p.price_open for p in positions if p.type == _dir_t]
        _atr_l = _simple_atr(*bars[:3])
        _atr = _atr_l[-1] if _atr_l else 0.0
        from agents import structural_sl as _ssl
        if _ssl.near_existing(float(vo["entry"]), _atr, _same, _gap):
            logger.debug(f"[MSE] {algo_id}:{symbol} {vo['dir']} skip — มีไม้ทิศเดียวใกล้ ≤{_gap}×ATR (กัน stack จุดเดิม)")
            return 0
    import time as _time
    if _time.time() < float(combo_state.get("retry_after", 0)):
        return 0                                                # เพิ่ง open fail → cooldown (กัน retry-spam ทุก tick) แต่ไม่บล็อกถาวร
    sl_pips_eff = float(vo["sl_pips"]) * sl_mult                 # edge = algo SL × mult (WTI 0.7)
    sl_pips_eff = _clamp_sl_atr(sl_pips_eff, bars, point)        # safety clamp (ไม่แตะ edge เคสปกติ)
    tp_pips_eff = float(vo["tp_pips"])
    sl_pips_eff, tp_pips_eff, _force_min = _apply_structural_sl(
        vo["dir"], float(vo["entry"]), bars, point, broker, sl_pips_eff, tp_pips_eff, algo_id, symbol)
    _lot = _cfgf("MIN_LOT", 0.01) if _force_min else None   # structural = min lot เสมอ (SL กว้าง, ยอม risk%)
    from connectors.mt5_connector import open_order
    res = open_order(vo["dir"], sl_pips_eff, tp_pips_eff, lot=_lot,
                     comment=f"MSE-{algo_id}", symbol=broker, max_open_override=max_pos)
    if res and res.get("success") and res.get("ticket"):
        combo_state["last_bar_ts"] = vo["bar_ts"]              # dedup **เฉพาะเมื่อสำเร็จ** (fail → retry บาร์เดิมได้หลัง cooldown)
        combo_state.pop("retry_after", None)
        combo_state.setdefault("tickets", {})[str(res["ticket"])] = {
            "sl_dist": sl_pips_eff * point, "dir": vo["dir"], "entry_bar_ts": vo["bar_ts"],
            "entry": float(res.get("price") or 0.0), "opened_ts": _now_iso(),
            "features": _entry_features(bars, point)}          # leakage-free snapshot → real-fill edge ตอนปิด
        logger.info(f"[MSE] LIVE entry {algo_id}:{symbol} {vo['dir']} @ {res.get('price')} "
                    f"SL={sl_pips_eff:.0f}p (×{sl_mult}) ticket={res['ticket']}")
        return 1
    combo_state["retry_after"] = _time.time() + _cfgf("MSE_ENTRY_RETRY_COOLDOWN", 300)   # fail → รอ 5 นาที ค่อย retry (ไม่ mark บาร์ handled)
    logger.warning(f"[MSE] entry {algo_id}:{symbol} ไม่สำเร็จ: {res.get('error') if res else 'no result'} "
                   f"— retry ใน {int(_cfgf('MSE_ENTRY_RETRY_COOLDOWN', 300))}s")
    return 0


def tick(force=False):
    """เรียกทุก cycle จาก node_position_mgmt. Gated ด้วย MULTI_SYMBOL_LIVE. fail-soft; 0 order เมื่อ gate ปิด.
    คืน summary dict หรือ None เมื่อ gate ปิด."""
    import config as _cfg
    if not getattr(_cfg, "MULTI_SYMBOL_LIVE", False):    # master gate เสมอ (force ไม่ข้าม — กันรันมือแล้ววางออเดอร์จริง)
        return None
    eligible = _reg.combos(_reg.UNIVERSE)
    live = _sw.combos_in(_sw.LIVE, eligible)
    if not live:
        return {"combos": 0, "opened": 0, "managed": 0}

    from connectors.pair_collector import _broker_map
    bmap = _broker_map()
    sl_mult = _sl_mult_map()
    max_pos = max(1, int(getattr(_cfg, "MSE_MAX_POSITIONS", 1)))   # stack ไม้/combo (min 1; 0 ไม่ได้แปลว่า "ปิด" — ปิดที่ MULTI_SYMBOL_LIVE=false หรือ toggle SHADOW)
    max_total = int(getattr(_cfg, "MSE_MAX_TOTAL", 0))            # เพดานรวมทุก symbol (0 = ไม่จำกัด)
    if max_total > 0:
        max_total += _protected_mse_positions()                  # ขยาย cap ตามไม้ protected (trailing แล้วปลอดภัย ไม่กิน slot) — pattern เดียวกับทอง
    total_open = _total_mse_positions() if max_total > 0 else 0    # snapshot ต้น cycle; +opened ระหว่างวนลูป
    state = _load_state()
    dirty = False
    opened = managed = ok = 0

    for algo_id, symbol in live:
        try:
            broker = bmap.get(symbol, symbol)
            algo_obj = _reg.get(algo_id)
            tf = getattr(algo_obj, "timeframe", "H1")
            mgmt = getattr(algo_obj, "mgmt", "managed")
            bars = _bars(broker, tf)
            if bars is None:
                continue
            point, digits = _meta(broker)
            if point is None:
                continue
            ck = f"{algo_id}:{symbol}"
            cstate = state.setdefault(ck, {})
            positions = _our_positions(broker)
            if positions is None:                            # fetch fail → ข้าม combo รอบนี้ (ห้าม manage ด้วยข้อมูลพัง)
                continue
            # ไม้ปิด → บันทึกโดย trade_recorder (universal, comment MSE-<algo>) แล้ว — MSE ไม่ record ซ้ำ
            # management ตาม algo: tsmom = exit-on-flip · อื่น = BE+trailing (SL/TP)
            if mgmt == "tsmom_flip":
                managed += _manage_tsmom(algo_id, symbol, broker, positions, bars, point, digits, cstate)
            else:
                managed += _manage(broker, positions, bars, point, digits, cstate)
            room_total = (max_total <= 0) or (total_open + opened < max_total)   # global cap ยังมีที่ว่าง
            if len(positions) < max_pos and room_total:         # ผ่านทั้ง per-combo + รวมทุก symbol
                op = _maybe_enter(algo_id, symbol, broker, bars, point,
                                  sl_mult.get(symbol, 1.0), cstate, max_pos, positions)   # LIVE = วางจริง (โบรก reject เองถ้าปิดคู่)
                opened += op
            elif not room_total:
                logger.debug(f"[MSE] {ck}: global cap {max_total} ถึงแล้ว (open={total_open + opened}) — ข้าม entry")
            ok += 1
            dirty = True
        except Exception as e:
            logger.debug(f"[MSE] {algo_id}:{symbol} fail-soft: {e}")
    if dirty:
        _save_state(state)
    if opened or managed:
        logger.info(f"[MSE] tick: combos={ok}/{len(live)} opened={opened} managed={managed}")
    return {"combos": ok, "opened": opened, "managed": managed}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa: F401 (load .env)
    print("MSE tick:", tick(force=True))
