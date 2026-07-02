"""
News Cache — Haiku pre-summarization + pgvector search (Gemini embeddings)
ประหยัด ~83% token ของ analyst.py โดย:
  1. สรุปข่าวด้วย Haiku (ถูกกว่า Sonnet 12x) และ cache 1 ชั่วโมง
  2. Embed ด้วย Gemini text-embedding-004 (768 dim, free tier)
     → vector search หา top-N ที่ relevant กับ market context
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone
from loguru import logger

import anthropic

_anthropic   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_EMBED_MODEL = "models/gemini-embedding-001"  # Gemini stable embedding model
_EMBED_DIM   = 3072                           # Gemini output dimension
_CACHE_TTL_H = 1                              # ชั่วโมง


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _hash_news(news_data: dict) -> str:
    """MD5 ของ headlines — เปลี่ยนเมื่อข่าวใหม่เข้ามา"""
    parts = (
        [t["text"][:80] for t in news_data.get("tweets", [])[:10]] +
        [e.get("title", "") for e in news_data.get("calendar", [])] +
        [a.get("title", "") for a in news_data.get("web_articles", [])]
    )
    return hashlib.md5("|".join(sorted(parts)).encode()).hexdigest()


def _get_db():
    from db.connection import get_client
    return get_client()


def _gemini_available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", ""))


def _get_gemini_client():
    """Lazy load google-genai client — return client หรือ None"""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except ImportError:
        logger.warning("google-genai ไม่ได้ติดตั้ง — ข้าม embedding (pip install google-genai)")
        return None


# ─────────────────────────────────────────────────────────────
#  CACHE READ
# ─────────────────────────────────────────────────────────────

def _get_cache_by_hash(content_hash: str) -> dict | None:
    """ดึง cache ที่ตรง hash และยังไม่หมดอายุ"""
    try:
        now = datetime.now(timezone.utc).isoformat()
        res = _get_db().table("news_cache").select("id,summary").eq(
            "content_hash", content_hash
        ).gt("expires_at", now).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.warning(f"News cache read error: {e}")
        return None


def _get_latest_valid_cache(max_age_min: int | None = None) -> dict | None:
    """ดึง cache ล่าสุดที่ยังไม่หมดอายุ.
    max_age_min: จำกัดอายุ (นาที) — ใช้ตอน hash MISS เพื่อ reuse ได้เฉพาะ cache สดจริง
    (กัน Haiku ยิงถี่จาก tweet สลับเล็กน้อย) โดยไม่ปล่อยให้ summary ค้างทั้ง TTL 1 ชม.
    None = ไม่จำกัดอายุ (ใช้เป็น error-fallback ตอน Haiku fail เท่านั้น)"""
    try:
        now = datetime.now(timezone.utc)
        res = _get_db().table("news_cache").select("id,summary,created_at").gt(
            "expires_at", now.isoformat()
        ).order("created_at", desc=True).limit(1).execute()
        if not res.data:
            return None
        row = res.data[0]
        if max_age_min is not None:
            try:
                created = datetime.fromisoformat(
                    str(row.get("created_at", "")).replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if (now - created).total_seconds() > max_age_min * 60:
                    return None   # cache สดไม่พอสำหรับ reuse — ให้ summarize ใหม่
            except ValueError:
                return None
        return row
    except Exception as e:
        logger.warning(f"News cache latest read error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  HAIKU SUMMARIZATION
# ─────────────────────────────────────────────────────────────

def _summarize_with_haiku(news_data: dict) -> str:
    """สรุปข่าว XAUUSD ด้วย Haiku — ได้ 5 bullet points ≈ 250 tokens"""
    tweets   = news_data.get("tweets", [])
    calendar = news_data.get("calendar", [])
    articles = news_data.get("web_articles", [])

    tweet_block = "\n".join(
        f"- {t.get('user','?')}: {t['text'][:150]}"
        for t in tweets[:10]
    ) or "none"

    cal_block = "\n".join(
        f"- [{e.get('time','?')}] {e.get('currency','?')} {e.get('title','?')} "
        f"forecast:{e.get('forecast','?')} actual:{e.get('actual','pending')}"
        for e in calendar[:8]
    ) or "none"

    art_block = "\n".join(
        f"- {a.get('title','?')}: {str(a.get('summary',''))[:120]}"
        for a in articles[:5]
    ) or "none"

    resp = _anthropic.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": f"""Summarize XAUUSD market news in exactly 5 bullet points.
Focus: Fed/rates, USD strength, geopolitics, gold demand, upcoming risk events.
Include numbers when available (e.g. CPI 3.2%, yields 4.5%).

TWEETS:
{tweet_block}

ECONOMIC CALENDAR:
{cal_block}

HEADLINES:
{art_block}

Output (5 bullets only, no extra text):
• ...
• ...
• ...
• ...
• ..."""}],
    )
    return resp.content[0].text.strip()


# ─────────────────────────────────────────────────────────────
#  EMBEDDINGS (Gemini text-embedding-004)
# ─────────────────────────────────────────────────────────────

def _embed(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float] | None:
    """
    Generate embedding ด้วย Gemini gemini-embedding-001 (3072 dim)
    task_type: 'RETRIEVAL_DOCUMENT' สำหรับ store, 'RETRIEVAL_QUERY' สำหรับ search
    """
    client = _get_gemini_client()
    if not client:
        return None
    try:
        from google.genai import types
        result = client.models.embed_content(
            model=_EMBED_MODEL,
            contents=text[:2000],
            config=types.EmbedContentConfig(task_type=task_type),
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.warning(f"Gemini embedding error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  CACHE WRITE
# ─────────────────────────────────────────────────────────────

def _store_cache(content_hash: str, summary: str, news_data: dict) -> int | None:
    """บันทึก summary + individual embeddings ลง Supabase"""
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_H)
    ).isoformat()

    try:
        db = _get_db()

        # upsert news_cache row
        res = db.table("news_cache").upsert(
            {"content_hash": content_hash, "summary": summary, "expires_at": expires_at},
            on_conflict="content_hash",
        ).execute()
        cache_id = res.data[0]["id"] if res.data else None
        if not cache_id:
            logger.warning("news_cache upsert ไม่คืน id")
            return None

        # สร้าง item list สำหรับ embed
        items: list[tuple[str, str]] = []
        for t in news_data.get("tweets", [])[:10]:
            items.append(("twitter", f"@{t.get('user','?')}: {t['text'][:300]}"))
        for e in news_data.get("calendar", [])[:8]:
            items.append(("forexfactory",
                f"{e.get('currency','?')} {e.get('title','?')} "
                f"forecast:{e.get('forecast','?')} actual:{e.get('actual','pending')}"))
        for a in news_data.get("web_articles", [])[:5]:
            items.append(("investing", f"{a.get('title','?')} {str(a.get('summary',''))[:200]}"))

        # embed แต่ละ item และ insert
        embedded = 0
        for source, content in items:
            emb = _embed(content, task_type="RETRIEVAL_DOCUMENT")
            row = {"cache_id": cache_id, "source": source, "content": content}
            if emb:
                row["embedding"] = emb
                embedded += 1
            db.table("news_embeddings").insert(row).execute()

        logger.info(
            f"News cache stored: {len(items)} items ({embedded} embedded) | "
            f"expires {expires_at}"
        )
        return cache_id

    except Exception as e:
        logger.warning(f"News cache store error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  VECTOR SEARCH
# ─────────────────────────────────────────────────────────────

def vector_search(query: str, top_n: int = 3) -> list[str]:
    """
    หา news items ที่ relevant กับ market context ปัจจุบัน
    query: เช่น "BUY signal BULLISH trend H4 resistance USD weakening"
    """
    if not _get_gemini_client():
        return []

    query_emb = _embed(query, task_type="RETRIEVAL_QUERY")
    if not query_emb:
        return []

    try:
        res = _get_db().rpc("search_news_relevant", {
            "query_embedding": query_emb,
            "match_count":     top_n,
        }).execute()
        items = [row["content"] for row in (res.data or [])]
        logger.debug(f"Vector search: {len(items)} relevant items for '{query[:60]}'")
        return items
    except Exception as e:
        logger.warning(f"Vector search error: {e}")
        return []


# ─────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

# hash MISS แต่ cache ล่าสุดอายุ ≤ นาทีนี้ → reuse ได้ (tweet มัก shuffle เล็กน้อยทุก cycle
# — summarize ใหม่ทุกครั้งเปลือง Haiku) เกินนี้ = ข่าวใหม่ต้องเห็นจริง ไม่ค้างทั้ง TTL 1 ชม.
_STALE_REUSE_MIN = 10


def get_news_context(news_data: dict, market_context: str = "",
                     force_fresh: bool = False) -> dict:
    """
    Main function — เรียกจาก analyst.py แทนการส่ง raw news ทั้งหมด

    Flow:
      1. ตรวจ cache: hash ตรง → ใช้เลย; hash ใหม่ → reuse ได้เฉพาะ cache อายุ ≤ 10 นาที
         (เดิม fallback ไป cache เก่าทั้ง TTL 1 ชม. = ข่าวใหม่ล่องหน — root ของ
         "sentiment ตามราคาไม่ทันตอน reversal")
      2. force_fresh=True (ราคาวิ่งแรง) → ข้าม reuse, summarize ใหม่เสมอ (hash ตรงยังใช้ได้)
      3. MISS → Haiku สรุป + Gemini embed + store; Haiku fail → fallback cache เก่า (resilience)
      4. vector_search หา top-3 items ที่ match กับ market context
      5. return {summary, relevant_items, from_cache, token_estimate}
    """
    content_hash = _hash_news(news_data)

    # ── ลอง cache ──────────────────────────────────────────────
    cached = _get_cache_by_hash(content_hash)
    if not cached and not force_fresh:
        cached = _get_latest_valid_cache(max_age_min=_STALE_REUSE_MIN)

    if cached:
        logger.info(f"News cache: HIT (id={cached['id']}) — ข้าม Haiku call")
        cache_id   = cached["id"]
        summary    = cached["summary"]
        from_cache = True
    else:
        logger.info("News cache: MISS — เรียก Haiku สรุปข่าว"
                    + (" [force_fresh: ราคาวิ่งแรง]" if force_fresh else ""))
        try:
            summary    = _summarize_with_haiku(news_data)
            cache_id   = _store_cache(content_hash, summary, news_data)
            from_cache = False
        except Exception as e:
            # Haiku fail → fallback cache เก่าที่ยังไม่หมดอายุ (ไม่จำกัดอายุ) ดีกว่าไม่มีข่าวเลย
            logger.warning(f"News summarize failed: {e} — ลอง fallback cache เก่า")
            stale = _get_latest_valid_cache()
            if stale is None:
                raise
            cache_id   = stale["id"]
            summary    = stale["summary"]
            from_cache = True

    # ── Vector search (ถ้ามี GEMINI_API_KEY) ───────────────────
    relevant: list[str] = []
    if market_context and _get_gemini_client():
        relevant = vector_search(market_context, top_n=3)

    # ── ประมาณ token ที่จะส่งไป Sonnet ────────────────────────
    context_text  = summary
    if relevant:
        context_text += "\n\nRelevant:\n" + "\n".join(f"- {r[:120]}" for r in relevant)
    token_estimate = len(context_text.split()) * 4 // 3

    return {
        "summary":        summary,
        "relevant_items": relevant,
        "cache_id":       cache_id,
        "from_cache":     from_cache,
        "token_estimate": token_estimate,
    }
