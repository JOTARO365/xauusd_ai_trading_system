"""
Lesson Store — RAG-based Lesson Retrieval (v2)
Hybrid search: pre-filter(direction+trend) → vector cosine → weighted score(frequency × recency)
Deduplication: pattern ซ้ำ (same mistake_type+direction+trend) → increment frequency แทน insert ใหม่
"""
import os
from datetime import datetime, timedelta, timezone
from loguru import logger

_LESSON_TTL_DAYS  = 90
_DEDUP_WINDOW_DAYS = 30   # รวม lesson ที่เกิดซ้ำภายใน 30 วัน
_EMBED_MODEL = "models/gemini-embedding-001"  # stable model ที่ v1beta รองรับ
_EMBED_DIM   = 768                            # ลด dim จาก 3072 → 768 ด้วย output_dimensionality

# คำแนะนำต่อ mistake_type — inject เข้า prompt เพื่อให้ Claude รู้ว่าต้องทำอะไร
_MISTAKE_ADVICE = {
    "COUNTER_TREND":        "require conf≥70 or SKIP",
    "NO_SR_ZONE":           "require clear S/R zone before entry",
    "OVERCONFIDENCE":       "reduce lot size, verify confluence",
    "LOW_CONFIDENCE_ENTRY": "SKIP if conf<60",
    "NEWS_TIMING":          "wait ≥30min after high-impact news",
    "WIDE_SL":              "tighten SL to wick high/low",
    "PENDING_WRONG_LEVEL":  "re-verify pending level vs current S/R",
    "OTHER":                "review setup carefully before entry",
}


def _get_db():
    from db.connection import get_client
    return get_client()


def _get_account_login() -> int:
    try:
        import config
        return config.MT5_LOGIN or 0
    except Exception:
        return 0


def _get_gemini_client():
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except ImportError:
        logger.warning("google-genai ไม่ได้ติดตั้ง — ข้าม lesson embedding")
        return None


def _embed(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float] | None:
    client = _get_gemini_client()
    if not client:
        return None
    try:
        from google.genai import types
        result = client.models.embed_content(
            model=_EMBED_MODEL,
            contents=text[:2000],
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=_EMBED_DIM),
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.warning(f"Gemini embedding error (lesson): {e}")
        return None


def _make_embed_text(mistake_type: str, pattern: str, direction: str, trend: str, sr_zone: str, conf) -> str:
    return f"[{mistake_type}] {pattern} | {direction} {trend} sr:{sr_zone} conf:{conf}"


# ─────────────────────────────────────────────────────────────
#  WRITE (dedup + frequency counter)
# ─────────────────────────────────────────────────────────────

def store_lesson(
    mistake_type: str,
    pattern: str,
    context: dict,
) -> bool:
    """
    บันทึก lesson — ถ้า pattern เดิมเกิดซ้ำภายใน 30 วัน → increment frequency แทน insert ใหม่
    context ต้องมี: direction, trend, sr_zone, confidence, pnl
    """
    if not mistake_type or not pattern:
        return False

    account_login = _get_account_login()
    direction     = (context.get("direction") or "").upper()
    trend         = (context.get("trend")     or "").upper()
    market_regime = (context.get("market_regime") or "").upper()
    pnl           = float(context.get("pnl") or 0)
    sr_zone       = context.get("sr_zone", "?")
    conf          = context.get("confidence", "?")

    dedup_cutoff = (datetime.now(timezone.utc) - timedelta(days=_DEDUP_WINDOW_DAYS)).isoformat()
    expires_at   = (datetime.now(timezone.utc) + timedelta(days=_LESSON_TTL_DAYS)).isoformat()

    embed_text = _make_embed_text(mistake_type, pattern, direction, trend, sr_zone, conf)
    embedding  = _embed(embed_text, task_type="RETRIEVAL_DOCUMENT")

    db = _get_db()

    try:
        # ── ตรวจ dedup: same mistake_type + direction + trend ใน 30 วัน ──────
        existing = db.table("trade_lessons").select("id,frequency,avg_pnl").eq(
            "account_login", account_login
        ).eq("mistake_type", mistake_type).eq("direction", direction).eq(
            "trend", trend
        ).gt("created_at", dedup_cutoff).order("created_at", desc=True).limit(1).execute()

        if existing.data:
            # ── UPDATE: increment frequency, rolling avg_pnl, refresh pattern ──
            old        = existing.data[0]
            new_freq   = old["frequency"] + 1
            new_avg    = round((old["avg_pnl"] * (new_freq - 1) + pnl) / new_freq, 2)
            update_row = {
                "frequency":  new_freq,
                "avg_pnl":    new_avg,
                "pattern":    pattern[:500],
                "expires_at": expires_at,
            }
            if embedding:
                update_row["embedding"] = embedding
            db.table("trade_lessons").update(update_row).eq("id", old["id"]).execute()
            logger.info(f"Lesson updated (x{new_freq}): [{mistake_type}] {direction}/{trend} avg_pnl={new_avg:+.2f}")
            return True

        # ── INSERT: lesson ใหม่ ───────────────────────────────────────────────
        row = {
            "account_login": account_login,
            "mistake_type":  mistake_type,
            "pattern":       pattern[:500],
            "direction":     direction,
            "trend":         trend,
            "market_regime": market_regime,
            "frequency":     1,
            "avg_pnl":       pnl,
            "context":       context,
            "expires_at":    expires_at,
        }
        if embedding:
            row["embedding"] = embedding
        db.table("trade_lessons").insert(row).execute()
        logger.info(f"Lesson stored (new): [{mistake_type}] {direction}/{trend} pnl={pnl:+.2f}")
        return True

    except Exception as e:
        logger.warning(f"Lesson store error: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  READ — hybrid search
# ─────────────────────────────────────────────────────────────

def search_lessons(
    context_text: str,
    direction: str = "",
    trend: str = "",
    top_k: int = 3,
) -> list[dict]:
    """
    Hybrid search:
      1. pre-filter by direction + trend (exact match)
      2. cosine similarity (vector)
      3. weighted score = cosine × frequency_boost × recency_boost

    context_text: เช่น "BUY COUNTER_TREND H4:BEARISH SR:NONE confidence:55"
    direction: "BUY"/"SELL" — ถ้าระบุจะ pre-filter ก่อน
    trend: "BULLISH"/"BEARISH"/"SIDEWAYS"
    """
    if not _get_gemini_client():
        return []

    query_emb = _embed(context_text, task_type="RETRIEVAL_QUERY")
    if not query_emb:
        return []

    account_login = _get_account_login()

    try:
        res = _get_db().rpc("search_trade_lessons", {
            "query_embedding": query_emb,
            "match_count":     top_k,
            "p_account":       account_login,
            "p_direction":     direction.upper(),
            "p_trend":         trend.upper(),
        }).execute()

        lessons = []
        for row in (res.data or []):
            lessons.append({
                "mistake_type": row["mistake_type"],
                "pattern":      row["pattern"],
                "direction":    row.get("direction", ""),
                "trend":        row.get("trend", ""),
                "frequency":    row.get("frequency", 1),
                "avg_pnl":      row.get("avg_pnl", 0),
                "context":      row.get("context", {}),
                "score":        round(float(row.get("score", 0)), 3),
            })
        logger.debug(f"Lesson search: {len(lessons)} results | dir={direction} trend={trend}")
        return lessons

    except Exception as e:
        logger.warning(f"Lesson search error: {e}")
        return []


def format_lessons_for_prompt(lessons: list[dict]) -> str:
    """
    แปลง lessons เป็น text block สำหรับ inject เข้า DecisionMaker prompt
    รูปแบบ: บอก Claude ว่า pattern เดิมเกิดซ้ำกี่ครั้ง + avg loss + สิ่งที่ต้องทำ
    max ~150 tokens
    """
    if not lessons:
        return ""

    lines = ["⚠ Similar past mistakes (review before deciding):"]
    for L in lessons[:3]:
        freq     = L.get("frequency", 1)
        avg_pnl  = L.get("avg_pnl", 0)
        mtype    = L.get("mistake_type", "OTHER")
        pattern  = L.get("pattern", "")[:110]
        advice   = _MISTAKE_ADVICE.get(mtype, "review carefully")
        occ      = f"x{freq}" if freq > 1 else "x1"
        pnl_str  = f"avg {avg_pnl:+.2f}" if avg_pnl != 0 else ""

        lines.append(f"  [{occ}] {mtype}: {pattern} {pnl_str}")
        lines.append(f"    → {advice}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  CLEANUP
# ─────────────────────────────────────────────────────────────

def cleanup_expired_lessons() -> int:
    """ลบ lessons ที่หมดอายุ"""
    try:
        now = datetime.now(timezone.utc).isoformat()
        res = _get_db().table("trade_lessons").delete().lt("expires_at", now).execute()
        deleted = len(res.data or [])
        if deleted:
            logger.info(f"Cleaned up {deleted} expired lessons")
        return deleted
    except Exception as e:
        logger.warning(f"Lesson cleanup error: {e}")
        return 0
