"""
scripts/realized_move_logger.py — Realized-Move Logger (M4)

Standalone scheduled script. Records XAUUSD price at +5/+15/+60 min after:
  • high-tier scored posts (magnitude_tier >= 2) from data/news_impact.json
  • recently-released economic events (actual != "pending") from ForexFactory

Run every ~5 minutes from Windows Task Scheduler:
    & "C:\\Users\\pornnatcha\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe" scripts\\realized_move_logger.py

Design:
  - Guarded MT5 init (terminal_info check) — safe to run while the live bot runs.
  - Pending markers persisted in data/realized_moves.json; horizons filled on
    subsequent runs when data becomes available (bot need not be alive at +60 m).
  - Atomic write (tmp + os.replace) to avoid serving a half-written JSON.
  - Idempotent: filled horizons are NEVER overwritten on re-run.
  - NO order calls, NO bot restarts, NO AI calls — read-only price access only.

Writes ONLY to:  data/realized_moves.json

Schema (ARCHITECTURE §4.4) is the ground truth consumed by M5/M6 calibration.
"""

import bisect
import json
import os
import sys
import time as _time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from loguru import logger
import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL

# ── File paths ────────────────────────────────────────────────────────────────

DATA_DIR            = ROOT / "data"
REALIZED_MOVES_PATH = DATA_DIR / "realized_moves.json"
NEWS_IMPACT_PATH    = DATA_DIR / "news_impact.json"

# ── Config ────────────────────────────────────────────────────────────────────

HORIZONS_MIN         = (5, 15, 60)   # minutes after anchor
FLAT_THRESHOLD_PCT   = 0.05          # |move_pct| < this → "flat"
HIGH_TIER_MIN        = 2             # magnitude_tier >= this to anchor a post
EVENT_LOOKBACK_HOURS = 24            # how far back to look for released events
MT5_SYMBOL           = SYMBOL        # inherited from config

# ForexFactory calendar URL (same as connectors/web_news.py)
_FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_HEADERS         = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_GOLD_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY", "CHF"}
_HIGH_IMPACTS    = {"High", "Medium"}


# ── MT5 helpers ───────────────────────────────────────────────────────────────

def init_mt5_guarded() -> bool:
    """Guarded MT5 init — safe for co-running with the live bot.

    Mirrors the pattern in scripts/score_trend_mode.py:36 and
    scripts/report_ride_cohort.py:84 (confirmed by ARCHITECTURE §D5):
      if mt5.terminal_info() is not None: already connected, skip initialize.
    Does NOT call mt5.shutdown() first (unlike connectors/price_feed.connect_mt5
    which would disturb the live bot's IPC connection).
    """
    try:
        if mt5.terminal_info() is not None:
            return True
        ok = mt5.initialize(
            login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER,
            timeout=15000,
        )
        if not ok:
            logger.error(f"MT5 init failed: {mt5.last_error()}")
        return ok
    except Exception as e:
        logger.error(f"MT5 init exception: {e}")
        return False


def price_at(ts_utc: datetime, symbol: str = MT5_SYMBOL) -> "float | None":
    """Return the open of the first M1 bar at or after ts_utc.

    ⚠️ Timezone is load-bearing (ARCHITECTURE §3.4):
      MT5 bar/tick .time is broker SERVER time (≈UTC+2 in winter, UTC+3
      during DST), NOT a true UTC epoch. The offset is computed LIVE per run
      from symbol_info_tick().time vs utcnow(), so it tracks DST transitions
      automatically without any hardcoded offset.

    Offset derivation:
        broker_offset_sec = tick.time - int(time.time())
        # tick.time is stored as broker-local epoch (e.g. +7200 ahead of UTC);
        # int(time.time()) is the true UTC epoch.
        # So broker_offset_sec ≈ +7200 (UTC+2) or +10800 (UTC+3).

    target_broker = ts_epoch + broker_offset_sec converts the UTC event time to
    the equivalent broker-local epoch, which matches bar.time values stored by MT5.

    Pattern reused from scripts/score_trend_mode.py:47 (copy_rates_range with
    naive datetimes = broker-local time, confirmed by ARCHITECTURE §3.4).

    Returns None if MT5 data unavailable — caller retries on the next run.
    """
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None

        # Live broker offset — positive means broker clock is ahead of UTC.
        # e.g. UTC+2 → broker_offset_sec ≈ +7200
        utcnow_epoch      = int(_time.time())
        broker_offset_sec = int(tick.time) - utcnow_epoch

        # F-06 guard: tick.time is FROZEN at the last quote, so when the market is
        # closed (weekend/holiday) this offset is garbage (large negative). MT5 gold
        # brokers sit at UTC+2/+3. Reject anything outside a sane tz band and leave
        # the anchor pending — never freeze a wrong price into calibration ground truth.
        if not (0 <= broker_offset_sec <= 4 * 3600):
            logger.debug(f"price_at: implausible broker offset {broker_offset_sec}s "
                         "(stale tick / market closed) — skip, retry next run")
            return None

        # Normalise ts_utc to UTC epoch
        if ts_utc.tzinfo is not None:
            ts_epoch = int(ts_utc.timestamp())
        else:
            # Treat naive datetime as UTC (defensive)
            ts_epoch = int(ts_utc.replace(tzinfo=timezone.utc).timestamp())

        # Translate to broker-local epoch (what MT5 stores in bar.time)
        target_broker_epoch = ts_epoch + broker_offset_sec

        # Query ±2-min window around target; MT5 copy_rates_range expects
        # naive datetimes in broker-local time (matches score_trend_mode.py:47)
        dt_start = datetime.fromtimestamp(target_broker_epoch - 120)
        dt_end   = datetime.fromtimestamp(target_broker_epoch + 120)

        mt5.symbol_select(symbol, True)
        bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, dt_start, dt_end)
        if bars is None or len(bars) == 0:
            return None

        bar_times = [int(b["time"]) for b in bars]
        # bisect_right gives the first index strictly after target_broker_epoch
        # (first bar that opened after the target moment — per ARCHITECTURE §3.4)
        i = bisect.bisect_right(bar_times, target_broker_epoch)
        # F-06: if no bar opened AT/AFTER the target within the ±2-min window, the
        # moment isn't covered (gap/closed) — return None and retry, do NOT clamp to
        # an earlier bar (that would freeze a stale price as the realized anchor).
        if i >= len(bars):
            return None

        return float(bars[i]["open"])

    except Exception as e:
        logger.debug(f"price_at({ts_utc!r}): {e}")
        return None


# ── Anchor collectors ─────────────────────────────────────────────────────────

def collect_post_anchors() -> list:
    """Load high-tier post anchors (magnitude_tier >= HIGH_TIER_MIN) from
    data/news_impact.json. Returns [] if file absent or on any error.
    """
    try:
        with open(NEWS_IMPACT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        anchors = []
        for post in data.get("posts", []):
            tier = post.get("magnitude_tier") or 0
            if tier < HIGH_TIER_MIN:
                continue
            anchors.append({
                "anchor_id":     f"post:{post['post_id']}",
                "kind":          "post",
                "subtype":       post.get("source", "tweet"),
                "anchor_ts_utc": post["ts_utc"],
                "pred": {
                    "magnitude_tier": tier,
                    "direction":      post.get("direction"),
                    "surprise_pct":   None,
                },
            })
        return anchors
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning(f"collect_post_anchors: {e}")
        return []


def _fetch_ff_raw() -> list:
    """Fetch the current-week ForexFactory JSON directly. Returns [] on error."""
    try:
        req = urllib.request.Request(_FF_CALENDAR_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"FF calendar fetch failed: {e}")
        return []


def collect_event_anchors(lookback_hours: int = EVENT_LOOKBACK_HOURS) -> list:
    """Collect recently-released economic event anchors from ForexFactory.

    Only includes events that:
      - Are for a gold-relevant currency (_GOLD_CURRENCIES)
      - Are high/medium impact
      - Have a non-empty actual value (not "pending")
      - Occurred within the last lookback_hours
    """
    anchors = []
    try:
        events = _fetch_ff_raw()
        now_utc  = datetime.now(timezone.utc)
        cutoff   = now_utc - timedelta(hours=lookback_hours)

        for ev in events:
            if ev.get("country", "").upper() not in _GOLD_CURRENCIES:
                continue
            if ev.get("impact", "") not in _HIGH_IMPACTS:
                continue

            actual = (ev.get("actual") or "").strip()
            if not actual or actual.lower() in ("pending", ""):
                continue

            date_str = ev.get("date", "")
            try:
                if "T" in date_str:
                    event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                else:
                    event_dt = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Only events released within the lookback window
            if not (cutoff <= event_dt <= now_utc):
                continue

            title       = ev.get("title", "")
            title_upper = title.upper()
            if "CPI" in title_upper:
                subtype = "CPI"
            elif any(k in title_upper for k in ("NON-FARM", "NONFARM", "NFP")):
                subtype = "NFP"
            elif any(k in title_upper for k in ("FOMC", "FEDERAL OPEN")):
                subtype = "FOMC"
            else:
                subtype = title[:20]

            ts_iso    = event_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            anchor_id = f"{subtype}-{ts_iso[:16]}"

            anchors.append({
                "anchor_id":     anchor_id,
                "kind":          "economic",
                "subtype":       subtype,
                "anchor_ts_utc": ts_iso,
                "pred": {
                    "magnitude_tier": None,
                    "direction":      None,
                    "surprise_pct":   None,
                },
            })
    except Exception as e:
        logger.warning(f"collect_event_anchors: {e}")
    return anchors


# ── Record persistence ────────────────────────────────────────────────────────

def load_records() -> list:
    """Load existing records from data/realized_moves.json. Returns [] if absent."""
    try:
        with open(REALIZED_MOVES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("records", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning(f"load_records: {e}")
        return []


def save_records(records: list) -> None:
    """Atomically write records to data/realized_moves.json (tmp + os.replace).

    Atomic write prevents dashboard or M5/M6 readers from seeing a half-written
    file (per ARCHITECTURE §D8 / §5 note 4).
    """
    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records": records,
    }
    tmp_path = REALIZED_MOVES_PATH.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, REALIZED_MOVES_PATH)
    logger.debug(f"Saved {len(records)} records to {REALIZED_MOVES_PATH.name}")


# ── Utility ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO-8601 UTC string to a timezone-aware datetime."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


# ── Core resolution logic ─────────────────────────────────────────────────────

def add_new_anchors(records: list, candidates: list) -> tuple:
    """Add new anchor records for candidates not yet tracked.

    Captures anchor_price via price_at(anchor_ts_utc).
    Returns (updated_records, n_added).
    """
    existing_ids = {r["anchor_id"] for r in records}
    n_added      = 0
    now_utc      = datetime.now(timezone.utc)

    for cand in candidates:
        if cand["anchor_id"] in existing_ids:
            continue

        anchor_ts = _parse_ts(cand["anchor_ts_utc"])
        # Skip future events — no price to anchor against yet
        if anchor_ts > now_utc + timedelta(minutes=1):
            continue

        anchor_price = price_at(anchor_ts)

        record = {
            "anchor_id":     cand["anchor_id"],
            "kind":          cand["kind"],
            "subtype":       cand["subtype"],
            "anchor_ts_utc": cand["anchor_ts_utc"],
            "anchor_price":  round(anchor_price, 2) if anchor_price is not None else None,
            "moves":         {},
            "realized_dir":  None,
            "pred":          cand["pred"],
        }
        records.append(record)
        existing_ids.add(cand["anchor_id"])
        n_added += 1
        logger.info(
            f"New anchor: {cand['anchor_id']} at {cand['anchor_ts_utc']} "
            f"anchor_price={anchor_price}"
        )

    return records, n_added


def resolve_pending(records: list) -> tuple:
    """Fill matured but unfilled horizons using historical M1 bars.

    Idempotent: a horizon with an existing non-None price is NEVER overwritten.
    Returns (updated_records, n_fills_this_run).
    """
    now_utc = datetime.now(timezone.utc)
    n_fills = 0

    for rec in records:
        anchor_ts = _parse_ts(rec["anchor_ts_utc"])
        moves     = rec.setdefault("moves", {})

        for h in HORIZONS_MIN:
            h_key     = str(h)
            existing  = moves.get(h_key, {})
            if existing.get("price") is not None:
                continue  # already filled — idempotent

            target_ts = anchor_ts + timedelta(minutes=h)
            if now_utc < target_ts:
                continue  # horizon has not matured yet

            price = price_at(target_ts)
            if price is None:
                continue  # bar unavailable — will retry next run

            anchor_price = rec.get("anchor_price")
            if anchor_price is not None and anchor_price > 0:
                move_pct = round((price - anchor_price) / anchor_price * 100, 4)
                move_abs = round(price - anchor_price, 2)
            else:
                move_pct = None
                move_abs = None

            moves[h_key] = {
                "price":     round(price, 2),
                "move_pct":  move_pct,
                "move_abs":  move_abs,
                "logged_at": _now_iso(),
            }
            n_fills += 1
            logger.info(
                f"Filled {rec['anchor_id']} +{h}m: "
                f"price={price:.2f}  move_pct={move_pct}%"
            )

        # Derive realized_dir from 60-min move (overwrite on each pass so it
        # gets set as soon as the 60m horizon is filled)
        sixty = moves.get("60", {})
        if sixty.get("move_pct") is not None:
            mp = sixty["move_pct"]
            if mp > FLAT_THRESHOLD_PCT:
                rec["realized_dir"] = "up"
            elif mp < -FLAT_THRESHOLD_PCT:
                rec["realized_dir"] = "down"
            else:
                rec["realized_dir"] = "flat"

    return records, n_fills


# ── Main entry point ──────────────────────────────────────────────────────────

def run() -> None:
    """Collect → add new anchors → resolve pending horizons → save if changed.

    Fully guarded: any exception is caught and logged; the script never raises
    into the caller so a Task Scheduler run cannot crash the broader environment.
    """
    if not init_mt5_guarded():
        logger.error("realized_move_logger: MT5 unavailable — aborting run")
        return

    try:
        # 1. Load persisted state
        records = load_records()

        # 2. Collect anchor candidates from both sources
        candidates = collect_post_anchors() + collect_event_anchors()

        # 3. Register new anchors (capture anchor_price)
        records, n_added = add_new_anchors(records, candidates)

        # 4. Fill matured horizons from historical M1 bars
        records, n_fills = resolve_pending(records)

        # 5. Persist only when something changed
        if n_added > 0 or n_fills > 0:
            save_records(records)
            logger.info(
                f"realized_move_logger: +{n_added} anchors  +{n_fills} fills  "
                f"total={len(records)} records"
            )
        else:
            logger.debug("realized_move_logger: nothing new this run")

    except Exception as e:
        # Fail-soft: log but never propagate so Task Scheduler does not report
        # a crash that would look like a bot issue
        logger.error(f"realized_move_logger run() exception: {e}")


if __name__ == "__main__":
    run()
