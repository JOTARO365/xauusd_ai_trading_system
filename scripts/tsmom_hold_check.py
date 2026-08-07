#!/usr/bin/env python
"""scripts/tsmom_hold_check.py — forward check: did TSMOM-D1 gold hold time jump to DAYS after the
intraday-exit-isolation fix (commit 15144e4, 2026-08-07)?

Before the fix the intraday exit stack closed TSMOM positions early (median hold ~1.2h). After it,
TSMOM should hold to the D1 signal flip (days). This splits the real gold fills by the fix timestamp
and reports n / median-hold / WR / PnL on each side so the edge repair is verifiable on live data.

Run: python scripts/tsmom_hold_check.py   (optionally: --cutoff 2026-08-07T01:44)
Read-only, 0 token.
"""
import glob
import json
import os
import statistics as st
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIX_UTC = "2026-08-07T01:44"          # fix commit (08:44 +07 = 01:44 UTC)


def _load():
    out = []
    for f in glob.glob(os.path.join(_ROOT, "logs", "real_fills", "tsmom_d1__*.jsonl")):
        b = os.path.basename(f)
        if "XAU" not in b and "GOLD" not in b:
            continue
        for ln in open(f, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def _hold_hours(r):
    if not (r.get("opened_ts") and r.get("closed_ts")):
        return None
    try:
        a = datetime.fromisoformat(r["opened_ts"]); b = datetime.fromisoformat(r["closed_ts"])
        return (b - a).total_seconds() / 3600
    except Exception:
        return None


def _report(tag, recs):
    if not recs:
        print(f"{tag:12s} n=0  (ยังไม่มีไม้)")
        return
    holds = [h for h in (_hold_hours(r) for r in recs) if h is not None]
    p = [r.get("profit", 0) or 0 for r in recs]
    wins = sum(1 for x in p if x > 0)
    med = st.median(holds) if holds else None
    med_txt = f"{med/24:.1f}d ({med:.1f}h)" if med is not None else "—"
    dirs = {}
    for r in recs:
        dirs[r.get("dir", "?")] = dirs.get(r.get("dir", "?"), 0) + 1
    print(f"{tag:12s} n={len(recs):3d}  median-hold={med_txt:16s}  WR={wins/len(recs)*100:4.1f}%  "
          f"PnL={sum(p):+8.0f}  dir={dirs}")


def main():
    cutoff = _FIX_UTC
    if "--cutoff" in sys.argv:
        cutoff = sys.argv[sys.argv.index("--cutoff") + 1]
    recs = _load()

    def _ts(r):
        return r.get("closed_ts") or r.get("opened_ts") or ""

    pre = [r for r in recs if _ts(r) < cutoff]
    post = [r for r in recs if _ts(r) >= cutoff]
    print(f"TSMOM-D1 gold hold check · fix cutoff = {cutoff}Z · now = {datetime.now(timezone.utc).isoformat()[:16]}Z")
    print("=" * 78)
    _report("PRE-fix", pre)
    _report("POST-fix", post)
    print("=" * 78)
    if not post:
        print("ยังไม่มีไม้หลัง fix → รอบอท restart (fix เป็น code) + เปิด/ปิดไม้ D1 ใหม่ (~วันละ 1, ถือหลายวัน).")
        print("เป้า: POST-fix median-hold ควรพุ่งจาก ~1.2h เป็นหน่วยวัน (ถือจน D1 flip).")
    elif len(post) < 3:
        print(f"POST-fix มีแค่ {len(post)} ไม้ — น้อยไป ยังสรุป median ไม่ได้ (รอ ≥5-8 ไม้).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
