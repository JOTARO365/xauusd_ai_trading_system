"""Event-Reaction Stats — สถิติทองตอบสนองต่อ high-impact event (แบบ HAS Terminal #10)

คำนวณจาก data/xau_daily.json (AlphaVantage daily) → เขียน data/event_stats.json
ให้ analyst ฉีดเป็น prior เข้า context วันมี event (agents/analyst.py)

MVP: NFP (วันประกาศ = ศุกร์แรกของเดือน; ถ้าตรง 4 ก.ค. เลื่อนเป็นพฤหัส)
⚠️ ข้อจำกัดที่รู้: (1) วันประกาศเป็น rule-based ~95% ตรง (BLS เลื่อนเป็นศุกร์ที่สอง
ได้ในบางเดือน) (2) ใช้ daily close = จับ reaction ระดับวัน ไม่ใช่ intraday
(3) ยังไม่มี beat/miss conditional — ต้องมี consensus history (Phase 2)

รัน: python scripts/event_reaction_stats.py   (refresh เดือนละครั้งพอ แล้ว commit)
"""
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
DAILY_PATH = ROOT / "data" / "xau_daily.json"
OUT_PATH   = ROOT / "data" / "event_stats.json"

FLAT_PCT = 0.05   # |return| <= นี้ = "flat" (สอดคล้องสัดส่วน flat ~5% ของ UHAS)


def _load_daily() -> tuple[list[str], dict[str, float]]:
    raw = json.loads(DAILY_PATH.read_text(encoding="utf-8"))
    rows = raw["data"]
    dates = [r["date"] for r in rows]
    prices = {r["date"]: float(r["price"]) for r in rows}
    return dates, prices


def _first_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)   # weekday 4 = Friday
    return d


def nfp_release_dates(start: date, end: date) -> list[date]:
    """ศุกร์แรกของเดือน; ตรง 4 ก.ค. → เลื่อนเป็นพฤหัส (เช่น 2026-07-02)"""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        d = _first_friday(y, m)
        if m == 7 and d.day == 4:
            d -= timedelta(days=1)
        if start <= d <= end:
            out.append(d)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _reaction(dates: list[str], prices: dict[str, float], release: date):
    """คืน (ret_day0, cum_d1, cum_d2) เป็น % — base = close วันเทรดก่อนประกาศ.
    day0 = วันเทรดแรก >= วันประกาศ (กันวันหยุด). คืน None ถ้าข้อมูลไม่พอ"""
    iso = release.isoformat()
    import bisect
    i0 = bisect.bisect_left(dates, iso)
    if i0 <= 0 or i0 + 2 >= len(dates):
        return None
    base = prices[dates[i0 - 1]]
    if base <= 0:
        return None
    r0 = (prices[dates[i0]] / base - 1) * 100
    r1 = (prices[dates[i0 + 1]] / base - 1) * 100
    r2 = (prices[dates[i0 + 2]] / base - 1) * 100
    return round(r0, 3), round(r1, 3), round(r2, 3)


def compute_nfp(dates: list[str], prices: dict[str, float]) -> dict:
    start = date.fromisoformat(dates[0]) + timedelta(days=35)
    end   = date.fromisoformat(dates[-1])
    releases = nfp_release_dates(start, end)
    rows = []
    for rel in releases:
        r = _reaction(dates, prices, rel)
        if r:
            rows.append({"release": rel.isoformat(), "d0": r[0], "d1": r[1], "d2": r[2]})

    d0s   = [r["d0"] for r in rows]
    ups   = [r for r in rows if r["d0"] > FLAT_PCT]
    downs = [r for r in rows if r["d0"] < -FLAT_PCT]
    n     = len(rows)
    # follow-through: ในบรรดาวันที่ day0 มีทิศ ทิศเดิมยังอยู่ที่ D+2 กี่ %
    cont = [r for r in ups if r["d2"] > r["d0"]] + [r for r in downs if r["d2"] < r["d0"]]
    directional = len(ups) + len(downs)

    return {
        "n": n,
        "window": f"{rows[0]['release']} .. {rows[-1]['release']}" if rows else "-",
        "up_pct":   round(len(ups) / n * 100, 1) if n else 0,
        "down_pct": round(len(downs) / n * 100, 1) if n else 0,
        "flat_pct": round((n - len(ups) - len(downs)) / n * 100, 1) if n else 0,
        "avg_d0_pct":     round(statistics.mean(d0s), 3) if d0s else 0,
        "median_d0_pct":  round(statistics.median(d0s), 3) if d0s else 0,
        "avg_abs_d0_pct": round(statistics.mean(abs(x) for x in d0s), 3) if d0s else 0,
        "avg_up_pct":   round(statistics.mean(r["d0"] for r in ups), 3) if ups else 0,
        "avg_down_pct": round(statistics.mean(r["d0"] for r in downs), 3) if downs else 0,
        "d2_extends_pct": round(len(cont) / directional * 100, 1) if directional else 0,
        "basis": "daily close, base = close วันเทรดก่อนประกาศ; วันประกาศ rule-based (first-Friday)",
        "flat_threshold_pct": FLAT_PCT,
    }


def _baseline_avg_abs(dates: list[str], prices: dict[str, float]) -> float:
    """avg |daily return| ของทุกวันเทรด — ไว้เทียบว่า event day ใหญ่กว่าปกติกี่เท่า"""
    rets = []
    for a, b in zip(dates, dates[1:]):
        pa, pb = prices[a], prices[b]
        if pa > 0:
            rets.append(abs(pb / pa - 1) * 100)
    return round(statistics.mean(rets), 3) if rets else 0.0


def main():
    dates, prices = _load_daily()
    baseline = _baseline_avg_abs(dates, prices)
    nfp = compute_nfp(dates, prices)
    nfp["vs_baseline_x"] = round(nfp["avg_abs_d0_pct"] / baseline, 2) if baseline else 0
    stats = {
        "updated": date.today().isoformat(),
        "source": "data/xau_daily.json (AlphaVantage daily)",
        "baseline_avg_abs_pct": baseline,
        "events": {"NFP": nfp},
    }
    OUT_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"baseline avg|daily move| = {baseline:.3f}% | NFP day = {nfp['vs_baseline_x']}x ของวันปกติ")
    print(f"NFP: n={nfp['n']} ({nfp['window']})")
    print(f"  release day: up {nfp['up_pct']}% / down {nfp['down_pct']}% / flat {nfp['flat_pct']}%")
    print(f"  avg {nfp['avg_d0_pct']:+.3f}% | avg|move| {nfp['avg_abs_d0_pct']:.3f}% "
          f"| avg up {nfp['avg_up_pct']:+.3f}% / down {nfp['avg_down_pct']:+.3f}%")
    print(f"  D+2 extends direction: {nfp['d2_extends_pct']}% of directional days")
    print(f"→ {OUT_PATH}")


if __name__ == "__main__":
    main()
