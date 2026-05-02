import asyncio
from connectors.twitter_client import fetch_gold_news, fetch_from_accounts
from connectors.web_news import fetch_forexfactory_calendar, fetch_investing_news
from loguru import logger


async def gather_news() -> dict:
    logger.info("Agent 2 (ผู้หาข้อมูล): กำลังดึงข่าวจาก X + ForexFactory + Investing.com...")

    # รัน Twitter + web news พร้อมกัน
    (keyword_tweets, account_tweets, calendar, articles) = await asyncio.gather(
        fetch_gold_news(limit=30),
        fetch_from_accounts(limit_per_account=10),
        asyncio.to_thread(fetch_forexfactory_calendar, 24),
        asyncio.to_thread(fetch_investing_news, 10),
    )

    # กรอง tweet ซ้ำ
    seen: set = set()
    unique_tweets: list = []
    for t in keyword_tweets + account_tweets:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique_tweets.append(t)

    logger.info(
        f"รวม: {len(unique_tweets)} tweets | "
        f"{len(calendar)} FF events | "
        f"{len(articles)} investing articles"
    )

    return {
        "tweets":         unique_tweets,
        "count":          len(unique_tweets),
        "calendar":       calendar,       # high-impact economic events
        "web_articles":   articles,       # investing.com headlines
        "sources": {
            "keyword_search":  len(keyword_tweets),
            "account_feed":    len(account_tweets),
            "forexfactory":    len(calendar),
            "investing_com":   len(articles),
        },
    }
