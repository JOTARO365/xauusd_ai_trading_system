"""
refresh_dashboard_data.py — รันทุก report/fetch script รวดเดียวให้ data/*.json สด
สำหรับ dashboard (burn, RIDE/NEWS_GATE cohort, calibration, macro, COT, scenarios,
realized-move, impact-calibration). Zero AI cost — ทุกตัวคำนวณในโค้ด/ดึงฟรี.

ออกแบบให้ตั้ง Windows Task Scheduler รันรายวัน (หรือทุก 6 ชม.). แต่ละ script รันแยก
subprocess + timeout + try/except → ตัวหนึ่งพังไม่ล้มตัวอื่น. MT5-dependent scripts
(ride/news_gate/realized_move) จะ no-op ถ้า MT5 terminal ไม่เปิด — ไม่ error.

Run: & $PY scripts\refresh_dashboard_data.py
"""
import os
import subprocess
import sys
from datetime import datetime

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# (script, timeout_sec) — เรียงจาก data-source เบา→หนัก; MT5 ตัวท้าย
_SCRIPTS = [
    ("report_burn.py",            60),
    ("report_calibration.py",     60),
    ("build_event_scenarios.py",  60),
    ("review_calibration.py",     60),
    ("fetch_macro_strip.py",     120),   # AlphaVantage REST (โควตาฟรี)
    ("fetch_cot.py",             120),   # CFTC public
    ("report_ride_cohort.py",     90),   # MT5
    ("report_news_gate.py",       90),   # MT5
    ("realized_move_logger.py",   90),   # MT5
]


def main() -> int:
    print(f"[refresh] start {datetime.now().isoformat()[:19]}")
    ok = 0
    for name, timeout in _SCRIPTS:
        path = os.path.join(_ROOT, "scripts", name)
        if not os.path.exists(path):
            print(f"  SKIP  {name} (not found)")
            continue
        try:
            r = subprocess.run(
                [sys.executable, path],
                cwd=_ROOT, timeout=timeout,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",   # scripts พิมพ์ UTF-8 — เลี่ยง cp874 decode พัง
            )
            tag = "OK  " if r.returncode == 0 else f"RC{r.returncode}"
            last = ((r.stdout or "").strip().splitlines() or [""])[-1][:90]
            print(f"  {tag}  {name:28} {last}")
            if r.returncode == 0:
                ok += 1
        except subprocess.TimeoutExpired:
            print(f"  TIME  {name:28} (>{timeout}s — skipped)")
        except Exception as e:   # noqa: BLE001
            print(f"  ERR   {name:28} {e}")
    print(f"[refresh] done — {ok}/{len(_SCRIPTS)} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
