import asyncio
import re
import time as _time
import urllib.request
import xml.etree.ElementTree as ET
from config import X_ACCOUNTS_TO_FOLLOW, X_KEYWORDS
from loguru import logger

# Nitter instances — ลองตามลำดับ ถ้าใดล่มข้ามไปตัวถัดไป
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacyredirect.com",
    "https://nitter.poast.org",
]

_TWEET_CACHE_TTL = 300   # 5 นาที — ไม่ re-fetch ถ้า cache ยังสด
_tweet_cache: tuple[float, list] = (0.0, [])


def _fetch_rss(url: str, timeout: int = 6) -> list:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()

        if not raw or len(raw) < 50:
            logger.warning(f"Empty response from {url}")
            return []

        root = ET.fromstring(raw)
        items = []
        for item in root.findall(".//item"):
            title = item.findtext("title") or ""
            desc  = item.findtext("description") or ""
            link  = item.findtext("link") or ""
            date  = item.findtext("pubDate") or ""
            text  = re.sub(r"<[^>]+>", " ", title + " " + desc).strip()
            text  = re.sub(r"\s+", " ", text)
            username = url.split("/")[3].split("/")[0]
            items.append({
                "id":         link,
                "text":       text[:500],
                "user":       username,
                "created_at": date,
                "likes":      0,
                "retweets":   0,
            })
        return items

    except ET.ParseError as e:
        logger.warning(f"RSS parse error {url}: {e}")
        return []
    except Exception as e:
        logger.warning(f"RSS fetch failed {url}: {e}")
        return []


def _fetch_account(account: str, limit: int = 15) -> list:
    """ลอง Nitter instances ตามลำดับ — คืนผลจาก instance แรกที่สำเร็จ"""
    for base in NITTER_INSTANCES:
        url    = f"{base}/{account}/rss"
        tweets = _fetch_rss(url)
        if tweets:
            logger.info(f"@{account}: {len(tweets[:limit])} tweets")
            return tweets[:limit]
    logger.info(f"@{account}: 0 tweets (ทุก Nitter instance ล้มเหลว)")
    return []


async def fetch_from_accounts(limit_per_account: int = 15) -> list:
    """ดึง tweet จากแต่ละ account ผ่าน Nitter RSS — cache 5 นาที"""
    global _tweet_cache

    now_ts = _time.time()
    cached_at, cached_items = _tweet_cache
    if now_ts - cached_at < _TWEET_CACHE_TTL:
        age_sec = int(now_ts - cached_at)
        logger.debug(f"Twitter: ใช้ cache (อายุ {age_sec}s)")
        return cached_items

    all_tweets = []
    for account in X_ACCOUNTS_TO_FOLLOW:
        tweets = await asyncio.to_thread(_fetch_account, account, limit_per_account)
        all_tweets.extend(tweets)
        await asyncio.sleep(0.5)

    if all_tweets:
        _tweet_cache = (now_ts, all_tweets)
    elif cached_items:
        logger.info("Twitter: fetch ไม่ได้ข้อมูล — ใช้ cache เก่า")
        return cached_items

    return all_tweets


async def fetch_gold_news(limit: int = 30) -> list:
    """กรอง tweet เฉพาะที่เกี่ยวกับ gold/keyword — เรียกใช้ cache จาก fetch_from_accounts"""
    all_tweets = await fetch_from_accounts(limit_per_account=15)

    keywords_lower = [k.lower() for k in X_KEYWORDS]
    filtered = [
        t for t in all_tweets
        if any(kw in t["text"].lower() for kw in keywords_lower)
    ]

    logger.info(f"กรอง keyword แล้ว: {len(filtered)}/{len(all_tweets)} tweets")
    return filtered[:limit] if filtered else all_tweets[:limit]
