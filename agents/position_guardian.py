"""
position_guardian.py — daemon thread เฝ้าไม้เปิดถี่ๆ ระหว่าง AI cycle ที่ช้า (5-15 นาที)

แนวคิดจาก 42 Philosophers (monitor/death-checker thread):
  - thread แยกที่ "เฝ้าสถานะถี่ๆ" อิสระจาก worker ที่ช้า
  - shared resource (MT5) มี mutex เดียว (_mt5_lock ใน mt5_connector) — ฟังก์ชัน manage_* self-lock แล้ว
  - poll ด้วย stop Event (คืนทันทีเมื่อ stop) — ไม่ sleep ก้อนเดียว → shutdown ไว
  - tick fail-soft — exception ตัวเดียวต้องไม่ฆ่า thread (เหมือน monitor ที่ต้องอยู่รอด)

*** GUARDIAN_ENABLED default = false *** — เปิดบน VM หลังทดสอบกับ MT5 จริงเท่านั้น (concurrency + เงินจริง)
"""
import threading
import config
from loguru import logger

_stop = threading.Event()
_thread: threading.Thread | None = None


def _tick() -> None:
    """หนึ่งรอบเฝ้า: ถ้ามีไม้เปิด → รัน protective management. ทุก mt5 call ถูก serialize ด้วย _mt5_lock."""
    from connectors.mt5_connector import (
        get_open_positions, manage_momentum_exit, manage_breakeven, manage_trailing_stop,
    )
    if not get_open_positions():
        return  # ไม่มีไม้ → ไม่แตะ MT5 ต่อ
    # momentum-exit ก่อน (ตัดไม้สวนเทรนด์ไว) → breakeven → trailing
    for fn in (manage_momentum_exit, manage_breakeven, manage_trailing_stop):
        try:
            fn()
        except Exception as e:
            logger.debug(f"[GUARDIAN] {fn.__name__}: {e}")   # fail-soft — thread ต้องไม่ตาย


def _loop() -> None:
    interval = max(1, config.GUARDIAN_INTERVAL_SEC)
    logger.info(f"[GUARDIAN] started — poll ทุก {interval}s")
    # _stop.wait คืน True ทันทีเมื่อถูก set (shutdown ไว) / คืน False เมื่อครบ interval → tick
    while not _stop.wait(interval):
        try:
            _tick()
        except Exception as e:
            logger.warning(f"[GUARDIAN] tick error: {e}")
    logger.info("[GUARDIAN] stopped")


def start_guardian() -> bool:
    """สตาร์ท guardian thread ถ้า GUARDIAN_ENABLED. คืน True ถ้าเริ่ม."""
    global _thread
    if not config.GUARDIAN_ENABLED:
        return False
    if _thread and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="position-guardian", daemon=True)
    _thread.start()
    return True


def stop_guardian(timeout: float = 5.0) -> None:
    """สั่งหยุด + join (graceful shutdown)."""
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout)


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())
