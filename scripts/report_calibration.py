"""
report_calibration.py — confidence calibration: predicted conf bin -> realized win-rate
  Reads CLOSED trades from DB (read-only, Supabase client, same pattern as report_burn.py)
  Writes data/calibration.json per ARCHITECTURE §3.5 / §3.6

Run: & $PY scripts\report_calibration.py
Zero AI calls — display-only, does NOT affect token burn.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

# ─── Bin definitions ──────────────────────────────────────────────────────────
# 5-point bins, as specified in ARCHITECTURE §3.5 example (60-64, 65-69, ...)
# Range 55-100 to catch all practical confidence values the system emits.
_BIN_STARTS = list(range(55, 100, 5))   # [55, 60, 65, 70, 75, 80, 85, 90, 95]
_BINS = [(lo, lo + 4) for lo in _BIN_STARTS] + [(100, 100)]


def _bin_index(conf: int) -> int | None:
    """Return the bin index for a given confidence value, or None if out of range."""
    for i, (lo, hi) in enumerate(_BINS):
        if lo <= conf <= hi:
            return i
    return None


# ─── DB query ─────────────────────────────────────────────────────────────────

def _fetch_closed_trades() -> list[dict]:
    """Fetch all CLOSED trades that have both technical_confidence and pnl set.
    Uses direct Supabase client (read-only) — same pattern as report_burn.py."""
    from db.connection import get_client
    client = get_client()

    res = (
        client.table("trades")
        .select("technical_confidence,pnl")
        .eq("status", "CLOSED")
        .execute()
    )
    rows = res.data or []
    # Filter NULL values in Python (safest across supabase-py versions)
    return [
        r for r in rows
        if r.get("technical_confidence") is not None and r.get("pnl") is not None
    ]


# ─── Build payload ────────────────────────────────────────────────────────────

def build_payload() -> dict:
    """Compute calibration payload matching ARCHITECTURE §3.5 schema."""
    rows = _fetch_closed_trades()

    # Accumulator per bin: [n, n_win, pnl_sum]
    acc: dict[int, list] = {i: [0, 0, 0.0] for i in range(len(_BINS))}

    for r in rows:
        raw_conf = r.get("technical_confidence")
        raw_pnl  = r.get("pnl")
        if raw_conf is None or raw_pnl is None:
            continue
        try:
            conf = int(raw_conf)
            pnl  = float(raw_pnl)
        except (ValueError, TypeError):
            continue

        idx = _bin_index(conf)
        if idx is None:
            continue

        acc[idx][0] += 1          # n
        acc[idx][2] += pnl        # pnl_sum
        if pnl > 0:
            acc[idx][1] += 1      # n_win

    # Build result bins — only emit bins with n > 0
    result_bins = []
    for i, (lo, hi) in enumerate(_BINS):
        n, n_win, pnl_sum = acc[i]
        if n == 0:
            continue
        result_bins.append({
            "conf_lo": lo,
            "conf_hi": hi,
            "n":       n,
            "wr":      round(n_win / n, 4),
            "pnl":     round(pnl_sum, 2),
        })

    return {
        "ok":      True,
        "bins":    result_bins,
        "suggestion": _build_suggestion(result_bins),
        "updated": datetime.now(timezone.utc).isoformat(),
    }


# ─── Conf-floor suggestion (ADVISORY — never changes the gate) ─────────────────

_SUGGEST_MIN_N = 30   # pre-registered min sample per project convention


def _build_suggestion(bins: list[dict]) -> dict:
    """From realized calibration, suggest a MIN_TECH_CONF floor by asking, for each
    candidate floor F: 'if we only traded conf >= F, what was the realized EV/trade?'
    Suggests the floor maximizing EV/trade (with an n>=30 guard). ADVISORY ONLY —
    the caller/dashboard never auto-applies it; the user sets it manually in Settings.
    Honest edge cases: too little data -> insufficient; no floor profitable ->
    the conf threshold is not the problem."""
    current = int(os.getenv("MIN_TECH_CONF") or 62)
    total_n = sum(b["n"] for b in bins)
    base = {"current_floor": current, "suggested_floor": None, "min_n": _SUGGEST_MIN_N,
            "total_n": total_n, "floors": [], "status": "insufficient", "note": ""}
    if total_n < _SUGGEST_MIN_N:
        base["note"] = f"ข้อมูลไม่พอ (n={total_n} < {_SUGGEST_MIN_N}) — ยังไม่แนะนำ"
        return base

    # Cumulative stats for each floor = sum of bins with conf_lo >= F.
    floors = sorted({b["conf_lo"] for b in bins})
    rows = []
    for f in floors:
        sel = [b for b in bins if b["conf_lo"] >= f]
        n   = sum(b["n"] for b in sel)
        wins = sum(round(b["wr"] * b["n"]) for b in sel)
        pnl = sum(b["pnl"] for b in sel)
        rows.append({"floor": f, "n": n,
                     "wr": round(wins / n, 4) if n else 0.0,
                     "pnl": round(pnl, 2),
                     "mean_pnl": round(pnl / n, 2) if n else 0.0})
    base["floors"] = rows

    eligible = [r for r in rows if r["n"] >= _SUGGEST_MIN_N]
    if not eligible:
        base["status"] = "insufficient"
        base["note"] = f"ทุก floor มีตัวอย่าง < {_SUGGEST_MIN_N} — ยังไม่แนะนำ"
        return base

    best = max(eligible, key=lambda r: r["mean_pnl"])
    if best["mean_pnl"] <= 0:
        base["status"] = "no_profitable_floor"
        base["note"] = ("ไม่มี conf floor ไหนที่ EV/ไม้ เป็นบวก → ปัญหาไม่ใช่ค่า conf "
                        "(อย่าดันขึ้นเฉยๆ) ควรดู exit/สภาพตลาดแทน")
        return base

    base["suggested_floor"] = best["floor"]
    ev = f"EV จริง {best['mean_pnl']:+.1f}฿/ไม้ ที่ conf≥{best['floor']} (n={best['n']}, WR {best['wr']*100:.0f}%)"
    # Bins are 5 wide, so a peak within one bin of the current floor is noise, not a
    # signal — don't nudge the gate on it (especially not to LOWER it).
    if abs(best["floor"] - current) < 5:
        base["status"] = "ok_keep"
        base["note"] = (f"floor ปัจจุบัน ({current}) เหมาะสมแล้ว — EV peak อยู่ band เดียวกัน "
                        f"({ev}). ไม่ต้องปรับ")
    elif best["floor"] > current:
        base["status"] = "suggest_raise"
        base["note"] = (f"พิจารณาขึ้น MIN_TECH_CONF {current} → {best['floor']} — {ev}. "
                        "คำแนะนำเท่านั้น ตั้งเองใน Settings, ระบบไม่เปลี่ยน gate อัตโนมัติ")
    else:
        base["status"] = "suggest_lower_cautious"
        base["note"] = (f"EV peak อยู่ที่ conf≥{best['floor']} (ต่ำกว่า floor ปัจจุบัน {current}) — "
                        f"{ev}. การลด floor = เทรดถี่ขึ้น เสี่ยงขึ้น พิจารณาระวัง ไม่แนะนำอัตโนมัติ")
    return base


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Fetching closed trades for confidence calibration...")
    payload = build_payload()

    out_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "calibration.json")
    )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Written -> {out_path}")
    print(f"Updated            : {payload['updated']}")
    print(f"Total bins (n > 0) : {len(payload['bins'])}")

    if payload["bins"]:
        total_n = sum(b["n"] for b in payload["bins"])
        print(f"\nCalibration ({total_n} closed trades with confidence):")
        print(f"  {'Bin':^7}  {'n':>5}  {'WR%':>7}  {'PnL':>10}  Verdict")
        for b in payload["bins"]:
            lo, hi      = b["conf_lo"], b["conf_hi"]
            mid_pred    = (lo + hi) / 2          # predicted WR (midpoint)
            wr_pct      = b["wr"] * 100
            verdict     = "OVER" if wr_pct >= mid_pred else "UNDER"
            print(
                f"  {lo:>3}-{hi:<3}  {b['n']:>5}  {wr_pct:>6.1f}%"
                f"  {b['pnl']:>10.2f}  {verdict} (pred {mid_pred:.0f}%)"
            )
    else:
        print("\nNo closed trades with technical_confidence found in DB.")
        print("(The bot must close trades that include AI confidence scores)")


if __name__ == "__main__":
    main()
