"""
swing_manager.py — SWING_HOLD long-term/position sleeve (rule-only, DEFAULT OFF).

ออกแบบตาม .claude/context/SWING_HOLD_spec.md (Q1-Q5 DECIDED).

หลักความปลอดภัย (INVARIANT ที่ต้องเป็นจริงเสมอ):
  ความเสียหายรวมของ campaign เมื่อชน structural SL ≤ SWING_TOTAL_RISK_PCT% ของ equity
  → ทุก leg ใช้ SL "ราคาเดียวกัน" (= structural invalidation level) เป็น broker-side
    circuit breaker (MT5 ปิดให้เองเมื่อชน — ไม่พึ่ง process ของเรา)
  → งบรวม = equity × RISK_PCT/100 แบ่งตาม SWING_LEG_SPLIT; แต่ละ leg size จากงบของตัวเอง
    → ผลรวม risk ≤ งบเสมอ (legs ที่ไม่ได้วาง = risk ยิ่งน้อย)

GATE 3 ด่าน (inert จนครบ):
  (1) _cfg.SWING_ENABLED = true
  (2) equity ≥ _cfg.SWING_MIN_EQUITY
  (3) DRY_RUN → log "would" ไม่ส่ง order จริง

แยกจาก scalp 100%:
  - ทุก order comment prefix "SWG-" + magic เดียวกัน, จัดการ order เอง (ไม่ผ่าน open_order/
    gates ของ scalp → ไม่โดน RR/slot/NNLB ของ scalp)
  - scalp guards (manage_momentum_exit / manage_breakeven) skip pos ที่ comment ขึ้นต้น SWG-
  - rule-only: ไม่เรียก Claude (Q5)

ENTRY (Q4 pullback-to-zone, trend-aligned ตามกฎ R2 "ทำตามที่เพจพูด ไม่ใช่ที่ทำ"):
  BUY  campaign: htf_zone=D1/W1 SUPPORT  + trend=BULLISH + ราคาย่อเข้า zone + conf≥SWING_MIN_CONF
  SELL campaign: htf_zone=D1/W1 RESISTANCE + trend=BEARISH + ราคาเด้งเข้า zone + conf≥SWING_MIN_CONF
  → ห้าม counter-trend (ต่างจาก grid ดิบของขงเบ้ง — อันนั้นไม่มี stop = ตัดทิ้ง)

SCALE-IN (Q3 ladder จาก sr_zones): เติม leg ที่ support ลึกถัดไป (BUY) จนถึง SWING_MAX_LEGS
EXIT: structural SL แตก (broker ปิดทุก leg) | ถึง opposite zone (TP) | เกิน SWING_MAX_HOLD_DAYS
"""
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5
from loguru import logger

import config as _cfg
from config import SYMBOL
from connectors.mt5_connector import SYSTEM_MAGIC, _calc_pip_value, _safe_comment, _locked

SWG_TAG = "SWG-"                 # comment prefix แยก swing ออกจาก scalp
_REENTRY_COOLDOWN_H = 4          # ห้ามเปิด campaign ใหม่ภายใน N ชม. หลังปิด (กัน churn)

# ── campaign state (in-memory; reconcile กับ MT5 ทุก call) ──────────────────────
# มีได้ทีละ 1 campaign (กันซ้อน/กัน margin ระเบิด). reset เมื่อ legs หมดจาก MT5
_campaign: dict | None = None    # {direction, structural_sl, tp, zone_level, ladder[], legs[], budget, since}
_last_close_ts: datetime | None = None


def _swing_positions() -> list:
    """open positions ที่เป็นของ swing (comment ขึ้นต้น SWG-)"""
    positions = mt5.positions_get(symbol=SYMBOL) or []
    return [p for p in positions
            if p.magic == SYSTEM_MAGIC and str(getattr(p, "comment", "") or "").startswith(SWG_TAG)]


def _is_swing_pos(pos) -> bool:
    return pos.magic == SYSTEM_MAGIC and str(getattr(pos, "comment", "") or "").startswith(SWG_TAG)


def _place_leg(direction: str, lot: float, sl_price: float, tp_price: float, leg_idx: int) -> int | None:
    """ส่ง market order 1 leg ที่ราคาตลาด ด้วย SL = structural level (ราคาเดียวทุก leg).
    คืน ticket หรือ None. DRY_RUN → log เฉยๆ"""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logger.error("[SWING] tick None — วาง leg ไม่ได้")
        return None
    is_buy = direction == "BUY"
    price  = tick.ask if is_buy else tick.bid

    if _cfg.DRY_RUN:
        logger.warning(
            f"[SWING][DRY_RUN] would open {direction} leg#{leg_idx} {lot}lot @ {price:.2f} "
            f"SL={sl_price:.2f} TP={tp_price:.2f}"
        )
        return None

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
        "price":        price,
        "sl":           round(sl_price, 2),
        "tp":           round(tp_price, 2),
        "deviation":    20,
        "magic":        SYSTEM_MAGIC,
        "comment":      _safe_comment(f"{SWG_TAG}{direction}L{leg_idx}"),
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = result.retcode if result else mt5.last_error()
        logger.error(f"[SWING] leg#{leg_idx} order failed: {err}")
        return None
    logger.warning(
        f"[SWING] OPEN {direction} leg#{leg_idx} {lot}lot @ {price:.2f} "
        f"SL={sl_price:.2f} TP={tp_price:.2f} ticket={result.order}"
    )
    return result.order


def _close_all_legs(reason: str) -> int:
    """ปิดทุก leg ของ campaign ที่ราคาตลาด (manual exit: max-hold/TP-manage)."""
    closed = 0
    for pos in _swing_positions():
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            break
        is_buy = pos.type == 0
        if _cfg.DRY_RUN:
            logger.warning(f"[SWING][DRY_RUN] would close ticket={pos.ticket} ({reason})")
            continue
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       SYMBOL,
            "volume":       pos.volume,
            "type":         mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position":     pos.ticket,
            "price":        tick.bid if is_buy else tick.ask,
            "deviation":    20,
            "magic":        SYSTEM_MAGIC,
            "comment":      _safe_comment(f"{SWG_TAG}EXIT"),
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
            logger.warning(f"[SWING] CLOSE ticket={pos.ticket} ({reason})")
        else:
            logger.error(f"[SWING] close failed ticket={pos.ticket}: {r.retcode if r else mt5.last_error()}")
    return closed


def _build_campaign(direction: str, zone_level: float, current: float, point: float,
                    chart_data: dict, equity: float, pipval: float) -> dict | None:
    """คำนวณ ladder + structural SL + งบ + tp. คืน campaign dict (ยังไม่วาง leg) หรือ None ถ้าไม่ผ่าน guard."""
    sr = chart_data.get("sr_zones", {}) or {}
    is_buy = direction == "BUY"

    # ── ladder: support ลึกถัดไป (BUY) / resistance สูงถัดไป (SELL) ──
    if is_buy:
        deeper = sorted([s for s in sr.get("support", []) if s < zone_level], reverse=True)
        opp    = sorted([r for r in sr.get("resistance", []) if r > current])   # TP candidates
    else:
        deeper = sorted([r for r in sr.get("resistance", []) if r > zone_level])
        opp    = sorted([s for s in sr.get("support", []) if s < current], reverse=True)

    entries = [zone_level] + deeper[: max(0, _cfg.SWING_MAX_LEGS - 1)]   # leg1 ที่ zone + ลึกถัดไป

    # ── structural SL = เลย ladder ลึกสุด + buffer (~0.4% ของราคา) ──
    buffer = current * 0.004
    deepest = min(entries) if is_buy else max(entries)
    structural_sl = (deepest - buffer) if is_buy else (deepest + buffer)

    # ── TP = opposite zone ใกล้สุด; ไม่มี → ไม่เปิด (ต้องมีเป้า) ──
    if not opp:
        logger.info(f"[SWING] no opposite zone for TP ({direction}) — skip")
        return None
    tp = opp[0]

    # ── งบรวม = equity × RISK_PCT% ──
    budget = equity * (_cfg.SWING_TOTAL_RISK_PCT / 100.0)

    return {
        "direction":     direction,
        "structural_sl": round(structural_sl, 2),
        "tp":            round(tp, 2),
        "zone_level":    zone_level,
        "ladder":        [round(e, 2) for e in entries],   # ราคาที่ตั้งใจจะวางแต่ละ leg
        "placed":        set(),                            # index ของ leg ที่วางแล้ว
        "legs":          [],                               # [{ticket, entry, lot, idx}]
        "budget":        budget,
        "pipval":        pipval,
        "point":         point,
        "since":         datetime.now(timezone.utc).isoformat(),
    }


def _leg_lot(camp: dict, entry_price: float, leg_idx: int) -> float:
    """size leg จากงบของ leg นั้น (split) ให้ risk-to-structural-SL = งบ_leg. clamp MIN/MAX_LOT."""
    point   = camp["point"]
    pipval  = camp["pipval"]
    sl_pips = abs(entry_price - camp["structural_sl"]) / point
    if sl_pips <= 0 or pipval <= 0:
        return 0.0
    split = _cfg.SWING_LEG_SPLIT[leg_idx] if leg_idx < len(_cfg.SWING_LEG_SPLIT) else _cfg.SWING_LEG_SPLIT[-1]
    leg_budget = camp["budget"] * (split / 100.0)
    lot = round(leg_budget / (sl_pips * pipval), 2)
    return max(0.0, lot)


def _current_risk(camp: dict) -> float:
    """ผลรวม max-loss ของ legs ที่วางแล้ว เมื่อชน structural SL (account ccy)."""
    point  = camp["point"]
    pipval = camp["pipval"]
    total  = 0.0
    for leg in camp["legs"]:
        sl_pips = abs(leg["entry"] - camp["structural_sl"]) / point
        total  += leg["lot"] * sl_pips * pipval
    return total


@_locked   # B10: serialize MT5 access กับ guardian thread (RLock reentrant — nested _calc_pip_value ปลอดภัย)
def manage_swing_campaign(chart_data: dict) -> int:
    """
    Entry point — เรียกจาก trading_graph.node_position_mgmt ทุก cycle.
    คืนจำนวน action (เปิด/เติม/ปิด). inert (คืน 0) ถ้าไม่ผ่าน gate.
    """
    global _campaign, _last_close_ts

    # ── GATE 1: master switch ──
    if not getattr(_cfg, "SWING_ENABLED", False):
        return 0

    info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    acct = mt5.account_info()
    if info is None or tick is None or acct is None:
        return 0
    point   = info.point
    equity  = float(acct.equity)
    current = float(tick.bid)

    # ── GATE 2: equity floor (swing SL กว้าง ต้องทุนพอ — กัน lot ต่ำกว่า MIN_LOT) ──
    if equity < getattr(_cfg, "SWING_MIN_EQUITY", 3600):
        return 0

    pipval = _calc_pip_value(SYMBOL)    # account-ccy ต่อ 1 point ต่อ 1 lot (เลี่ยง SUSP-1)
    actions = 0

    # ── RECONCILE: sync campaign กับ MT5 (legs ที่ปิดด้วย SL/TP จะหายไป) ──
    live = _swing_positions()
    live_tickets = {p.ticket for p in live}
    if _campaign is not None:
        _campaign["legs"] = [l for l in _campaign["legs"] if l["ticket"] in live_tickets]
        if not _campaign["legs"]:
            # campaign จบแล้ว (structural SL แตก หรือ TP โดน — broker ปิดให้)
            logger.warning("[SWING] campaign ended (all legs closed by broker SL/TP) — reset")
            _campaign = None
            _last_close_ts = datetime.now(timezone.utc)
            return 0

    # ── PHASE A: จัดการ campaign ที่มีอยู่ ──
    if _campaign is not None:
        camp = _campaign
        is_buy = camp["direction"] == "BUY"

        # A1. max hold → ปิดทุก leg
        try:
            since = datetime.fromisoformat(camp["since"])
            if _cfg.SWING_MAX_HOLD_DAYS > 0 and \
               datetime.now(timezone.utc) - since > timedelta(days=_cfg.SWING_MAX_HOLD_DAYS):
                n = _close_all_legs("max-hold")
                _campaign = None
                _last_close_ts = datetime.now(timezone.utc)
                return n
        except Exception:
            pass

        # A2. scale-in — ราคาแตะ ladder ระดับถัดไปที่ยังไม่วาง + legs < MAX_LEGS + งบเหลือ
        for idx, entry_lv in enumerate(camp["ladder"]):
            if idx in camp["placed"]:
                continue
            if len(camp["legs"]) >= _cfg.SWING_MAX_LEGS:
                break
            reached = (current <= entry_lv) if is_buy else (current >= entry_lv)
            if not reached:
                continue
            lot = _leg_lot(camp, current, idx)
            if lot < info.volume_min:
                camp["placed"].add(idx)   # ทุนไม่พอ leg นี้ — ข้าม (ไม่ retry ถี่)
                continue
            # guard งบ: risk รวมหลังเติมต้องไม่ทะลุ budget (กันลอตปัดเศษทำเกิน)
            new_risk = _current_risk(camp) + lot * (abs(current - camp["structural_sl"]) / point) * pipval
            if new_risk > camp["budget"] * 1.05:
                logger.warning(f"[SWING] scale-in leg#{idx} จะทำ risk เกินงบ — ข้าม")
                camp["placed"].add(idx)
                continue
            ticket = _place_leg(camp["direction"], lot, camp["structural_sl"], camp["tp"], idx)
            camp["placed"].add(idx)
            if ticket:
                camp["legs"].append({"ticket": ticket, "entry": current, "lot": lot, "idx": idx})
                actions += 1
        return actions

    # ── PHASE B: ไม่มี campaign → ตรวจ entry trigger (เปิด leg แรก) ──
    # cooldown หลังปิด
    if _last_close_ts and datetime.now(timezone.utc) - _last_close_ts < timedelta(hours=_REENTRY_COOLDOWN_H):
        return 0
    # มี SWG- ค้างใน MT5 แต่ state หาย (restart) → ไม่เปิดซ้ำ ปล่อยให้ broker จัดการ legs เดิม
    if live:
        return 0

    htf = chart_data.get("htf_zone")
    if not htf:
        return 0
    if str(htf.get("tf", "")).upper() not in _cfg.SWING_TF:
        return 0
    trend = str(chart_data.get("trend", "")).upper()
    conf  = float(chart_data.get("confidence", 0) or 0)
    if conf < _cfg.SWING_MIN_CONF:
        return 0

    ztype = htf.get("zone_type")
    # trend-aligned เท่านั้น (R2): BUY ที่ SUPPORT ใน BULLISH / SELL ที่ RESISTANCE ใน BEARISH
    if ztype == "SUPPORT" and trend == "BULLISH":
        direction = "BUY"
    elif ztype == "RESISTANCE" and trend == "BEARISH":
        direction = "SELL"
    else:
        return 0

    zone_level = float(htf.get("level") or 0)
    if not zone_level:
        return 0

    camp = _build_campaign(direction, zone_level, current, point, chart_data, equity, pipval)
    if camp is None:
        return 0

    # วาง leg แรก (idx 0 = ที่ zone, เข้าตอนราคาย่อมาถึงแล้ว → market)
    lot = _leg_lot(camp, current, 0)
    if lot < info.volume_min:
        logger.info(f"[SWING] leg1 lot {lot} < min — equity ไม่พอกับ structural SL กว้าง, skip")
        return 0
    ticket = _place_leg(direction, lot, camp["structural_sl"], camp["tp"], 0)
    camp["placed"].add(0)
    if ticket:
        camp["legs"].append({"ticket": ticket, "entry": current, "lot": lot, "idx": 0})
        _campaign = camp
        logger.warning(
            f"[SWING] NEW campaign {direction} | zone={zone_level:.2f} structSL={camp['structural_sl']:.2f} "
            f"TP={camp['tp']:.2f} budget={camp['budget']:.0f} ({_cfg.SWING_TOTAL_RISK_PCT}% of {equity:.0f}) "
            f"legs_max={_cfg.SWING_MAX_LEGS}"
        )
        actions += 1

    return actions
