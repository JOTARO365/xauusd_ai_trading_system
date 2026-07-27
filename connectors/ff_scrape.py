"""connectors/ff_scrape.py — actual เศรษฐกิจ same-day จาก ForexFactory.com (scrape HTML).

mirror `nfs.faireconomy.media` ตัด actual ออก · AV lag 1 เดือน · FMP/TE = premium/gone.
แต่ **ForexFactory.com เอง** ฝัง actual/forecast/previous + dateline ใน `window.calendarComponentStates`
→ scrape ได้ actual same-day ทุกสกุล ฟรี (ไม่ต้อง key). match กับ calendar (mirror) ด้วย currency+dateline
= เป๊ะ (source เดียวกัน). cache 30 นาที (48 hit/วัน). 0 LLM token.

⚠️ เปราะ: FF เปลี่ยน HTML/บล็อก = พัง → fallback AV/pending อัตโนมัติ (web_news จัดการ).
อ่านโดย connectors/web_news.fetch_forexfactory_calendar.
"""
import json
import os
import re
import sys
import time
import urllib.request

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

_CACHE = os.path.join(_BASE, "data", "ff_scrape.json")
_CACHE_TTL = 1800          # 30 นาที
_URL = "https://www.forexfactory.com/calendar"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
# flat event object ที่มี dateline (event ของ FF ไม่มี nested brace) → parse ทีละตัวได้
_EV_RE = re.compile(r'\{[^{}]*"dateline":\d+[^{}]*\}')


def _fetch():
    """scrape FF.com/calendar → list ของ event dict (dedup ตาม dateline+name+currency). [] ถ้า fail/block."""
    try:
        req = urllib.request.Request(_URL, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as res:
            body = res.read().decode("utf-8", "ignore")
    except Exception as e:
        logger.warning(f"[ff_scrape] fetch fail: {e}")
        return []
    out, seen = [], set()
    for raw in _EV_RE.findall(body):
        try:
            e = json.loads(raw)
        except Exception:
            continue
        dl = e.get("dateline")
        if not dl:
            continue
        key = (dl, e.get("name"), e.get("currency"))
        if key in seen:
            continue                                        # หน้ามี event ซ้ำ (2 ชุด) → เก็บชุดเดียว
        seen.add(key)
        out.append({"currency": e.get("currency", ""), "name": e.get("name", ""),
                    "dateline": int(dl), "actual": str(e.get("actual") or "").strip(),
                    "forecast": str(e.get("forecast") or "").strip(),
                    "previous": str(e.get("previous") or "").strip(),
                    "impact": e.get("impactName", "")})
    return out


def _load_cache():
    try:
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_events():
    """คืน list FF.com events (มี actual). cache 30 นาที. [] ถ้า scrape ไม่ได้."""
    cache = _load_cache()
    if cache.get("events") is not None and time.time() - cache.get("ts", 0) < _CACHE_TTL:
        return cache["events"]
    events = _fetch()
    if not events:                                          # scrape ไม่ได้ → ใช้ cache เก่า (ถ้ามี)
        return cache.get("events") or []
    try:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "events": events}, f, ensure_ascii=False)
    except OSError:
        pass
    n_act = sum(1 for e in events if e["actual"])
    logger.info(f"[ff_scrape] refresh: {len(events)} events ({n_act} มี actual)")
    return events


_STOP = {"mm", "yy", "qq", "mom", "yoy", "qoq", "rate", "index", "the", "of", "and", "s"}


def _toks(s):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split() if w and w not in _STOP}


def actual_for(currency, title, event_dt, events=None):
    """หา actual จาก FF.com: match currency + เวลาตรง (≤180 วิ) → ถ้าหลายตัว/เวลาเดียว ใช้ title ตัดสิน
    (source เดียวกัน = ชื่อตรง). คืน str หรือ None."""
    if events is None:
        events = get_events()
    if not events:
        return None
    ets = event_dt.timestamp()
    cur = (currency or "").upper()
    cands = [e for e in events if (e["currency"] or "").upper() == cur
             and abs(e["dateline"] - ets) <= 180 and e["actual"]]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]["actual"]
    tt = _toks(title)                                       # เวลาเดียวกันหลาย event → Jaccard (penalize คำเกิน
    def _jac(e):                                            #   "Durable Goods" ตรงกว่า "Core Durable Goods")
        et = _toks(e["name"])
        u = tt | et
        return len(tt & et) / len(u) if u else 0.0
    best = max(cands, key=_jac)
    return best["actual"]


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from datetime import datetime, timezone
    evs = get_events()
    rel = [e for e in evs if e["actual"]]
    print(f"FF.com events: {len(evs)} · มี actual: {len(rel)}")
    for e in rel[:20]:
        dt = datetime.fromtimestamp(e["dateline"], timezone.utc).strftime("%m-%d %H:%M")
        print(f"  {e['currency']:4s} {e['name'][:32]:32s} act={e['actual']:>8s} fc={e['forecast']:>7s} prev={e['previous']:>7s} {dt} {e['impact']}")
