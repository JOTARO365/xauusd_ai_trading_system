"""
delete_bad_pending.py — รัน 1 ครั้งเมื่อตลาดเปิด จันทร์ 19 พ.ค. 2026
ลบ 6 pending orders ที่มี SL=2000 pips (ผิด) จาก config เก่า

รัน: python scripts/delete_bad_pending.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from dotenv import load_dotenv
load_dotenv()

# tickets ที่ต้องลบ (SL=2000 pips จาก config เก่า — เสี่ยง $200/trade > พอร์ต 3000 บาท)
BAD_TICKETS = [
    217886500,  # SELL_LIMIT
    217886505,  # BUY_LIMIT @ 4500.65 — ใกล้ราคาปัจจุบันมาก (urgent)
    218493565,
    218493569,
    218493577,
    218498463,
]

def main():
    login    = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")

    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return

    if not mt5.login(login, password=password, server=server):
        print(f"MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return

    info = mt5.account_info()
    print(f"Connected: {info.login} | Balance: {info.balance:.2f} {info.currency}")
    print()

    # ตรวจสอบ pending orders ที่ยังอยู่
    orders = mt5.orders_get()
    if orders is None:
        orders = []

    existing_tickets = {o.ticket for o in orders}
    print(f"Pending orders ทั้งหมดตอนนี้: {len(orders)} รายการ")

    success = 0
    skip    = 0
    fail    = 0

    for ticket in BAD_TICKETS:
        if ticket not in existing_tickets:
            print(f"  [SKIP] {ticket} — ไม่พบใน pending (อาจถูกลบแล้วหรือ filled)")
            skip += 1
            continue

        # หา order info
        o = next((x for x in orders if x.ticket == ticket), None)
        type_name = {
            mt5.ORDER_TYPE_BUY_LIMIT:  "BUY_LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
            mt5.ORDER_TYPE_BUY_STOP:   "BUY_STOP",
            mt5.ORDER_TYPE_SELL_STOP:  "SELL_STOP",
        }.get(o.type, "UNKNOWN") if o else "?"

        result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})

        if result is None:
            print(f"  [FAIL] {ticket} ({type_name} @ {o.price_open if o else '?'}) — order_send returned None: {mt5.last_error()}")
            fail += 1
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"  [FAIL] {ticket} ({type_name} @ {o.price_open if o else '?'}) — retcode={result.retcode} {result.comment}")
            fail += 1
        else:
            print(f"  [OK]   {ticket} ({type_name} @ {o.price_open if o else '?'}) — ลบสำเร็จ")
            success += 1

    print()
    print(f"Results: {success} ลบสำเร็จ | {skip} ข้าม | {fail} ล้มเหลว")

    if fail > 0:
        print("\nTickets ที่ล้มเหลว ให้ลบด้วยมือใน MT5 (Right-click → Delete)")

    mt5.shutdown()

if __name__ == "__main__":
    main()
