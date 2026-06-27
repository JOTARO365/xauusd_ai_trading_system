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

    meta_map = _trade_meta_from_logs()   # Fix 1: กู้ decision context จาก trades.json
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

        opened_at  = datetime.utcfromtimestamp(entry_deal.time).isoformat()
        is_closed  = len(exit_deals) > 0
        closed_at  = None
        pnl        = None

        if is_closed:
            last_exit = max(exit_deals, key=lambda d: d.time)
            closed_at = datetime.utcfromtimestamp(last_exit.time).isoformat()
            pnl = round(sum(d.profit + d.swap + d.commission for d in dlist), 2)

        from config import SYMBOL
        from connectors.mt5_connector import SYSTEM_MAGIC
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

        # Fix 1: เติม decision metadata จาก trades.json (กู้ถ้า open-time DB write fail)
        _extra = meta_map.get(int(ticket))
        if _extra:
            for _k, _v in _extra.items():
                trade.setdefault(_k, _v)

        if write_trade(trade):
            synced += 1

    if synced:
        logger.info(f"sync_mt5_history: synced {synced} new trade(s) from MT5 → DB")
    else:
        logger.debug("sync_mt5_history: ไม่มี trades ใหม่")

    return synced


def reconcile_open_trades(account_login: int | None = None, days: int = 365,
                          dry_run: bool = False) -> dict:
    """ปิด orphan: row ที่ DB ยัง status='OPEN' แต่ broker ปิดไปแล้ว.

    Scope **เฉพาะบัญชีที่ MT5 ต่ออยู่ + SYMBOL เสมอ** → เป็นไปไม่ได้ที่จะแตะไม้
    ของบัญชีอื่น (ไม้บัญชีอื่นไม่มี ground truth จากเครื่องนี้ ต้องใช้ manual cleanup).

    เทียบ DB-open กับความจริงจาก MT5:
      - ticket ยังอยู่ใน positions_get()          → OPEN ตามเดิม
      - ปิดแล้ว + เจอใน MT5 history (pnl ได้)      → CLOSED + pnl + closed_at  (close_reason=RECONCILED)
      - ปิดแล้ว + เกิน history window (pnl ไม่ได้)  → CLOSED + pnl=None          (close_reason=RECONCILED_STALE)

    UPDATE เฉพาะ 4 ฟิลด์ (status/pnl/closed_at/close_reason) — ไม่ทับ AI context อื่น.
    dry_run=True → ไม่เขียน DB, แค่คืน actions ที่ "จะ" ทำ.
    """
    from collections import defaultdict
    from db.connection import is_available, get_client
    from config import SYMBOL

    result = {"login": None, "db_open": 0, "still_open": 0,
              "reconciled": 0, "stale": 0, "failed": 0, "dry_run": dry_run, "actions": []}

    if not is_available():
        logger.debug("reconcile_open_trades: DB ไม่พร้อม — ข้าม")
        return result

    info = mt5.account_info()
    if info is None:
        logger.warning("reconcile_open_trades: ไม่ได้เชื่อมต่อ MT5 — ข้าม (กันแตะผิดบัญชี)")
        return result
    login = int(account_login) if account_login else int(info.login)
    result["login"] = login

    # ── ground truth จาก MT5 (บัญชีที่ต่ออยู่) ────────────────────
    live = {int(p.ticket) for p in (mt5.positions_get(symbol=SYMBOL) or [])}

    deals = mt5.history_deals_get(datetime.now() - timedelta(days=days), datetime.now()) or []
    grp: dict[int, list] = defaultdict(list)
    for d in deals:
        if d.symbol == SYMBOL:
            grp[d.position_id].append(d)
    hist: dict[int, tuple] = {}
    for pid, dl in grp.items():
        if any(d.entry == 1 for d in dl):   # มี closing deal = ปิดจริง
            last_exit = max((d for d in dl if d.entry in (1, 2)), key=lambda d: d.time)
            pnl = round(sum(d.profit + d.swap + d.commission for d in dl), 2)
            hist[int(pid)] = (pnl, datetime.utcfromtimestamp(last_exit.time).isoformat())

    # ── DB rows ที่ยัง OPEN ของบัญชี + symbol นี้ ──────────────────
    try:
        rows = (get_client().table("trades")
                .select("ticket")
                .eq("status", "OPEN").eq("account_login", login).eq("symbol", SYMBOL)
                .execute().data) or []
    except Exception as e:
        logger.debug(f"reconcile_open_trades: query error: {e}")
        return result
    result["db_open"] = len(rows)

    for r in rows:
        if not r.get("ticket"):
            continue
        tk = int(r["ticket"])
        if tk in live:
            result["still_open"] += 1
            continue
        if tk in hist:
            pnl, closed_at = hist[tk]
            patch = {"status": "CLOSED", "pnl": pnl, "closed_at": closed_at}
            kind, reason = "reconciled", "RECONCILED"   # closed normally, late-synced
        else:
            patch = {"status": "CLOSED", "pnl": None}    # pnl=None = STALE marker (no history)
            kind, reason = "stale", "RECONCILED_STALE"

        if not dry_run:
            try:
                (get_client().table("trades").update(patch)
                 .eq("ticket", tk).eq("account_login", login).execute())
            except Exception as e:
                result["failed"] += 1
                logger.debug(f"reconcile_open_trades: update ticket {tk} failed: {e}")
                continue   # นับ/แสดงเฉพาะที่เขียนสำเร็จ
        result[kind] += 1
        result["actions"].append({"ticket": tk, "reason": reason, "pnl": patch.get("pnl")})

    tag = "DRY-RUN" if dry_run else "applied"
    logger.info(f"reconcile_open_trades[{login}] ({tag}): db_open={result['db_open']} "
                f"still_open={result['still_open']} reconciled={result['reconciled']} "
                f"stale={result['stale']} failed={result['failed']}")
    return result


_META_FIELDS = (
    "technical_signal", "technical_confidence", "trend", "entry_type",
    "sr_zone", "sr_strength", "pa_action", "sentiment", "analysis",
    "planned_sl_pips", "entry_score", "atr_h4", "momentum", "htf_zone_tf",
    "strategy_version",
)


def _trade_meta_from_logs() -> dict:
    """อ่าน decision metadata จาก logs/<symbol>_trades.json → {ticket: {field: value}}.

    log_trade() เขียน JSON ก่อน DB เสมอ → ไฟล์นี้มี trend/conf/entry_type แม้ DB write
    ตอนเปิดไม้จะ fail เงียบ. ใช้กู้คืน metadata ตอน sync/backfill.
    """
    import json
    from config import SYMBOL
    sym  = SYMBOL.upper().replace("/", "")
    path = "logs/trades.json" if sym == "XAUUSD" else f"logs/{sym.lower()}_trades.json"
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return out
    for t in data.get("trades", []):
        tk = t.get("ticket")
        if tk is None:
            continue
        meta = {k: t.get(k) for k in _META_FIELDS if t.get(k) is not None}
        if meta:
            out[int(tk)] = meta
    return out


def backfill_metadata_from_logs(account_login: int | None = None,
                                dry_run: bool = False) -> dict:
    """เติม decision metadata ให้ row ใน DB ที่ trend=None (มาจาก MT5-sync ไม่มี context).

    ดึงจาก trades.json → UPDATE เฉพาะ field ที่ขาด, scope account ปัจจุบัน + SYMBOL.
    ไม่ทับค่าที่มีอยู่ (อัปเดตเฉพาะ row ที่ trend ว่าง). dry_run=True → ไม่เขียน.
    """
    from db.connection import is_available, get_client
    from config import SYMBOL

    result = {"login": None, "db_missing": 0, "backfilled": 0, "no_log": 0,
              "failed": 0, "dry_run": dry_run}
    if not is_available():
        logger.debug("backfill_metadata: DB ไม่พร้อม — ข้าม")
        return result

    info = mt5.account_info()
    if info is None:
        logger.warning("backfill_metadata: ไม่ได้เชื่อมต่อ MT5 — ข้าม")
        return result
    login = int(account_login) if account_login else int(info.login)
    result["login"] = login

    meta_map = _trade_meta_from_logs()
    if not meta_map:
        logger.debug("backfill_metadata: trades.json ไม่มี metadata — ข้าม")
        return result

    try:
        rows = (get_client().table("trades")
                .select("ticket")
                .is_("trend", "null").eq("account_login", login).eq("symbol", SYMBOL)
                .execute().data) or []
    except Exception as e:
        logger.debug(f"backfill_metadata: query error: {e}")
        return result
    result["db_missing"] = len(rows)

    for r in rows:
        tk = r.get("ticket")
        if tk is None:
            continue
        meta = meta_map.get(int(tk))
        if not meta:
            result["no_log"] += 1
            continue
        if not dry_run:
            try:
                (get_client().table("trades").update(meta)
                 .eq("ticket", int(tk)).eq("account_login", login).execute())
            except Exception as e:
                result["failed"] += 1
                logger.warning(f"backfill_metadata: update ticket {tk} failed: {e}")
                continue
        result["backfilled"] += 1

    tag = "DRY-RUN" if dry_run else "applied"
    logger.info(f"backfill_metadata[{login}] ({tag}): db_missing={result['db_missing']} "
                f"backfilled={result['backfilled']} no_log={result['no_log']} failed={result['failed']}")
    return result


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
