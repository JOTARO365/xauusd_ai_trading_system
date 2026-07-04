"""
report_burn.py — คำนวณ AI token burn (฿/วัน) เทียบเป้า 150-250฿
  อ่านจาก agent_usage ผ่าน db/reader pattern (ใช้ Supabase client โดยตรง)
  เขียน data/burn_daily.json ตาม ARCHITECTURE §3.4 / §3.6

รัน: & $PY scripts\report_burn.py [--days N]
ไม่มี AI call ทั้งสิ้น — display-only, ไม่กระทบ token burn
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

TARGET_MIN = 150.0   # ฿/day
TARGET_MAX = 250.0   # ฿/day

# ─── USD → THB ────────────────────────────────────────────────────────────────
# ใช้ pattern เดียวกับ get_usd_thb() ใน dashboard/app.py (Yahoo Finance, fallback 33.0)

def _get_usd_thb() -> float:
    """ดึงอัตราแลกเปลี่ยน USD/THB จาก Yahoo Finance, fallback 33.0"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/USDTHB=X?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read())
        rate = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return round(float(rate), 4)
    except Exception:
        return 33.0


# ─── DB query ─────────────────────────────────────────────────────────────────

def _fetch_daily_cost_usd(days: int) -> dict:
    """คืน dict {date_str: total_cost_usd} สำหรับ N วันที่ผ่านมา (รวมวันนี้)"""
    from db.connection import get_client
    client = get_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (
        client.table("agent_usage")
        .select("cycle_at,cost_usd")
        .gte("cycle_at", cutoff)
        .execute()
    )
    rows = res.data or []

    daily: dict = {}
    for r in rows:
        raw = r.get("cycle_at") or ""
        day_key = raw[:10]
        if not day_key:
            continue
        cost = float(r.get("cost_usd") or 0)
        daily[day_key] = daily.get(day_key, 0.0) + cost

    return daily


# ─── Build payload ────────────────────────────────────────────────────────────

def build_payload(days: int = 14) -> dict:
    """คำนวณ payload §3.4"""
    usd_thb = _get_usd_thb()
    daily_usd = _fetch_daily_cost_usd(days)

    today_str = datetime.now(timezone.utc).date().isoformat()

    def _vs(thb: float) -> str:
        if thb < TARGET_MIN:
            return "under"
        if thb > TARGET_MAX:
            return "over"
        return "in"

    # เรียงวันจากเก่าไปใหม่
    sorted_days = sorted(daily_usd.keys())
    day_list = []
    for d in sorted_days:
        thb = round(daily_usd[d] * usd_thb, 2)
        day_list.append({
            "date":       d,
            "thb":        thb,
            "vs_target":  _vs(thb),
        })

    today_thb = round(daily_usd.get(today_str, 0.0) * usd_thb, 2)

    return {
        "ok":         True,
        "target_min": TARGET_MIN,
        "target_max": TARGET_MAX,
        "days":       day_list,
        "today_thb":  today_thb,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Compute daily AI burn in THB")
    parser.add_argument("--days", type=int, default=14,
                        help="Number of past days to include (default: 14)")
    args = parser.parse_args()

    print(f"Fetching agent_usage for last {args.days} days…")
    payload = build_payload(days=args.days)

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "burn_daily.json")
    out_path = os.path.normpath(out_path)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Written → {out_path}")
    print(f"USD/THB used     : (fetched live)")
    print(f"Today burn       : {payload['today_thb']:.2f} ฿")
    print(f"Days computed    : {len(payload['days'])}")

    if payload["days"]:
        print("\nRecent days (newest last):")
        for d in payload["days"][-7:]:
            bar = "[IN ]" if d["vs_target"] == "in" else ("[OVER]" if d["vs_target"] == "over" else "[    ]")
            print(f"  {d['date']}  {d['thb']:7.2f} ฿  {bar}")


if __name__ == "__main__":
    main()
