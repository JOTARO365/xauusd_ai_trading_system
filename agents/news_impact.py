"""
agents/news_impact.py — Feature A: News Impact core (M1 — normalize / filter / dedupe)

Pure code-only lib.  No LLM, no network, no database, no MT5.
M3 will add: parse_scores, rolling_aggregate, write_snapshot.

Public API (M1):
    normalize_posts(news_data)        -> list[dict]
    is_gold_relevant(text)            -> bool
    content_hash(text)                -> str  (8-char hex)
    prefilter_and_dedupe(posts)       -> (kept: list[dict], stats: dict)
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gold-factor keyword set (module constant — extend here, nowhere else)
# ---------------------------------------------------------------------------
# Covers: Fed/monetary-policy, CPI/inflation, yields/bonds, USD/DXY, gold/XAU
# direct, geopolitical risk, trade/tariff, key political figures & institutions,
# macro data releases, and risk-sentiment terms.
#
# Design choices:
#   • Word-boundary (\b) prevents partial matches ("rater" ≠ "rate").
#   • Patterns like r"\bgeopolit\w*" capture geopolitical/geopolitics/geopolitik.
#   • "china" / "taiwan" / "iran" etc. are included because their mentions in a
#     financial context reliably flag safe-haven / risk-off moves for gold.
#   • Kept tight: no generic words like "market", "news", "stock", "equity" —
#     those would let everything through and undermine the ≥70% drop target.
# ---------------------------------------------------------------------------
_GOLD_KEYWORDS: list[str] = [
    # Fed / monetary policy
    r"\bfed\b",
    r"\bfomc\b",
    r"\bpowell\b",
    r"\bwarsh\b",
    r"\bwaller\b",
    r"\bjefferson\b",
    r"\bkugler\b",
    r"\bfederal\s+reserve\b",
    r"\bfed\s+funds\b",
    r"\bfed\s+chair\b",
    r"\brate\s+hike\b",
    r"\brate\s+cut\b",
    r"\brate\s+hold\b",
    r"\brate\s+pause\b",
    r"\binterest\s+rate\b",
    r"\brate\s+decision\b",
    r"\bhawkish\b",
    r"\bdovish\b",
    r"\bmonetary\s+policy\b",
    r"\bquantitative\s+easing\b",
    r"\bquantitative\s+tightening\b",
    r"\bqe\b",
    r"\bqt\b",
    # Inflation / CPI / PCE
    r"\bcpi\b",
    r"\bcore\s+cpi\b",
    r"\bpce\b",
    r"\bcore\s+pce\b",
    r"\binflation\b",
    r"\bdeflation\b",
    r"\bdisinflation\b",
    r"\bprice\s+index\b",
    r"\bconsumer\s+price\b",
    r"\bppi\b",
    # Yields / bonds
    r"\byield\b",
    r"\byields\b",
    r"\btreasury\b",
    r"\btreasuries\b",
    r"\b10[\s\-]year\b",
    r"\b2[\s\-]year\b",
    r"\bt[\s\-]note\b",
    r"\bt[\s\-]bond\b",
    r"\bbond\s+market\b",
    r"\bdebt\s+ceiling\b",
    # USD / DXY / dollar
    r"\bdxy\b",
    r"\bdollar\b",
    r"\busd\b",
    r"\bdollar\s+index\b",
    r"\bdollar\s+strength\b",
    r"\bdollar\s+weakness\b",
    # Gold / XAU direct
    r"\bgold\b",
    r"\bxau\b",
    r"\bxauusd\b",
    r"\bbullion\b",
    r"\bgold\s+price\b",
    r"\bspot\s+gold\b",
    r"\bprecious\s+metal\b",
    # Geopolitical risk
    r"\bwar\b",
    r"\bconflict\b",
    r"\bgeopolit\w*",
    r"\bsanction\b",
    r"\bsanctions\b",
    r"\bmilitary\b",
    r"\bstrike\b",
    r"\battack\b",
    r"\bukraine\b",
    r"\brussia\b",
    r"\biran\b",
    r"\bisrael\b",
    r"\bhamas\b",
    r"\bhamas\b",
    r"\bmiddle\s+east\b",
    r"\bgaza\b",
    r"\bhormuz\b",
    r"\bstrait\s+of\s+hormuz\b",
    r"\btaiwan\b",
    r"\bchina\b",
    r"\bnorth\s+korea\b",
    r"\bcrisis\b",
    r"\bescalat\w*",
    # Trade / tariff
    r"\btariff\b",
    r"\btariffs\b",
    r"\btrade\s+war\b",
    r"\btrade\s+deal\b",
    r"\btrade\s+policy\b",
    r"\bimport\s+dut\w+",
    r"\bwto\b",
    r"\btrade\s+deficit\b",
    # Key political figures & institutions
    r"\btrump\b",
    r"\bbiden\b",
    r"\bwhite\s+house\b",
    r"\bcongress\b",
    r"\bsenate\b",
    # Economic data releases
    r"\bnfp\b",
    r"\bnonfarm\b",
    r"\bunemployment\b",
    r"\bjobless\b",
    r"\bgdp\b",
    r"\brecession\b",
    r"\bpayrolls\b",
    r"\bdurables\b",
    r"\bretail\s+sales\b",
    # Risk sentiment
    r"\brisk[\s\-]off\b",
    r"\brisk[\s\-]on\b",
    r"\bsafe[\s\-]haven\b",
    r"\bvolatility\b",
    r"\bvix\b",
]

# Compiled once at import time — OR of all patterns, case-insensitive
_GOLD_REGEX: re.Pattern[str] = re.compile(
    "|".join(_GOLD_KEYWORDS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_posts(news_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Unify tweets and web_articles into a common schema.

    Input:
        news_data["tweets"]       — list of {id, text, user, created_at}
        news_data["web_articles"] — list of {title, summary, ...}

    Output per post:
        {id, source, text, author, ts_utc}

    Calendar entries are deliberately excluded — Feature B handles them.
    Malformed entries are silently skipped (fail-soft).
    """
    posts: list[dict[str, Any]] = []

    # --- tweets --------------------------------------------------------------
    for t in news_data.get("tweets", []) or []:
        try:
            posts.append({
                "id":     str(t.get("id", "")),
                "source": "twitter",
                "text":   str(t.get("text", "")),
                "author": str(t.get("user", "")),
                "ts_utc": str(t.get("created_at", "")),
            })
        except Exception:  # noqa: BLE001
            log.debug("[news_impact] skipping malformed tweet entry")

    # --- web_articles --------------------------------------------------------
    for a in news_data.get("web_articles", []) or []:
        try:
            title   = str(a.get("title", ""))
            summary = str(a.get("summary", ""))
            # Combine title + summary so the relevance filter can see both.
            text    = f"{title}. {summary}".strip(". ")
            # Use explicit id when present; fall back to a hash of the title.
            art_id  = str(a.get("id", "")) or content_hash(title)
            posts.append({
                "id":     art_id,
                "source": "web",
                "text":   text,
                "author": str(a.get("source", a.get("author", ""))),
                "ts_utc": str(a.get("published_at", a.get("ts_utc", ""))),
            })
        except Exception:  # noqa: BLE001
            log.debug("[news_impact] skipping malformed web_article entry")

    return posts


def is_gold_relevant(text: str) -> bool:
    """
    Return True when `text` contains at least one gold-factor keyword.

    Matching is case-insensitive and word-boundary anchored so partial
    matches (e.g. "rater" matching "rate") are avoided.
    """
    return bool(_GOLD_REGEX.search(text))


def content_hash(text: str) -> str:
    """
    Return a stable 8-character hex digest of the normalised text.

    Normalisation: lowercase + collapse all whitespace → single spaces.
    This ensures minor formatting differences (extra spaces, newlines)
    between otherwise identical stories map to the same dedupe key.
    """
    normalised = " ".join(text.lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:8]


def prefilter_and_dedupe(
    posts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Two-step reduction pipeline:

    1. Gold-factor keyword filter — keep only posts where is_gold_relevant
       returns True on the `text` field.
    2. Content-hash dedupe — when two posts share the same normalised-text
       hash (same story appearing in tweets AND web_articles, or retweets),
       keep the first occurrence only.

    Each surviving post is annotated with its `content_hash` key for
    downstream use (M3 score caching, M4 realized-move logger anchor).

    Returns:
        kept  — filtered + deduped posts
        stats — {"raw": int, "kept": int, "filter_rate_pct": float}
                filter_rate_pct = % of raw posts that were removed (0–100)
    """
    raw: int = len(posts)
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()

    for post in posts:
        text = post.get("text", "")
        if not is_gold_relevant(text):
            continue
        h = content_hash(text)
        if h in seen:
            continue
        seen.add(h)
        kept.append({**post, "content_hash": h})

    n_kept = len(kept)
    filter_rate = round((1.0 - n_kept / raw) * 100.0, 1) if raw > 0 else 0.0

    stats: dict[str, Any] = {
        "raw":             raw,
        "kept":            n_kept,
        "filter_rate_pct": filter_rate,
    }
    return kept, stats
