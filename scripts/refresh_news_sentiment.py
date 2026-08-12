"""scripts/refresh_news_sentiment.py — force-refresh การวิเคราะห์ข่าว + sentiment ให้เป็นปัจจุบัน.

ใช้ prompt/pipeline เดียวกับที่บอทใช้:
  1. fetch news สด (ForexFactory calendar + Investing articles)
  2. get_news_context(force_fresh=True) → Haiku สรุป+ให้คะแนน → เขียน data/news_impact.json
  3. sentiment_score.get_score(force=True) → Sonnet (gold macro strategist prompt) → data/sentiment_score.json
     (sentiment อ่าน news_impact สดที่เพิ่งเขียน + macro_strip/actuals/regime)

⚠️ มี token cost (Haiku ข่าว + Sonnet sentiment). รัน: python scripts/refresh_news_sentiment.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main():
    from dotenv import load_dotenv
    load_dotenv(override=True)

    # 1) news_data สด (เหมือน analyst ประกอบ)
    news_data = {"tweets": [], "calendar": [], "web_articles": []}
    try:
        from connectors.web_news import fetch_forexfactory_calendar
        news_data["calendar"] = fetch_forexfactory_calendar() or []
    except Exception as e:
        print(f"  -- calendar fail: {str(e)[:80]}")
    try:
        from connectors.web_news import fetch_investing_news
        news_data["web_articles"] = fetch_investing_news(limit=12) or []
    except Exception as e:
        print(f"  -- articles fail: {str(e)[:80]}")
    try:
        from connectors.twitter_client import fetch_recent_tweets   # optional
        news_data["tweets"] = fetch_recent_tweets() or []
    except Exception:
        pass
    print(f"news_data: calendar={len(news_data['calendar'])} "
          f"articles={len(news_data['web_articles'])} tweets={len(news_data['tweets'])}")

    # 2) news analysis (Haiku) → data/news_impact.json
    print("\n[1/2] วิเคราะห์ข่าว (Haiku, force fresh)…")
    from agents.news_cache import get_news_context
    nc = get_news_context(news_data, market_context="", force_fresh=True)
    print("  summary:", (nc.get("summary") or "")[:280])
    try:
        import json
        ni = json.load(open(os.path.join(_ROOT, "data", "news_impact.json"), encoding="utf-8"))
        print(f"  news_impact: score={ni.get('score')} label={ni.get('label')} n={ni.get('n_scored')} updated={ni.get('updated')}")
    except Exception:
        pass

    # 3) sentiment (Sonnet, gold macro strategist prompt) → data/sentiment_score.json
    print("\n[2/2] sentiment (Sonnet, force)…")
    from agents.sentiment_score import get_score
    s = get_score(force=True)
    print("  sentiment:", s)
    print("\ndone → data/news_impact.json + data/sentiment_score.json (บอทอ่านรอบถัดไป)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
