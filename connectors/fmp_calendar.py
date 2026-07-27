"""connectors/fmp_calendar.py — economic calendar actuals จาก FMP (Financial Modeling Prep).

FF feed ให้แค่ forecast/previous · AV ตามหลัง ~1 เดือน. FMP economic_calendar ให้ **actual same-day
ทุกประเทศ** (US/EUR/GBP/JPY...). ใช้เติม field actual เข้า calendar ที่ประกาศแล้ว (match currency+date+title).

ต้อง FMP_API_KEY (free 250 call/วัน · financialmodelingprep.com). ไม่มี key → คืน [] (fallback AV/FF).
cache 30 นาที (actual อัปเดตเร็ว). 0 LLM token. อ่านโดย connectors/web_news.fetch_forexfactory_calendar.
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

_CACHE = os.path.join(_BASE, "data", "fmp_calendar.json")
_CACHE_TTL = 1800          # 30 นาที — actual อัปเดตเร็วหลังประกาศ (48 refresh/วัน × 1 call < 250 free)
_URL = "https://financialmodelingprep.com/api/v3/economic_calendar?from={f}&to={t}&apikey={k}"

# token ที่ไม่ช่วยแยก event (หน่วย/คำทั่วไป) — ตัดออกก่อนวัดความเหมือน title
_STOP = {"mm", "yy", "qq", "mom", "yoy", "qoq", "rate", "index", "prelim", "final",
         "advance", "flash", "annual", "annualized", "monthly", "change", "the", "of",
         "and", "s", "p", "n", "a", "vs", "gov", "govt"}

# synonym → canonical: FF กับ FMP ตั้งชื่อ event ต่างกัน (CPI↔Inflation · Non-Farm↔Payrolls) → map ให้ตรง
_SYN = {
    "cpi": "inflation", "nonfarm": "payrolls", "farm": "payrolls", "payroll": "payrolls",
    "nfp": "payrolls", "ppi": "producer", "boc": "boccash", "fomc": "fed", "ecb": "ecb",
    "claims": "jobless", "unemployment": "unemployment", "gdp": "gdp", "pmi": "pmi",
    "pce": "pce", "sales": "sales", "confidence": "confidence", "sentiment": "sentiment",
}


def _tokens(s):
    out = []
    for w in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split():
        if not w or w in _STOP:
            continue
        out.append(_SYN.get(w, w))
    return out


def _similar(a, b):
    """สัดส่วน token ที่ตรงกัน (เทียบกับฝั่งสั้น) — 1.0 = title เดียวกัน. ตัดหน่วย/stopword ก่อน."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _fetch(key):
    """ดึง FMP economic_calendar ช่วง [วันนี้-2, +8] → list ของ event dict. [] ถ้า fail/rate-limit."""
    now = datetime.now(timezone.utc)
    f = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    t = (now + timedelta(days=8)).strftime("%Y-%m-%d")
    try:
        url = _URL.format(f=f, t=t, k=key)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
        if isinstance(data, dict):                           # error payload → {"Error Message": ...}
            logger.warning(f"[fmp_calendar] FMP error: {data.get('Error Message') or data}")
            return []
        return data or []
    except Exception as e:
        logger.warning(f"[fmp_calendar] fetch fail: {e}")
        return []


def _load_cache():
    try:
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_events():
    """คืน list ของ FMP events (มี currency/date/event/actual). cache 30 นาที. [] ถ้าไม่มี key/ดึงไม่ได้."""
    try:
        import config
        key = getattr(config, "FMP_API_KEY", "") or ""
    except Exception:
        key = ""
    if not key:
        return []
    cache = _load_cache()
    if cache.get("events") is not None and time.time() - cache.get("ts", 0) < _CACHE_TTL:
        return cache["events"]
    events = _fetch(key)
    if not events:                                           # ดึงไม่ได้ → ใช้ cache เก่า (ถ้ามี)
        return cache.get("events") or []
    try:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "events": events}, f, ensure_ascii=False)
    except OSError:
        pass
    logger.info(f"[fmp_calendar] refresh: {len(events)} events")
    return events


def _fmp_dt(s):
    """parse FMP date 'YYYY-MM-DD HH:MM:SS' (สมมติ UTC) → datetime หรือ None."""
    try:
        s = str(s).strip().replace("T", " ")
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def actual_for(currency, title, event_dt, events=None):
    """หา actual จาก FMP: match currency + วันเดียวกัน + (เวลาใกล้ ≤45น. **หรือ** title คล้าย ≥0.5).
    เวลา = สัญญาณหลัก (event เดียวกันไม่ว่าชื่อต่าง) · title = ยืนยัน/สำรอง. คืน str หรือ None."""
    if events is None:
        events = get_events()
    if not events:
        return None
    day = event_dt.strftime("%Y-%m-%d")
    best, best_score = None, 0.0
    for e in events:
        if (e.get("currency") or "").upper() != (currency or "").upper():
            continue
        edt = _fmp_dt(e.get("date"))
        if not edt or edt.strftime("%Y-%m-%d") != day:       # ต้องวันเดียวกัน (กัน match ข้ามวัน)
            continue
        act = e.get("actual")
        if act is None or str(act).strip() == "":
            continue
        dmin = abs((edt - event_dt).total_seconds()) / 60.0
        sim = _similar(title, e.get("event", ""))
        near = dmin <= 45                                    # เวลาใกล้ = น่าจะ event เดียวกัน
        if not (near or sim >= 0.5):
            continue
        score = (2.0 if near else 0.0) + sim - dmin / 600.0  # ใกล้เวลา+ชื่อคล้าย = คะแนนสูง; ห่างเวลาลดคะแนน
        if score > best_score:
            best, best_score = str(act).strip(), score
    return best


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    evs = get_events()
    print(f"FMP events: {len(evs)}")
    filled = [e for e in evs if str(e.get("actual") or "").strip()]
    print(f"มี actual: {len(filled)}")
    for e in filled[:15]:
        print(f"  {e.get('currency'):4s} {str(e.get('event',''))[:36]:36s} act={e.get('actual')} fc={e.get('estimate')} date={str(e.get('date'))[:16]}")
