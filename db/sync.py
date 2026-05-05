"""MT5 → Supabase history sync
รันตอน startup ครั้งเดียว — ดึง closed trades จาก MT5 แล้ว upsert เข้า DB
ข้าม tickets ที่มีอยู่แล้วใน DB เพื่อไม่ overwrite AI context ที่บันทึกไว้
"""
from datetime import datetime, timedelta
from loguru import logger

import MetaTrader5 as mt5


def sync_mt5_history_to_db(days: int = 365) -> int:
    """ดึง closed trade history จาก MT5 แล้ว upsert เข้า Supabase
    คืนจำนวน trades ที่ sync ใหม่ (0 ถ้า DB ไม่พร้อมหรือไม่มีของใหม่)
    """
    from db.connection import is_available
    from db.writer import write_trade

    if not is_available():
        logger.debug("sync_mt5_history: DB ไม่พร้อม — ข้าม")
        return 0

    # ── ดึง account login ของเครื่องนี้ (ใช้ทั้ง filter + upsert) ──
    account_info  = mt5.account_info()
    account_login = int(account_info.login) if account_info else 0
    logger.debug(f"sync_mt5_history: account_login={account_login}")

    # ── ดึง existing tickets ของ account นี้จาก DB ────────────────
    existing: set[int] = _get_existing_tickets(account_login)

    # ── ดึง deals จาก MT5 ────────────────────────────────────────
    date_from = datetime.now() - timedelta(days=days)
    date_to   = datetime.now()

    deals = mt5.history_deals_get(date_from, date_to)
    if not deals:
        logger.debug("sync_mt5_history: ไม่มี deals จาก MT5")
        return 0

    # ── ดึง orders (เพื่อหา SL/TP) ───────────────────────────────
    raw_orders = mt5.history_orders_get(date_from, date_to) or []
    order_map: dict[int, object] = {o.ticket: o for o in raw_orders}

    # ── จัดกลุ่ม deals ตาม position_id ───────────────────────────
    from collections import defaultdict
    pos_deals: dict[int, list] = defaultdict(list)
    for d in deals:
        from config import SYMBOL
        if d.symbol != SYMBOL:
            continue
        pos_deals[d.position_id].append(d)

    synced = 0
    for pos_id, dlist in pos_deals.items():
        entry_deal = next((d for d in dlist if d.entry == 0), None)
        exit_deals = [d for d in dlist if d.entry in (1, 2)]

        if entry_deal is None:
            continue

        ticket = entry_deal.order   # order ticket = trade key

        # ข้าม ticket ที่มีอยู่ใน DB สำหรับ account นี้แล้ว (ป้องกัน overwrite AI context)
        if ticket in existing:
            continue

        o  = order_map.get(ticket)
        sl = o.sl if o and o.sl != 0.0 else None
        tp = o.tp if o and o.tp != 0.0 else None

        opened_at  = datetime.utcfromtimestamp(entry_deal.time).isoformat() + "Z"
        is_closed  = len(exit_deals) > 0
        closed_at  = None
        pnl        = None

        if is_closed:
            last_exit = max(exit_deals, key=lambda d: d.time)
            closed_at = datetime.utcfromtimestamp(last_exit.time).isoformat() + "Z"
            pnl = round(sum(d.profit + d.swap + d.commission for d in dlist), 2)

        from config import SYMBOL, SYSTEM_MAGIC
        trade = {
            "ticket":        ticket,
            "account_login": account_login,
            "symbol":        SYMBOL,
            "source":        "SYSTEM" if entry_deal.magic == SYSTEM_MAGIC else "MANUAL",
            "direction":     "BUY" if entry_deal.type == 0 else "SELL",
            "status":        "CLOSED" if is_closed else "OPEN",
            "lot":           entry_deal.volume,
            "entry_price":   entry_deal.price,
            "sl":            sl,
            "tp":            tp,
            "pnl":           pnl,
            "timestamp":     opened_at,
            "close_time":    closed_at,
        }

        if write_trade(trade):
            synced += 1

    if synced:
        logger.info(f"sync_mt5_history: synced {synced} new trade(s) from MT5 → DB")
    else:
        logger.debug("sync_mt5_history: ไม่มี trades ใหม่")

    return synced


def _get_existing_tickets(account_login: int) -> set[int]:
    """ดึง tickets ที่มีใน DB สำหรับ account นี้แล้ว"""
    try:
        from db.connection import get_client
        from config import SYMBOL
        res = (
            get_client().table("trades")
            .select("ticket")
            .eq("symbol", SYMBOL)
            .eq("account_login", account_login)
            .execute()
        )
        return {int(r["ticket"]) for r in res.data if r.get("ticket")}
    except Exception as e:
        logger.debug(f"_get_existing_tickets error: {e}")
        return set()
