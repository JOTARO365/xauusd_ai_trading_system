"""gen_extra_event_dates.py — เติมวันประกาศย้อนหลังของ event Tier A+B ลง event_dates.json

Tier A (แม่นเป๊ะ — ออกพร้อม event ที่มีวันจริงอยู่แล้ว):
  CORE_CPI     = วันเดียวกับ CPI (รายงาน CPI ฉบับเดียวกัน)
  UNEMPLOYMENT = วันเดียวกับ NFP (Employment Situation ฉบับเดียวกัน; first-Friday rule)

Tier B (business-day rule + ปฏิทินวันหยุด US — คลาด ~1 วัน):
  ISM_MFG  = วันทำการที่ 1 ของเดือน
  ISM_SVC  = วันทำการที่ 3 ของเดือน
  ADP      = วันพุธก่อนศุกร์แรก (พุธสัปดาห์เดียวกับ NFP)

Idempotent — รันซ้ำได้ (อ่าน CPI เดิมก่อนเขียนทับ key ใหม่). ไม่แตะ CPI/FOMC.
Zero AI. รัน: & $PY scripts\gen_extra_event_dates.py
"""
import json
import os
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EVENT_DATES = os.path.join(_ROOT, "data", "event_dates.json")

_START_YEAR = 2011   # xau_daily เริ่ม 2011-06; เผื่อต้นปีให้ stats builder ตัดเอง
_END = date(2026, 7, 1)


# ── US federal holidays (สำหรับนับวันทำการ) ──────────────────────────────────────
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """วันที่ n ของ weekday นั้นในเดือน (weekday: Mon=0..Sun=6)."""
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 28) + timedelta(days=4)      # ต้นเดือนถัดไปโดยประมาณ
    d = d.replace(day=1) - timedelta(days=1)            # วันสุดท้ายของเดือน
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """วันหยุดตรงเสาร์→ศุกร์, อาทิตย์→จันทร์ (ธรรมเนียม US federal)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _us_holidays(year: int) -> set:
    hs = {
        _observed(date(year, 1, 1)),          # New Year
        _nth_weekday(year, 1, 0, 3),          # MLK (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),          # Presidents (3rd Mon Feb)
        _last_weekday(year, 5, 0),            # Memorial (last Mon May)
        _observed(date(year, 7, 4)),          # Independence
        _nth_weekday(year, 9, 0, 1),          # Labor (1st Mon Sep)
        _nth_weekday(year, 10, 0, 2),         # Columbus (2nd Mon Oct)
        _observed(date(year, 11, 11)),        # Veterans
        _nth_weekday(year, 11, 3, 4),         # Thanksgiving (4th Thu Nov)
        _observed(date(year, 12, 25)),        # Christmas
    }
    if year >= 2021:
        hs.add(_observed(date(year, 6, 19)))  # Juneteenth (federal ตั้งแต่ 2021)
    return hs


def _nth_business_day(year: int, month: int, n: int, holidays: set) -> date:
    d, count = date(year, month, 1), 0
    while True:
        if d.weekday() < 5 and d not in holidays:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


# ── date series generators ──────────────────────────────────────────────────────
def _months():
    for y in range(_START_YEAR, _END.year + 1):
        for m in range(1, 13):
            if date(y, m, 1) <= _END:
                yield y, m


def _ism(n: int) -> list:
    out = []
    for y, m in _months():
        hol = _us_holidays(y)
        d = _nth_business_day(y, m, n, hol)
        if d <= _END:
            out.append(d.isoformat())
    return out


def _adp() -> list:
    out = []
    for y, m in _months():
        wed = _first_friday(y, m) - timedelta(days=2)   # พุธก่อนศุกร์แรก
        if wed <= _END:
            out.append(wed.isoformat())
    return out


def _unemployment() -> list:
    """= NFP: ศุกร์แรกของเดือน; ตรง 4 ก.ค. เลื่อนเป็นพฤหัส (ตรงกับ event_reaction_stats)."""
    out = []
    for y, m in _months():
        d = _first_friday(y, m)
        if m == 7 and d.day == 4:
            d -= timedelta(days=1)
        if d <= _END:
            out.append(d.isoformat())
    return out


def _monthly_nbd(n: int) -> list:
    """วันทำการที่ n ของทุกเดือน (generic; ใช้กับ PPI/Retail Sales ~กลางเดือน)."""
    out = []
    for y, m in _months():
        d = _nth_business_day(y, m, n, _us_holidays(y))
        if d <= _END:
            out.append(d.isoformat())
    return out


def _weekly_thursday() -> list:
    """Jobless Claims — ทุกพฤหัส; พฤหัสที่เป็นวันหยุด → เลื่อนเป็นพุธ (ธรรมเนียม DOL)."""
    out = []
    d = date(_START_YEAR, 1, 1)
    d += timedelta(days=(3 - d.weekday()) % 7)          # พฤหัสแรก (Thu=3)
    while d <= _END:
        rel = d - timedelta(days=1) if d in _us_holidays(d.year) else d
        out.append(rel.isoformat())
        d += timedelta(weeks=1)
    return out


def _last_tuesday() -> list:
    """CB Consumer Confidence — อังคารสุดท้ายของเดือน."""
    return [_last_weekday(y, m, 1).isoformat() for y, m in _months() if _last_weekday(y, m, 1) <= _END]


def _gdp() -> list:
    """GDP advance — พฤหัสที่ 4 ของ ม.ค./เม.ย./ก.ค./ต.ค. (quarterly)."""
    out = []
    for y in range(_START_YEAR, _END.year + 1):
        for m in (1, 4, 7, 10):
            d = _nth_weekday(y, m, 3, 4)                 # 4th Thursday
            if date(_START_YEAR, 1, 1) <= d <= _END:
                out.append(d.isoformat())
    return out


def main() -> None:
    with open(_EVENT_DATES, "r", encoding="utf-8") as f:
        doc = json.load(f)
    events = doc.setdefault("events", {})

    cpi_dates = (events.get("CPI") or {}).get("dates") or []

    events["CORE_CPI"] = {
        "dates": list(cpi_dates),
        "source": "= CPI (Core CPI อยู่ในรายงาน CPI ฉบับเดียวกัน)",
        "notes": "co-released with CPI; วันเดียวกันเป๊ะ",
    }
    events["UNEMPLOYMENT"] = {
        "dates": _unemployment(),
        "source": "= NFP first-Friday (Employment Situation ฉบับเดียวกัน)",
        "notes": "co-released with NFP; rule-based first-Friday (4 ก.ค.→พฤหัส)",
    }
    events["ISM_MFG"] = {
        "dates": _ism(1),
        "source": "rule: วันทำการที่ 1 ของเดือน + US federal holidays",
        "notes": "Tier B — คลาด ~1 วันได้ (ISM อาจเลื่อน)",
    }
    events["ISM_SVC"] = {
        "dates": _ism(3),
        "source": "rule: วันทำการที่ 3 ของเดือน + US federal holidays",
        "notes": "Tier B — คลาด ~1 วันได้",
    }
    events["ADP"] = {
        "dates": _adp(),
        "source": "rule: วันพุธก่อนศุกร์แรก (สัปดาห์เดียวกับ NFP)",
        "notes": "Tier B — ADP monthly (ไม่ใช่ ADP weekly)",
    }
    # ── ขยาย event set (จาก analyst UHAS 08-12) — gold-impact + date rule แม่นพอ ──
    events["JOBLESS_CLAIMS"] = {
        "dates": _weekly_thursday(),
        "source": "rule: ทุกพฤหัส (วันหยุด→พุธ)",
        "notes": "Tier B — weekly, N สูง (labor สด รายสัปดาห์)",
    }
    events["CB_CONF"] = {
        "dates": _last_tuesday(),
        "source": "rule: อังคารสุดท้ายของเดือน",
        "notes": "Tier B — Conference Board Consumer Confidence",
    }
    events["GDP"] = {
        "dates": _gdp(),
        "source": "rule: พฤหัสที่ 4 ของ ม.ค./เม.ย./ก.ค./ต.ค. (advance)",
        "notes": "Tier B — quarterly advance estimate",
    }
    events["PPI"] = {
        "dates": _monthly_nbd(9),
        "source": "rule: วันทำการที่ 9 (~กลางเดือน ใกล้ CPI)",
        "notes": "Tier C — คลาด ~1-2 วัน (ไม่มี official schedule)",
    }
    events["RETAIL_SALES"] = {
        "dates": _monthly_nbd(11),
        "source": "rule: วันทำการที่ 11 (~กลางเดือน)",
        "notes": "Tier C — คลาด ~1-2 วัน",
    }

    with open(_EVENT_DATES, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    for k in ("CORE_CPI", "UNEMPLOYMENT", "ISM_MFG", "ISM_SVC", "ADP",
              "JOBLESS_CLAIMS", "CB_CONF", "GDP", "PPI", "RETAIL_SALES"):
        ds = events[k]["dates"]
        print(f"{k}: {len(ds)} dates ({ds[0]} .. {ds[-1]})")


if __name__ == "__main__":
    main()
