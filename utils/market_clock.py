"""
คำนวณ interval รอบถัดไปตามสภาพตลาด XAUUSD
สูงสุด 600 วิ (นิ่ง) / ต่ำสุด 60 วิ (ร้อนแรง)
รวม market_sleep_status() สำหรับตรวจว่าตลาดปิดอยู่หรือไม่
"""
import os
from datetime import datetime, timezone, timedelta


# ─── Market close/open windows (UTC) ─────────────────────────
MARKET_CLOSE_UTC       = int(os.getenv("MARKET_CLOSE_UTC",       21))  # 21 UTC = ตี4 BKK (daily/Friday close)
MARKET_OPEN_UTC        = int(os.getenv("MARKET_OPEN_UTC",        22))  # 22 UTC = ตี5 BKK (Mon–Thu reopen)
MARKET_OPEN_SUNDAY_UTC = int(os.getenv("MARKET_OPEN_SUNDAY_UTC", 22))  # 22 UTC = ตี5 BKK Monday (Sunday open)


def _next_dt_utc(now: datetime, target_weekday: int, hour: int) -> datetime:
    """คืน datetime UTC ของ target_weekday ถัดไปที่ชั่วโมง hour:00"""
    days_ahead = (target_weekday - now.weekday()) % 7 or 7
    return (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def market_sleep_status() -> tuple[bool, int, str]:
    """
    ตรวจว่าควรหยุดรอหรือไม่

    Returns
    -------
    should_sleep : bool
    sleep_secs   : int   — วินาทีที่ควรรอ (0 ถ้า should_sleep=False)
    reason       : str
    """
    now = datetime.now(timezone.utc)
    wd, h = now.weekday(), now.hour  # 0=Mon … 6=Sun

    # วันเสาร์ทั้งวัน → รอถึงอาทิตย์ MARKET_OPEN_SUNDAY_UTC
    if wd == 5:
        wake = _next_dt_utc(now, 6, MARKET_OPEN_SUNDAY_UTC)
        secs = max(0, int((wake - now).total_seconds()))
        return True, secs, f"วันเสาร์ — ตลาดปิดสุดสัปดาห์ (เปิด อา. {MARKET_OPEN_SUNDAY_UTC:02d}:00 UTC)"

    # วันอาทิตย์ก่อนเปิด → รอถึง MARKET_OPEN_SUNDAY_UTC วันเดียวกัน
    if wd == 6 and h < MARKET_OPEN_SUNDAY_UTC:
        wake = now.replace(hour=MARKET_OPEN_SUNDAY_UTC, minute=0, second=0, microsecond=0)
        secs = max(0, int((wake - now).total_seconds()))
        return True, secs, f"วันอาทิตย์ ตลาดยังไม่เปิด (เปิด {MARKET_OPEN_SUNDAY_UTC:02d}:00 UTC)"

    # วันศุกร์ ≥ MARKET_CLOSE_UTC → ปิดสุดสัปดาห์
    if wd == 4 and h >= MARKET_CLOSE_UTC:
        wake = _next_dt_utc(now, 6, MARKET_OPEN_SUNDAY_UTC)
        secs = max(0, int((wake - now).total_seconds()))
        return True, secs, f"ปิดสุดสัปดาห์ (ศุกร์ {MARKET_CLOSE_UTC:02d}:00+ UTC)"

    # จันทร์–พฤหัส ช่วง daily close → รอถึง MARKET_OPEN_UTC:05
    if wd <= 3 and h == MARKET_CLOSE_UTC:
        wake = now.replace(hour=MARKET_OPEN_UTC, minute=5, second=0, microsecond=0)
        if wake <= now:
            wake += timedelta(days=1)
        secs = max(0, int((wake - now).total_seconds()))
        return True, secs, f"Daily close {MARKET_CLOSE_UTC:02d}:00–{MARKET_OPEN_UTC:02d}:05 UTC"

    return False, 0, ""


# ─── ช่วงเวลาตลาด (UTC) ───────────────────────────────────────
# XAUUSD เคลื่อนไหวมากสุดช่วง London/NY overlap
SESSIONS = {
    "asian_quiet":  (0,  7),    # 07:00-14:00 BKK — สงบมาก
    "london_open":  (7,  10),   # 14:00-17:00 BKK — เริ่มคึกคัก
    "london":       (10, 13),   # 17:00-20:00 BKK — London กลาง
    "overlap":      (13, 17),   # 20:00-00:00 BKK — ร้อนแรงสุด
    "ny_close":     (17, 21),   # 00:00-04:00 BKK — NY ปิด
    "dead_zone":    (21, 24),   # 04:00-07:00 BKK — เงียบมาก
}

# ชั่วโมง UTC ที่มักมีข่าว high-impact (US economic releases, Fed)
HIGH_IMPACT_HOURS_UTC = {8, 9, 13, 14, 15, 18, 19}


def _session_score(hour_utc: int) -> tuple[int, str]:
    """คืน (score, session_name) ตามชั่วโมง UTC"""
    if 13 <= hour_utc < 17:
        return 4, "London/NY Overlap"
    if 7 <= hour_utc < 10:
        return 3, "London Open"
    if 10 <= hour_utc < 13:
        return 2, "London"
    if 17 <= hour_utc < 21:
        return 2, "New York"
    if 21 <= hour_utc < 24:
        return 0, "NY Close (quiet)"
    return -1, "Asian (quiet)"


def next_interval(chart_data: dict, sentiment_data: dict,
                  htf_zone: dict | None = None) -> tuple[int, str]:
    """
    คำนวณ interval รอบถัดไปเป็นวินาที

    Returns
    -------
    interval : int   — วินาที (60 / 120 / 180 / 300 / 600)
    reason   : str   — เหตุผล
    """
    now_utc  = datetime.now(timezone.utc)
    hour_utc = now_utc.hour

    reasons: list[str] = []
    score = 0

    # ── 1. Market session ─────────────────────────────────
    s_score, s_name = _session_score(hour_utc)
    score += s_score
    reasons.append(s_name)

    # ── 2. Near high-impact news time ────────────────────
    if hour_utc in HIGH_IMPACT_HOURS_UTC:
        score += 2
        reasons.append(f"ช่วงข่าว {hour_utc:02d}:xx UTC")

    # ── 3. ATR สูง = ตลาดเคลื่อนไหวมาก ──────────────────
    h4_atr = chart_data.get("indicators", {}).get("h4", {}).get("atr", 0)
    if h4_atr > 30:
        score += 3
        reasons.append(f"ATR สูงมาก ({h4_atr:.1f})")
    elif h4_atr > 20:
        score += 1
        reasons.append(f"ATR สูง ({h4_atr:.1f})")

    # ── 4. Price action signal ────────────────────────────
    sr_actions = chart_data.get("sr_actions", [])
    if sr_actions:
        score += 2
        actions_str = "/".join(a["action"] for a in sr_actions[:2])
        reasons.append(f"PA: {actions_str}")

    # ── 5. Entry setup confluence ─────────────────────────
    scan = chart_data.get("scan", {})
    conf = scan.get("confluence_count", 0)
    if conf >= 3:
        score += 2
        reasons.append(f"{conf} setups")
    elif conf >= 2:
        score += 1
        reasons.append(f"{conf} setups")

    # ── 6. Active news ────────────────────────────────────
    tweet_count = sentiment_data.get("tweet_count", 0)
    if tweet_count >= 10:
        score += 2
        reasons.append(f"ข่าว {tweet_count} รายการ")
    elif tweet_count >= 5:
        score += 1
        reasons.append(f"ข่าว {tweet_count} รายการ")

    # ── 7. M15 Momentum (ตลาดวิ่งแรง → ลด interval ทันที) ──
    mom_tf  = chart_data.get("momentum_tf", {})
    mom_m15 = mom_tf.get("m15", {})
    mom_h1  = mom_tf.get("h1", {})
    if mom_m15.get("strength") == "STRONG":
        h1_aligned = mom_h1.get("direction") == mom_m15.get("direction")
        if h1_aligned:
            score += 4
            reasons.append(f"momentum แรง M15+H1 ({mom_m15.get('direction', '')})")
        else:
            score += 2
            reasons.append(f"momentum แรง M15 ({mom_m15.get('direction', '')})")

    # ── HTF zone: ลด interval ทันที (อยู่ที่ D1/W1 = ต้องดูใกล้ชิด) ─
    if htf_zone:
        score += 5
        reasons.append(f"⚡ HTF {htf_zone['tf']} zone ({htf_zone['dist_pct']}%)")

    # ── Map score → interval ──────────────────────────────
    #   score ≥ 9  → 60s   (ร้อนแรงมาก)
    #   score 7-8  → 120s  (ร้อนแรง)
    #   score 5-6  → 180s  (ค่อนข้างคึกคัก)
    #   score 3-4  → 300s  (ปกติ)
    #   score ≤ 2  → 600s  (เงียบ)
    if score >= 9:
        interval = 60
    elif score >= 7:
        interval = 120
    elif score >= 5:
        interval = 180
    elif score >= 3:
        interval = 300
    else:
        interval = 600

    # Bangkok time สำหรับแสดงผล
    bkk_hour = (hour_utc + 7) % 24
    reason_str = f"{', '.join(reasons)}  [{bkk_hour:02d}:{now_utc.minute:02d} BKK]"
    return interval, reason_str
