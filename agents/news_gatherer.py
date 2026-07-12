import asyncio
import re
from connectors.twitter_client import fetch_from_accounts
from connectors.web_news import fetch_forexfactory_calendar, fetch_investing_news
from config import X_KEYWORDS
from loguru import logger

# word-boundary match — substring เดิมทำให้คำสั้นจับผิดเป้า ("war"→forward/award,
# "oil"→boiling) → tweet ขยะไหลเข้า analyst; \b ทำให้ทุก keyword จับเฉพาะคำเต็ม
_KW_RE = re.compile(
    r"\b(" + "|".join(re.escape(k.lower()) for k in X_KEYWORDS) + r")\b"
) if X_KEYWORDS else None


async def gather_news() -> dict:
    logger.info("Agent 2 (ผู้หาข้อมูล): กำลังดึงข่าวจาก X + ForexFactory + Investing.com...")

    # ดึงข้อมูลทุกแหล่งพร้อมกัน — Twitter ดึงครั้งเดียว แล้วแยก filtered vs raw ทีหลัง
    # return_exceptions=True → ถ้าแหล่งใดแหล่งหนึ่ง raise (เช่น twitter) จะไม่ทำให้ทั้ง cycle
    # เสีย calendar + articles ไปด้วย; coerce ผลที่เป็น exception → [] แยกรายแหล่ง
    (raw_tweets, calendar, articles) = await asyncio.gather(
        fetch_from_accounts(limit_per_account=15),
        asyncio.to_thread(fetch_forexfactory_calendar, 24),
        asyncio.to_thread(fetch_investing_news, 10),
        return_exceptions=True,
    )
    for _name, _val in (("twitter", raw_tweets), ("forexfactory", calendar), ("investing", articles)):
        if isinstance(_val, BaseException):
            logger.warning(f"gather_news: {_name} fetch failed: {_val}")
    raw_tweets = raw_tweets if isinstance(raw_tweets, list) else []
    calendar   = calendar   if isinstance(calendar, list)   else []
    articles   = articles   if isinstance(articles, list)   else []

    # กรอง keyword (gold/XAU/etc) จาก raw tweets — word-boundary (ดู _KW_RE)
    keyword_tweets = [
        t for t in raw_tweets
        if _KW_RE and _KW_RE.search(t["text"].lower())
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
