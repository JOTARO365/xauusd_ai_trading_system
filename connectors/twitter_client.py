import asyncio
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from config import X_ACCOUNTS_TO_FOLLOW, X_KEYWORDS
from loguru import logger

NITTER_BASE = "https://nitter.net"


def _fetch_rss(url: str) -> list:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
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


async def fetch_gold_news(limit: int = 30) -> list:
    """ดึง tweet จาก account หลักที่ติดตาม กรองเฉพาะที่เกี่ยวกับ keyword"""
    all_tweets = await fetch_from_accounts(limit_per_account=15)

    # กรองเฉพาะ tweet ที่มี keyword เกี่ยวกับทอง
    keywords_lower = [k.lower() for k in X_KEYWORDS]
    filtered = [
        t for t in all_tweets
        if any(kw in t["text"].lower() for kw in keywords_lower)
    ]

    logger.info(f"กรอง keyword แล้ว: {len(filtered)}/{len(all_tweets)} tweets")
    return filtered[:limit] if filtered else all_tweets[:limit]


async def fetch_from_accounts(limit_per_account: int = 10) -> list:
    """ดึง tweet จากแต่ละ account ผ่าน Nitter RSS"""
    all_tweets = []
    for account in X_ACCOUNTS_TO_FOLLOW:
        url = f"{NITTER_BASE}/{account}/rss"
        tweets = _fetch_rss(url)
        all_tweets.extend(tweets[:limit_per_account])
        logger.info(f"@{account}: {len(tweets[:limit_per_account])} tweets")
        await asyncio.sleep(1)
    return all_tweets
