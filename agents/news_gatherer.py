import asyncio
from connectors.twitter_client import fetch_from_accounts
from connectors.web_news import fetch_forexfactory_calendar, fetch_investing_news
from config import X_KEYWORDS
from loguru import logger


async def gather_news() -> dict:
    logger.info("Agent 2 (ผู้หาข้อมูล): กำลังดึงข่าวจาก X + ForexFactory + Investing.com...")

    # ดึงข้อมูลทุกแหล่งพร้อมกัน — Twitter ดึงครั้งเดียว แล้วแยก filtered vs raw ทีหลัง
    (raw_tweets, calendar, articles) = await asyncio.gather(
        fetch_from_accounts(limit_per_account=15),
        asyncio.to_thread(fetch_forexfactory_calendar, 24),
        asyncio.to_thread(fetch_investing_news, 10),
    )

    # กรอง keyword (gold/XAU/etc) จาก raw tweets
    keywords_lower = [k.lower() for k in X_KEYWORDS]
    keyword_tweets = [
        t for t in raw_tweets
        if any(kw in t["text"].lower() for kw in keywords_lower)
    ]
    logger.info(f"กรอง keyword แล้ว: {len(keyword_tweets)}/{len(raw_tweets)} tweets")

    # dedup โดย id
    seen: set = set()
    unique_tweets: list = []
    for t in keyword_tweets + raw_tweets:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique_tweets.append(t)

    logger.info(
        f"รวม: {len(unique_tweets)} tweets | "
        f"{len(calendar)} FF events | "
        f"{len(articles)} investing articles"
    )

    return {
        "tweets":       unique_tweets,
        "count":        len(unique_tweets),
        "calendar":     calendar,
        "web_articles": articles,
        "sources": {
            "keyword_search": len(keyword_tweets),
            "account_feed":   len(raw_tweets),
            "forexfactory":   len(calendar),
            "investing_com":  len(articles),
        },
    }
