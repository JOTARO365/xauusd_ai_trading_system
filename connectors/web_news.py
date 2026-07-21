"""
Web news connector — ForexFactory calendar + Investing.com gold headlines
ใช้ stdlib เท่านั้น (urllib, xml, json) ไม่ต้องติดตั้งเพิ่ม
"""

import json
import re
import time as _time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from loguru import logger

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── ForexFactory ─────────────────────────────────────────────────────────────

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# currencies ที่ส่งผลต่อ Gold โดยตรง
_GOLD_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY", "CHF"}
_HIGH_IMPACTS    = {"High", "Medium"}

_FF_CACHE_TTL = 1800   # วินาที — refresh ทุก 30 นาที
_ff_cache: tuple[float, list] = (0.0, [])   # (timestamp, data)

_INV_CACHE_TTL = 900   # วินาที — refresh ทุก 15 นาที
_inv_cache: tuple[float, list] = (0.0, [])


def fetch_forexfactory_calendar(hours_ahead: int = 24,
                                include_all_us: bool = False) -> list[dict]:
    """
    ดึง economic calendar จาก ForexFactory unofficial JSON endpoint
    คืน high-impact events ที่จะเกิดใน `hours_ahead` ชั่วโมงข้างหน้า
    Cache ผล 30 นาที เพื่อหลีกเลี่ยง 429 rate limit

    include_all_us=True (dashboard only): สำหรับ USD คืน "ทั้งหมดของสัปดาห์นี้" —
    ทุกระดับ impact และรวมทั้งที่ประกาศไปแล้ว (ข้าม impact + future-only filter).
    สกุลอื่นยังกรอง High/Medium + อนาคตเหมือนเดิม. agent เรียกแบบ default = พฤติกรรมเดิม.
    """
    global _ff_cache
    now_ts = _time.time()

    cached_at, cached_events = _ff_cache
    if now_ts - cached_at < _FF_CACHE_TTL:
        age_min = int((now_ts - cached_at) / 60)
        logger.debug(f"ForexFactory: ใช้ cache (อายุ {age_min}min)")
        events = cached_events
    else:
        try:
            req = urllib.request.Request(FF_CALENDAR_URL, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as res:
                events = json.loads(res.read().decode("utf-8"))
            _ff_cache = (now_ts, events)
            logger.debug("ForexFactory: fetch สำเร็จ — อัปเดต cache")
        except Exception as e:
            logger.warning(f"ForexFactory calendar fetch failed: {e}")
            if cached_events:
                logger.info(f"ForexFactory: ใช้ cache เดิม ({len(cached_events)} events) เนื่องจาก fetch ล้มเหลว")
                events = cached_events
            else:
                return []

    now    = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)

    results: list[dict] = []
    for ev in events:
        country = ev.get("country", "").upper()
        # กรองเฉพาะ currency ที่เกี่ยวกับ gold
        if country not in _GOLD_CURRENCIES:
            continue
        us_all = include_all_us and country == "USD"

        # US โหมด all-week: เก็บทุก impact; ไม่งั้นเฉพาะ High/Medium
        if not us_all and ev.get("impact", "") not in _HIGH_IMPACTS:
            continue

        # parse date — format: "01-05-2026" หรือ ISO
        date_str = ev.get("date", "")
        try:
            # รองรับ format: "01-05-2026" และ "2026-01-05T..."
            if "T" in date_str:
                event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                event_dt = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=timezone.utc)
        except Exception:
            continue

        # US โหมด all-week: เก็บทั้งสัปดาห์ (past+future); ไม่งั้นเฉพาะอนาคตในกรอบเวลา
        if not us_all and not (now <= event_dt <= cutoff):
            continue

        results.append({
            "source":        "forexfactory",
            "title":         ev.get("title", ""),
            "currency":      ev.get("country", ""),
            "impact":        ev.get("impact", ""),
            "time":          event_dt.strftime("%H:%M UTC"),
            "timestamp_iso": event_dt.isoformat(),
            "forecast":      ev.get("forecast", "") or "—",
            "previous":      ev.get("previous", "") or "—",
            "actual":        ev.get("actual",   "") or "pending",
        })

    logger.info(f"ForexFactory: {len(results)} high-impact events ใน {hours_ahead}h")
    return results


# ── Investing.com ─────────────────────────────────────────────────────────────

# RSS ข่าว commodities (gold) จาก Investing.com
INVESTING_RSS_URLS = [
    "https://www.investing.com/rss/news_301.rss",   # Commodities news
    "https://www.investing.com/rss/market_overview_Technical.rss",
]


def _parse_rss(url: str, limit: int = 8) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()
        root = ET.fromstring(raw)
    except Exception as e:
        logger.warning(f"Investing.com RSS fetch failed ({url}): {e}")
        return []

    items = []
    for item in root.findall(".//item")[:limit]:
        title   = item.findtext("title")   or ""
        desc    = item.findtext("description") or ""
        pub     = item.findtext("pubDate") or ""
        link    = item.findtext("link")    or ""

        # strip HTML tags จาก description
        desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()
        desc_clean = re.sub(r"\s+", " ", desc_clean)[:200]

        # กรองเฉพาะข่าวที่เกี่ยวกับ gold — ต้องมีคำหลักใน title
        title_lower = title.lower()
        if not any(kw in title_lower for kw in ("gold", "xau", "bullion", "precious metal",
                                                  "fed", "federal reserve", "inflation",
                                                  "interest rate", "dollar", "dxy")):
            continue

        items.append({
            "source":  "investing.com",
            "title":   title.strip(),
            "summary": desc_clean,
            "pub":     pub[:25],
            "url":     link,
        })

    return items


def fetch_investing_news(limit: int = 10) -> list[dict]:
    """ดึงข่าว gold-related จาก Investing.com RSS — cache 15 นาที"""
    global _inv_cache
    now_ts = _time.time()

    cached_at, cached_items = _inv_cache
    if now_ts - cached_at < _INV_CACHE_TTL:
        age_min = int((now_ts - cached_at) / 60)
        logger.debug(f"Investing.com: ใช้ cache (อายุ {age_min}min)")
        return cached_items[:limit]

    results: list[dict] = []
    seen: set[str] = set()
    for url in INVESTING_RSS_URLS:
        for item in _parse_rss(url, limit):
            key = item["title"][:60]
            if key not in seen:
                seen.add(key)
                results.append(item)
        if len(results) >= limit:
            break

    if results:
        _inv_cache = (now_ts, results)
    elif cached_items:
        logger.info("Investing.com: ไม่สามารถ fetch ข้อมูลได้ — ใช้ cache เดิม")
        return cached_items[:limit]

    logger.info(f"Investing.com: {len(results)} articles")
    return results[:limit]
