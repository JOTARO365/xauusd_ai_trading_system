"""
probe_broker_tz.py — READ-ONLY diagnostic for B8 (broker-server time offset).

วัดว่า MT5 broker-server time ต่างจาก UTC กี่ชั่วโมง เพื่อยืนยันว่า history_deals_get
ที่ใช้ 2 convention (aware-UTC ใน pending_manager vs naive-local ที่อื่น) ทำให้ SL-reentry
window 30 นาที พลาด deal ที่เพิ่งปิดจริงไหม.

⚠️ READ-ONLY: เรียกแค่ symbol_info_tick + history_deals_get + account_info.
   ไม่มี order_send / order_close / positions modify ใดๆ. ไม่แตะบอทที่รันอยู่.
   (mt5.shutdown() ปิดแค่ handle ของสคริปต์นี้ ไม่กระทบ process อื่น)

รัน (ผู้ใช้เป็นคนสั่งเอง เพราะคุม live process):
  ! C:\\Users\\pornnatcha\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe scripts\\probe_broker_tz.py
"""
import sys, time
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import MetaTrader5 as mt5
sys.path.insert(0, ".")
try:
    from config import SYMBOL
except Exception:
    SYMBOL = "XAUUSD"


def main():
    if not mt5.initialize():
        print(f"[FAIL] mt5.initialize(): {mt5.last_error()} — เปิด MT5 terminal ก่อน")
        return

    now_utc = datetime.now(timezone.utc)
    local_epoch = time.time()

    # 1) offset จาก tick ล่าสุด (broker server epoch vs UTC epoch)
    #    ⚠️ ใช้ได้เฉพาะเมื่อ tick เป็นของ "ตอนนี้" (ตลาดเปิด + terminal ต่อ feed). ถ้า tick เก่า
    #    (ตลาดปิด/disconnect) offset ที่ได้ = อายุ tick ไม่ใช่ tz offset → ต้องเตือน ไม่งั้นเข้าใจผิด
    STALE_SEC = 300   # tick เก่ากว่า 5 นาที = ไม่มี feed สด
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"[WARN] ไม่มี tick ของ {SYMBOL} (ตลาดปิด/terminal ไม่ต่อ) — ลอง deal ต่อ")
    else:
        age_sec = local_epoch - tick.time
        print(f"[TICK]  {SYMBOL} tick.time={tick.time} ({datetime.fromtimestamp(tick.time, timezone.utc):%Y-%m-%d %H:%M:%S} 'UTC-labeled')")
        print(f"        time.time()={local_epoch:.0f} ({now_utc:%Y-%m-%d %H:%M:%S} UTC จริง)")
        if age_sec > STALE_SEC:
            print(f"        ❌ tick เก่า {age_sec/3600:.1f} ชม. = ไม่มี feed สด (ตลาดปิด/terminal disconnect).")
            print(f"           วัด broker-tz offset ไม่ได้ตอนนี้ — รันใหม่ตอน terminal ต่อ broker + ตลาดเปิด")
        else:
            offset_sec = tick.time - local_epoch
            print(f"        ✅ tick สด (อายุ {age_sec:.0f}s) → broker-server offset ≈ {offset_sec/3600:+.2f} ชม. (บวก = server นำ UTC)")

    # 2) deal ล่าสุดใน 7 วัน — เทียบ deal.time กับ UTC now
    frm = now_utc - timedelta(days=7)
    deals = mt5.history_deals_get(frm, now_utc + timedelta(hours=1))
    if not deals:
        print("[DEAL]  ไม่มี deal ใน 7 วัน (naive/aware ทั้งคู่ให้ผลเดียวกันตอนไม่มี data)")
    else:
        d = max(deals, key=lambda x: x.time)
        d_utc_label = datetime.fromtimestamp(d.time, timezone.utc)
        age_min = (local_epoch - d.time) / 60
        print(f"[DEAL]  ล่าสุด ticket_pos={d.position_id} time={d.time} "
              f"({d_utc_label:%Y-%m-%d %H:%M:%S} 'UTC-labeled')")
        print(f"        อายุถ้าตี deal.time เป็น UTC epoch: {age_min:+.0f} นาที ก่อน now")
        print(f"        >>> ถ้า age ติดลบมาก/เกิน window = deal 'อนาคต' → SL-reentry 30-min พลาดจริง")

    # 3) สรุปทิศทางแก้
    print("\n[สรุป] ถ้า offset ≈ 0 → 2 convention ต่างกันแค่ naive-local vs UTC (ต่างตาม TZ เครื่อง).")
    print("       ถ้า offset != 0 → broker server ไม่ใช่ UTC; _broker_now() ต้องบวก offset นี้")
    print("       ให้ทุก history_deals_get caller (pending_manager/reporter/mt5_connector).")

    mt5.shutdown()


if __name__ == "__main__":
    main()
