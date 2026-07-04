"""
agents/news_impact.py — Feature A: News Impact core (M1 + M3)

Pure code-only lib.  No LLM, no network, no database, no MT5.

Public API (M1):
    normalize_posts(news_data)        -> list[dict]
    is_gold_relevant(text)            -> bool
    content_hash(text)                -> str  (8-char hex)
    prefilter_and_dedupe(posts)       -> (kept: list[dict], stats: dict)

Public API (M3 — added):
    parse_scores(haiku_raw)           -> list[dict]   ([] on any failure)
    rolling_aggregate(scored_posts)   -> dict          (§4.1 aggregate)
    write_snapshot(agg, scored_posts, filter_stats) -> None  (atomic)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# M3 — parse_scores, rolling_aggregate, write_snapshot
# ---------------------------------------------------------------------------

# Half-life lookup: Haiku token → minutes used for freshness decay
_HALF_LIFE_MINUTES: dict[str, int] = {
    "min":  30,   # effect lasts <1 h   → half-life 30 min
    "hour": 120,  # effect lasts 1–12 h → half-life 120 min
    "day":  480,  # effect lasts >12 h  → half-life 480 min
}

# Where to write the display snapshot (relative to this file's directory)
_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data")
)
_SNAPSHOT_PATH = os.path.join(_DATA_DIR, "news_impact.json")


def parse_scores(haiku_raw: str) -> list[dict[str, Any]]:
    """
    Extract per-post JSON scores from a Haiku response.

    Looks for a SCORES: block delimited by a fenced JSON section (```json … ```)
    or a bare JSON array after the SCORES: marker.

    Returns [] on ANY failure — never raises.
    """
    try:
        # Try fenced block first: SCORES:\n```json\n[...]\n```
        match = re.search(
            r"SCORES:\s*```(?:json)?\s*(\[.*?\])\s*```",
            haiku_raw,
            re.DOTALL,
        )
        if not match:
            # Bare array after SCORES:
            match = re.search(
                r"SCORES:\s*(\[.*?\])",
                haiku_raw,
                re.DOTALL,
            )
        if not match:
            return []

        raw_json = match.group(1).strip()
        scores = json.loads(raw_json)

        if not isinstance(scores, list):
            return []

        valid: list[dict[str, Any]] = []
        for s in scores:
            if not isinstance(s, dict):
                continue
            direction = str(s.get("direction", "neutral")).lower()
            if direction not in ("bull", "bear", "neutral"):
                direction = "neutral"
            try:
                confidence = float(s.get("confidence", 0.0))
                confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = 0.0
            try:
                magnitude_tier = int(s.get("magnitude_tier", 1))
                magnitude_tier = max(1, min(3, magnitude_tier))
            except (TypeError, ValueError):
                magnitude_tier = 1
            half_life = str(s.get("half_life", "hour")).lower()
            if half_life not in _HALF_LIFE_MINUTES:
                half_life = "hour"
            valid.append({
                "id":             str(s.get("id", "")),
                "direction":      direction,
                "confidence":     confidence,
                "magnitude_tier": magnitude_tier,
                "half_life":      half_life,
                "reason":         str(s.get("reason", ""))[:80],
            })
        return valid

    except Exception:   # noqa: BLE001
        return []


def rolling_aggregate(scored_posts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute a magnitude×freshness-weighted net bull/bear score.

    Each entry in scored_posts should carry:
        direction       "bull" | "bear" | "neutral"
        confidence      0.0–1.0
        magnitude_tier  1 | 2 | 3
        half_life       "min" | "hour" | "day"
        ts_utc          ISO timestamp string (optional — omit for no decay)

    Returns §4.1 aggregate dict.
    """
    _empty_agg: dict[str, Any] = {
        "score":      0,
        "label":      "neutral gold",
        "n_scored":   0,
        "provenance": "rubric",
        "n":          0,
    }
    if not scored_posts:
        return _empty_agg

    now = datetime.now(timezone.utc)
    # Magnitude weights: tier 1→1, tier 2→2, tier 3→4
    _MAG_WEIGHT = {1: 1.0, 2: 2.0, 3: 4.0}

    total_weight = 0.0
    weighted_score = 0.0

    for post in scored_posts:
        direction      = post.get("direction", "neutral")
        confidence     = float(post.get("confidence", 0.5) or 0.0)
        magnitude_tier = int(post.get("magnitude_tier", 1) or 1)
        half_life_key  = post.get("half_life", "hour") or "hour"
        ts_utc_str     = post.get("ts_utc", "") or ""

        mag_w      = _MAG_WEIGHT.get(magnitude_tier, 1.0)
        half_min   = _HALF_LIFE_MINUTES.get(half_life_key, 120)

        # Freshness: exponential decay e^(-ln2 * age / half_life)
        try:
            if ts_utc_str:
                ts = datetime.fromisoformat(ts_utc_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_min = max(0.0, (now - ts).total_seconds() / 60.0)
            else:
                age_min = 0.0
        except Exception:   # noqa: BLE001
            age_min = 0.0

        freshness = math.exp(-math.log(2) * age_min / half_min)

        weight = mag_w * confidence * freshness
        total_weight += weight

        if direction == "bull":
            weighted_score += weight
        elif direction == "bear":
            weighted_score -= weight
        # neutral: no contribution

    if total_weight == 0.0:
        return _empty_agg

    # Scale to -100..+100 int
    raw_ratio = weighted_score / total_weight  # -1..+1
    score = int(round(raw_ratio * 100))
    score = max(-100, min(100, score))

    if score > 10:
        label = "bullish gold"
    elif score < -10:
        label = "bearish gold"
    else:
        label = "neutral gold"

    return {
        "score":      score,
        "label":      label,
        "n_scored":   len(scored_posts),
        "provenance": "rubric",
        "n":          len(scored_posts),
    }


def write_snapshot(
    agg: dict[str, Any],
    scored_posts: list[dict[str, Any]],
    filter_stats: dict[str, Any] | None = None,
) -> None:
    """
    Atomic write of data/news_impact.json in the exact §4.1 shape.
    Uses tmp + os.replace.  Never raises — logs warning on failure.
    """
    if filter_stats is None:
        filter_stats = {"raw": 0, "kept": 0, "filter_rate_pct": 0.0}

    # F-10: on a no-scores round (cache HIT with pruned/lost scores-cache), don't
    # overwrite a previously populated snapshot with an empty one — keep the last
    # real display. Still write when there is genuinely nothing yet (fresh install).
    if not scored_posts:
        try:
            with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                if (json.load(f) or {}).get("posts"):
                    log.debug("[news_impact] no scores this round — keeping existing snapshot")
                    return
        except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
            pass  # no usable existing snapshot → fall through and write the empty one

    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build posts array in §4.1 shape
    posts_out: list[dict[str, Any]] = []
    for p in scored_posts:
        ts_str = str(p.get("ts_utc", "") or "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_min = int(max(0, (now - ts).total_seconds() / 60))
        except Exception:   # noqa: BLE001
            age_min = 0

        half_life_key  = str(p.get("half_life", "hour") or "hour")
        half_life_min  = _HALF_LIFE_MINUTES.get(half_life_key, 120)

        # confidence from Haiku is 0.0–1.0; §4.1 wants 0..100 int
        raw_conf = p.get("confidence", 0.0)
        try:
            conf_100 = int(round(float(raw_conf) * 100))
        except (TypeError, ValueError):
            conf_100 = 0

        # post_id: prefer content_hash (dedupe key); fall back to id
        post_id = str(
            p.get("content_hash") or p.get("id") or ""
        )

        posts_out.append({
            "post_id":        post_id,
            "source":         str(p.get("source", "") or ""),
            "author":         str(p.get("author", "") or ""),
            "text":           str(p.get("text", "") or "")[:160],
            "ts_utc":         ts_str,
            "age_min":        age_min,
            "direction":      str(p.get("direction", "neutral")),
            "confidence":     conf_100,
            "magnitude_tier": int(p.get("magnitude_tier", 1) or 1),
            "half_life_min":  half_life_min,
            "reason":         str(p.get("reason", "") or ""),
            "provenance":     "rubric",
        })

    snapshot: dict[str, Any] = {
        "ok":          True,
        "updated":     now_iso,
        "window_min":  180,
        "aggregate":   agg,
        "filter_stats": {
            "raw":             int(filter_stats.get("raw", 0)),
            "kept":            int(filter_stats.get("kept", 0)),
            "filter_rate_pct": float(filter_stats.get("filter_rate_pct", 0.0)),
        },
        "posts": posts_out,
    }

    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _SNAPSHOT_PATH)
            log.debug("[news_impact] snapshot written → %s", _SNAPSHOT_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:   # noqa: BLE001
                pass
            raise
    except Exception as exc:   # noqa: BLE001
        log.warning("[news_impact] write_snapshot failed: %s", exc)
