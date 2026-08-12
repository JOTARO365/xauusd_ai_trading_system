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


# ── per-algo magic ────────────────────────────────────────────────────────
# แต่ละ MSE algo ได้ magic = SYSTEM_MAGIC + offset → ถือไม้แยกบน symbol เดียวกันได้ (account hedging)
# + จัดการ SL แยกต่อ algo. ทอง = SYSTEM_MAGIC (offset 0, gold path) ไม่ปน. offset 1..999 = ช่วง MSE.
_ALGO_MAGIC = {"regime_momentum": 1, "mean_reversion": 2, "tsmom_d1": 3,
               "regime_momentum_fvg": 4, "sweep_reversal": 5, "macro_momentum": 6, "confluence_15m": 8}
_MSE_OFF_MIN, _MSE_OFF_MAX = 1, 9999          # ช่วง offset ที่นับเป็น MSE (ไม่รวม 0 = ทอง/base)


def _magic_of(algo_id):
    """magic ต่อ algo (SYSTEM_MAGIC + offset คงที่). algo นอก map → offset จากชื่อ (deterministic, กันชน base)."""
    from connectors.mt5_connector import SYSTEM_MAGIC
    off = _ALGO_MAGIC.get(algo_id)
    if off is None:
        off = 100 + (sum(algo_id.encode()) % 900)     # 100..999 คงที่ข้าม restart (ไม่ใช้ hash ที่ random)
    return SYSTEM_MAGIC + off


def _is_mse_magic(m):
    """magic นี้อยู่ในช่วง MSE (per-algo) ไหม — ใช้นับ exposure รวมทุก algo."""
    from connectors.mt5_connector import SYSTEM_MAGIC
    return _MSE_OFF_MIN <= (int(m) - SYSTEM_MAGIC) <= _MSE_OFF_MAX


# ── cold-start gate ───────────────────────────────────────────────────────
# เทรดเฉพาะ signal จากบาร์ที่ปิด**หลัง** engine เริ่ม cycle แรก. กัน stale-entry: ตอน start
# marker ว่าง → signal ของบาร์ที่ปิดไปก่อนหน้าจะถูกเข้า market ที่ราคาไกลจากจุด setup.
_ENGINE_START = None                             # epoch (UTC) ของ tick แรก
_TF_SECONDS = {"H1": 3600, "H4": 14400, "D1": 86400}


def _signal_stale(bar_ts_iso, algo):
    """True ถ้าบาร์ของ signal ปิดก่อน engine เริ่ม (bar_ts + tf ≤ start) → stale ไม่ควรเข้า."""
    if _ENGINE_START is None or not bar_ts_iso:
        return False
    try:
        from datetime import datetime
        bt = datetime.fromisoformat(bar_ts_iso).timestamp()      # bar_ts = เวลาเปิดบาร์ (UTC) → ปิดที่ +tf
        tf = _TF_SECONDS.get(getattr(algo, "timeframe", "H1"), 3600)
        return (bt + tf) <= _ENGINE_START
    except Exception:
        return False


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


def _our_positions(broker, magic):
    """open positions ของ **algo นี้** บน broker symbol (magic ต่อ algo). algo/ทองอื่น = คนละ magic → ไม่ปน."""
    try:
        import MetaTrader5 as mt5
        pos = mt5.positions_get(symbol=broker)
        if pos is None:
            return None                                      # fetch fail (terminal hiccup) — แยกจาก "ไม่มีไม้" กัน false-close
        return [p for p in pos if p.magic == magic]
    except Exception:
        return None


def _position_protected(p, point):
    """ไม้นี้ trailing เลย BE แล้ว (SL พ้นทุน ±BE_BUFFER = risk-free) → ไม่ควรกิน entry-slot.
    ใช้ทั้งขยาย global cap และปลด per-combo slot (algo เดิม/อื่นเข้าเพิ่มได้เมื่อไม้เก่าปลอดภัยแล้ว)."""
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        if not getattr(p, "sl", 0) or not point:
            return False
        buf = float(getattr(_cfg, "BE_BUFFER_PIPS", 200)) * point
        is_buy = p.type == mt5.ORDER_TYPE_BUY
        return (is_buy and p.sl >= p.price_open + buf) or (not is_buy and p.sl <= p.price_open - buf)
    except Exception:
        return False


def _total_mse_positions():
    """นับไม้ MSE รวมทุก algo/symbol = magic ในช่วง MSE (per-algo) + symbol != ทอง. คุม exposure รวม (MSE_MAX_TOTAL)."""
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYMBOL as GOLD
        pos = mt5.positions_get() or []
        return sum(1 for p in pos if _is_mse_magic(p.magic) and p.symbol != GOLD)
    except Exception:
        return 0


def _protected_mse_positions():
    """นับไม้ MSE (non-gold) ที่ SL พ้นทุนแล้ว (BE±buffer = protected, ไม่เสี่ยงขาดทุน).
    ใช้ขยาย global cap: ไม้ protected ไม่นับกิน slot (trailing แล้วปลอดภัย) — pattern เดียวกับ count_protected_slots ทอง."""
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import SYMBOL as GOLD
        n = 0
        for p in (mt5.positions_get() or []):
            if not _is_mse_magic(p.magic) or p.symbol == GOLD or p.sl == 0:
                continue
            info = mt5.symbol_info(p.symbol)
            if not info or not info.point:
                continue
            if _position_protected(p, info.point):
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
    try:                                                    # scalp (confluence_15m) ใช้ SL ของตัวเอง — D1-wick กว้างเกินสำหรับ M15 (ผิดจาก backtest)
        _a = _reg.get(algo_id)
        if _a is not None and getattr(_a, "klass", "") == "scalp":
            return base_sl_pips, base_tp_pips, False
    except Exception:
        pass
    high, low, close, _t = bars
    atr_list = _simple_atr(high, low, close)
    atr = atr_list[-1] if atr_list else 0.0
    _enabled = getattr(_cfg, "STRUCTURAL_SL_MSE", False)
    if _enabled and getattr(_cfg, "ATR_SL_SMALL_CAP", False):   # ทุนเล็ก → ATR SL (native) แทน structural (user 08-09)
        try:                                                   # → SL แคบ → FF sizing คุม risk/DD ได้จริง
            import MetaTrader5 as _mt5
            _a = _mt5.account_info()
            if _a and _a.equity < float(getattr(_cfg, "CAPITAL_GATE_FLOOR", 20000)):
                _enabled = False
        except Exception:
            pass
    sl_pips, tp_pips, meta = structural_sl.live_adjust(
        direction, entry, atr, point, broker, base_sl_pips, base_tp_pips, _cfg,
        enabled=_enabled)
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
# momentum/breakout algo = ต้องปล่อยวิ่งถึง TP (RR2). trailing แน่นตัดกำไร (replay: +119%→+12%) → trail หลวม (ช้า+กว้าง)
_MOM_ALGOS = {"macro_momentum", "confluence_15m", "regime_momentum", "regime_momentum_fvg"}


def _manage(broker, positions, bars, point, digits, combo_state, algo_id=None):
    """ต่อ position ที่เราถือ → คำนวณ SL เป้าหมาย (BE→trailing, improve-only) แล้ว push ผ่าน SLTP.
    R (=sl_dist) จำจาก state ต่อ ticket (คงที่แม้ย้าย SL ไป BE แล้ว). fail-soft ต่อ position.
    momentum algo → trailing หลวม (TRAILING_MOM_*) ปล่อยวิ่งถึง TP; fade algo → trailing ปกติ."""
    if not positions:
        return 0
    import MetaTrader5 as mt5
    import config as _cfg
    _mom = algo_id in _MOM_ALGOS
    if _mom and bool(getattr(_cfg, "MOM_LET_RUN", True)):
        return 0                                            # momentum = fixed SL/TP ปล่อยวิ่งถึง TP (replay: +119% vs BE/trail +12%). ไม่ BE/trail
    high, low, close, _times = bars
    atr_v = _simple_atr(high, low, close)
    be_trig_r = _cfgf("BE_TRIGGER_R", 0.8)
    be_buf = _cfgf("BE_BUFFER_PIPS", 200) * point
    tr_on = bool(getattr(_cfg, "TRAILING_STOP", False))
    tr_min_r = _cfgf("TRAILING_MOM_MIN_R", 1.9) if _mom else _cfgf("TRAILING_MIN_PROFIT_R", 1.5)
    tr_mult = _cfgf("TRAILING_MOM_MULT", 3.0) if _mom else _cfgf("TRAILING_ATR_MULT", 0.8)
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
               "magic": int(p.magic), "comment": "MSE-flip-exit",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            logger.debug(f"[MSE] close fail ticket={p.ticket}: {r.retcode if r else mt5.last_error()}")
            return False
        return True
    except Exception as e:
        logger.debug(f"[MSE] close exc ticket={getattr(p,'ticket','?')}: {e}")
        return False


def _parse_combo_map(raw):
    """'algo:SYM=val;algo2:SYM2=val2' → {(algo,sym): val}. fail-soft {}."""
    out = {}
    for part in str(raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part or ":" not in part.split("=", 1)[0]:
            continue
        key, val = part.split("=", 1)
        algo, sym = key.split(":", 1)
        out[(algo.strip(), sym.strip())] = val.strip()
    return out


def _combo_tf(algo_id, symbol):
    """per-combo timeframe override (short-term H4 winners) หรือ None → ใช้ algo.timeframe."""
    import config as _c
    return _parse_combo_map(getattr(_c, "ALGO_TF_OVERRIDE", "")).get((algo_id, symbol)) or None


def _combo_ctx(algo_id, symbol):
    """ctx per-combo (lookbacks override สำหรับ tsmom H4) → dict หรือ None."""
    import config as _c
    v = _parse_combo_map(getattr(_c, "ALGO_LB_OVERRIDE", "")).get((algo_id, symbol))
    if v:
        try:
            lb = tuple(int(x) for x in v.split(",") if x.strip())
            if lb:
                return {"lookbacks": lb}
        except Exception:
            pass
    return None


def _manage_tsmom(algo_id, symbol, broker, positions, bars, point, digits, combo_state, ctx=None):
    """tsmom = ถือจนสัญญาณ D1 กลับ. re-evaluate; ถ้ามีสัญญาณ dir ตรงข้าม → ปิดไม้ (market).
    disaster SL (ตั้งตอนเข้า) คงเดิม — ไม่ BE/trail. FLAT/บาร์ไม่พอ → ถือต่อ (กัน false-close)."""
    if not positions:
        return 0
    import MetaTrader5 as mt5
    algo = _reg.get(algo_id)
    vo = algo.evaluate(symbol, bars, ctx=ctx, point=point) if algo else None
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


def _cdc_risk_too_high(broker, sl_pips, point):
    """True = block cdc entry/pyramid: risk ที่ min-lot × SL เกิน CDC_MAX_UNIT_RISK_PCT ของ equity.
    audit 08-12: ทอง micro min-lot 0.1 × 2N SL = 63%/ไม้ บน 1000฿ → guard กันเปิดตอนทุนน้อยเกิน SL."""
    import config as _cfg
    cap = float(getattr(_cfg, "CDC_MAX_UNIT_RISK_PCT", 3.0) or 0.0)
    if cap <= 0:
        return False
    try:
        import MetaTrader5 as mt5
        acct = mt5.account_info()
        eq = float(acct.equity) if acct else 0.0
        if eq <= 0:
            return True                                  # unfunded → block (กันเปิดบนบัญชีไม่มีเงิน)
        from connectors.mt5_connector import _lot_floor
        floor = _lot_floor(broker)
        tick = mt5.symbol_info_tick(broker)
        px = float(tick.ask) if tick else 0.0
        if px <= 0 or sl_pips <= 0:
            return False
        risk = abs(mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, broker, floor, px, px - sl_pips * point) or 0.0)
        return (risk / eq * 100.0) > cap
    except Exception:
        return False


def _manage_cdc(algo_id, symbol, broker, positions, bars, point, digits, combo_state, ctx=None):
    """cdc = ถือจน CDC Action Zone พลิก + Turtle pyramid (เติม unit ตามเทรนด์, flag OFF default).
    exit: long ปิดเมื่อ bear (fast<slow) · short ปิดเมื่อ bull. disaster SL (ตั้งตอนเข้า) คงเดิม.
    pyramid: CDC_PYRAMID=on → เติม 1 unit ทุก +½N ที่ราคาไปในทาง จนถึง CDC_MAX_UNITS (long-side)."""
    if not positions:
        return 0
    import MetaTrader5 as mt5
    import regime_lib as _R
    import config as _cfg
    high, low, close = bars[0], bars[1], bars[2]
    if close is None or len(close) < 40:
        return 0
    fast, slow = _R.cdc_zone(close)
    bull = fast[-2] > slow[-2]                            # closed บาร์ (i=n-2 ตรงกับ evaluate)
    tickets = combo_state.get("tickets") or {}
    # 1) exit-on-flip
    closed = 0
    for p in positions:
        is_buy = (p.type == mt5.ORDER_TYPE_BUY)
        if ((is_buy and not bull) or ((not is_buy) and bull)) and _close_position(broker, p, digits):
            tickets.pop(str(p.ticket), None)
            closed += 1
            logger.info(f"[MSE] cdc zone flip → close {algo_id}:{symbol} #{p.ticket} ({'BUY' if is_buy else 'SELL'})")
    if closed:
        combo_state.pop("cdc_last_add", None)             # จบ campaign → reset pyramid state
        return closed
    # 2) Turtle pyramid (default OFF) — เติม unit long เมื่อราคาไป +½N (Turtle "big order")
    if not getattr(_cfg, "CDC_PYRAMID", False) or not bull:
        return 0
    longs = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
    maxu = max(1, int(getattr(_cfg, "CDC_MAX_UNITS", 4)))
    if not longs or len(longs) >= maxu:
        return 0
    atr = _R.atr(high, low, close)
    av = float(atr[-2]) if atr[-2] == atr[-2] else 0.0
    if av <= 0:
        return 0
    tick = mt5.symbol_info_tick(broker)
    px = float(tick.ask) if tick else float(close[-1])
    last_add = float(combo_state.get("cdc_last_add") or max(p.price_open for p in longs))
    if (px - last_add) < float(getattr(_cfg, "CDC_ADD_HALF_N", 0.5)) * av:
        return 0                                          # ยังไปไม่ถึง +½N → ยังไม่เติม
    if _cdc_risk_too_high(broker, (2.0 * av) / point, point):
        return 0                                          # guard: risk/unit เกิน cap (ทุนน้อยเกิน 2N) → ไม่เติม
    from connectors.mt5_connector import open_order
    res = open_order("BUY", (2.0 * av) / point, 0.0, comment=f"MSE-{algo_id}", symbol=broker,
                     max_open_override=maxu, min_rr=0.1, magic=_magic_of(algo_id))   # open_order คุม margin/cap เอง
    if res and res.get("success") and res.get("ticket"):
        combo_state["cdc_last_add"] = px
        combo_state.setdefault("tickets", {})[str(res["ticket"])] = {
            "sl_dist": 2.0 * av, "dir": "BUY", "entry": float(res.get("price") or px), "opened_ts": _now_iso()}
        logger.info(f"[MSE] cdc pyramid +unit {algo_id}:{symbol} @ {res.get('price')} (unit {len(longs)+1}/{maxu})")
        return 1
    return 0


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
def _maybe_enter(algo_id, symbol, broker, bars, point, sl_mult, combo_state, max_pos=1, positions=None, magic=None, ctx=None):
    """ถ้ายังไม่ครบ max_pos + มี signal ใหม่ (bar_ts ยังไม่เคยเข้า) → open_order จริง. คืน 1 ถ้าเปิด."""
    import config as _cfg
    algo = _reg.get(algo_id)
    if algo is None:
        return 0
    vo = algo.evaluate(symbol, bars, ctx=ctx, point=point)
    if not vo or not vo.get("bar_ts"):
        return 0
    try:                                                       # per-algo direction mode (long/short/both; default both = ไม่กรอง)
        from agents import algo_dir as _adir
        if not _adir.allowed(algo_id, vo.get("dir")):
            return 0
    except Exception:
        pass
    try:                                                       # event-engine gate (ทองเท่านั้น): PRE=หยุดเข้าก่อนข่าว · POST=block สวนทิศ rubric
        if symbol.upper().startswith("XAU"):                   # bias() คืน None เมื่อ EVENT_ENGINE_LIVE=false → ไม่กระทบ (shadow)
            from agents import event_engine as _ee
            _eb = _ee.bias()
            if _eb:
                if _eb["dir"] == "FLAT":
                    logger.debug(f"[MSE] {algo_id}:{symbol} skip — PRE-event {_eb.get('key')} (หยุดเข้าก่อนข่าว)")
                    return 0
                if _eb["dir"] in ("BUY", "SELL") and vo.get("dir") != _eb["dir"]:
                    logger.debug(f"[MSE] {algo_id}:{symbol} {vo.get('dir')} skip — POST-event สวน bias {_eb['dir']} ({_eb.get('key')})")
                    return 0
    except Exception:
        pass
    try:                                                       # S/R entry gate: BUY ชนแนวต้านแข็งใกล้/SELL ชนแนวรับแข็ง → skip
        from agents import sr_entry_gate as _srg              # (SR_ENTRY_GATE off หรือ combo ไม่อยู่ allowlist → no-op)
        _atr_l = _simple_atr(*bars[:3]); _atr_g = _atr_l[-1] if _atr_l else 0.0
        _blk, _why = _srg.blocks_live(bars, vo.get("dir"), float(vo["entry"]), _atr_g, algo_id, symbol)
        if _blk:
            logger.debug(f"[MSE] {algo_id}:{symbol} {vo.get('dir')} skip — {_why}")
            return 0
    except Exception:
        pass
    if algo_id == "cdc_zone" and _cdc_risk_too_high(broker, float(vo.get("sl_pips") or 0), point):
        logger.debug(f"[MSE] {algo_id}:{symbol} skip — risk/ไม้ > CDC_MAX_UNIT_RISK_PCT% (ทุนน้อยเกิน 2N SL)")
        return 0
    if vo["bar_ts"] == combo_state.get("last_bar_ts"):
        return 0                                                # เข้าไม้บาร์นี้ **สำเร็จ**ไปแล้ว (dedup ต่อ signal-bar)
    if _signal_stale(vo["bar_ts"], algo):                       # cold-start: บาร์ปิดก่อน engine เริ่ม = stale
        combo_state["last_bar_ts"] = vo["bar_ts"]              # seed baseline → รอบาร์สดถัดไป (ไม่เข้าที่ราคาไกลจาก setup)
        logger.debug(f"[MSE] {algo_id}:{symbol} skip cold-start stale signal (bar {vo['bar_ts']})")
        return 0
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
    # RR gate ของ open_order = global 2.0 (คู่กับ decision_maker path ทอง). MSE เป็น validated-edge path
    # คนละเรื่อง: algo ใส่ RR ที่ backtest ผ่านลง tp_pips แล้ว (sweep BTC 1.5, macro BTC 2.5) → gate 2.0
    # จะ reject edge ที่ validate มา. ใช้ RR ต่อ combo (algo_pair_config → algo default → global) เป็น floor แทน,
    # หัก spread-tolerance กันโดน reject เพราะ gate คิด RR ใหม่จาก price จริง (มี spread) เทียบ SL/TP จาก signal.
    if _force_min:
        _min_rr = 0.1                                         # structural (ทอง): SL ปลายไส้ D1 กว้าง = risk control ไม่ใช่ RR
    else:
        from agents import algo_pair_config as _apc
        from config import MONEY_MANAGEMENT as _mm
        _base_rr = _apc.get(algo_id, symbol, "RR", None)
        if _base_rr is None:
            _base_rr = getattr(algo, "RR", None) or _mm["min_rr_ratio"]
        _min_rr = max(0.1, float(_base_rr) - _cfgf("MSE_RR_SPREAD_TOL", 0.05))
    res = open_order(vo["dir"], sl_pips_eff, tp_pips_eff, lot=_lot,
                     comment=f"MSE-{algo_id}", symbol=broker, max_open_override=max_pos,
                     min_rr=_min_rr, magic=magic if magic is not None else _magic_of(algo_id))
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
    global _ENGINE_START
    if _ENGINE_START is None:                            # cold-start: จำเวลาเริ่ม → ข้าม signal บาร์ที่ปิดก่อนหน้า
        import time as _t
        _ENGINE_START = _t.time()
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

    # reap: ปิดไม้ทุก combo ใน state (รวม combo ที่ toggle SHADOW/OFF ไปแล้ว → live loop ข้าม) →
    # record real_fill (feature-rich จาก ctx ตอน entry) + pop. MSE เป็นเจ้าของ record ไม้ non-gold
    # (trade_recorder ข้าม MSE-*). กัน ghost สะสม + edge-data leak. dedup กัน dup. fail-soft.
    try:
        import MetaTrader5 as _mt5r
        _all_open = _mt5r.positions_get() or []
        for _ck, _cs in list(state.items()):
            if not (_cs.get("tickets")):
                continue
            _ra, _, _rs = _ck.rpartition(":")
            if _reconcile_closed(_ra, _rs, _all_open, _cs):
                dirty = True
            if not _cs.get("tickets"):
                _cs.pop("tickets", None); dirty = True
    except Exception as _re:
        logger.debug(f"[MSE] reap fail: {_re}")

    for algo_id, symbol in live:
        try:
            broker = bmap.get(symbol, symbol)
            algo_obj = _reg.get(algo_id)
            tf = _combo_tf(algo_id, symbol) or getattr(algo_obj, "timeframe", "H1")   # per-combo short-term override (H4)
            _ctx = _combo_ctx(algo_id, symbol)                                        # lookbacks override (tsmom H4)
            mgmt = getattr(algo_obj, "mgmt", "managed")
            bars = _bars(broker, tf)
            if bars is None:
                continue
            point, digits = _meta(broker)
            if point is None:
                continue
            ck = f"{algo_id}:{symbol}"
            cstate = state.setdefault(ck, {})
            magic = _magic_of(algo_id)                       # magic ต่อ algo → ถือ/จัดการไม้แยกบน symbol เดียว
            positions = _our_positions(broker, magic)
            if positions is None:                            # fetch fail → ข้าม combo รอบนี้ (ห้าม manage ด้วยข้อมูลพัง)
                continue
            # ไม้ปิด → บันทึกโดย trade_recorder (universal, comment MSE-<algo>) แล้ว — MSE ไม่ record ซ้ำ
            # management ตาม algo: tsmom = exit-on-flip · อื่น = BE+trailing (SL/TP)
            if mgmt == "tsmom_flip":
                managed += _manage_tsmom(algo_id, symbol, broker, positions, bars, point, digits, cstate, _ctx)
            elif mgmt == "cdc_flip":
                managed += _manage_cdc(algo_id, symbol, broker, positions, bars, point, digits, cstate, _ctx)
            else:
                managed += _manage(broker, positions, bars, point, digits, cstate, algo_id)
            room_total = (max_total <= 0) or (total_open + opened < max_total)   # global cap ยังมีที่ว่าง
            active_pos = sum(1 for p in positions if not _position_protected(p, point))   # ไม้ protected (trailing เลย BE) ไม่กิน slot → เติมไม้สดได้
            if active_pos < max_pos and room_total:             # ผ่านทั้ง per-combo (ไม่นับ protected) + รวมทุก symbol
                op = _maybe_enter(algo_id, symbol, broker, bars, point,
                                  sl_mult.get(symbol, 1.0), cstate, max_pos, positions, magic, _ctx)   # LIVE = วางจริง (โบรก reject เองถ้าปิดคู่)
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
