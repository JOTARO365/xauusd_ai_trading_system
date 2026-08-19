#!/usr/bin/env python
"""scripts/btc_shadow_monitor.py — เฝ้าการสะสม BTC tsmom SHADOW data (forward, D1).

อ่าน daily mark-to-market tape (agents/shadow_tsmom.py → logs/shadow/tsmom__BTCUSD.jsonl) แล้วสรุป:
  - ช่วงวัน + จำนวนวันสะสม + สถานะ position ปัจจุบัน
  - reconstruct discrete trades (จับกลุ่ม pos ต่อเนื่อง) → per-trade return (raw + LONG-ONLY = ทิศ edge จริง)
  - progress ไปยัง n≥100 (ที่ deflated bar ต้องการ) + ETA คร่าวๆ ตาม rate
เอาไว้รันเช็คเป็นระยะว่า shadow เก็บถึงไหน พอ re-test (placebo+deflated) ยัง.

⚠️ D1 trend-follow = ~ไม่กี่ trade/ปี → forward-only ช้ามาก (ดู ETA). accelerator จริง = intraday CSV (H1/H4).
read-only · ไม่แตะ live/switch. รัน: python scripts/btc_shadow_monitor.py
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGDIR = os.path.join(_ROOT, "logs", "shadow")
TARGET_N = 100


def _load(name):
    p = os.path.join(LOGDIR, name)
    if not os.path.exists(p):
        return []
    out = []
    for ln in open(p, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def _trades_from_tape(rows):
    """จับกลุ่ม pos ต่อเนื่อง = 1 trade. per-trade return = sum(ret) ระหว่างถือ (ret เป็น % ต่อวัน มี sign แล้ว)."""
    trades = []
    cur_pos = 0; acc = 0.0; start = None; days = 0
    for r in rows:
        pos = r.get("pos") or 0
        ret = r.get("ret")
        if pos != cur_pos:
            if cur_pos != 0 and start is not None:
                trades.append({"pos": cur_pos, "ret": acc, "days": days, "start": start, "end": r.get("ts")})
            cur_pos = pos; acc = 0.0; start = r.get("ts"); days = 0
        if ret is not None:
            acc += float(ret); days += 1
    if cur_pos != 0 and start is not None:                 # trade ที่ยังเปิดอยู่
        trades.append({"pos": cur_pos, "ret": acc, "days": days, "start": start, "end": rows[-1].get("ts"), "open": True})
    return trades


def _summ(label, trades):
    closed = [t for t in trades if not t.get("open")]
    if not closed:
        print(f"  {label}: ยังไม่มี trade ปิด ({len(trades)} เปิดอยู่)"); return
    import statistics as st
    rets = [t["ret"] for t in closed]
    wr = 100.0 * sum(1 for x in rets if x > 0) / len(rets)
    avg = sum(rets) / len(rets)
    print(f"  {label}: trade ปิด n={len(closed)}  avg_ret {avg*100:+.2f}%  WR {wr:.0f}%  "
          f"cum {sum(rets)*100:+.1f}%  (median hold {int(st.median([t['days'] for t in closed]))}d)")


def main():
    rows = _load("tsmom__BTCUSD.jsonl")
    print("\n=== BTC tsmom SHADOW monitor (forward D1 collection) ===")
    if not rows:
        print("  logs/shadow/tsmom__BTCUSD.jsonl = ยังไม่มี/ว่าง. shadow เก็บต่อเมื่อบอทรัน (SHADOW_ENGINE=true).")
        return
    ts = [r.get("ts") for r in rows if r.get("ts")]
    days = len(rows)
    last = rows[-1]
    print(f"  ช่วง: {ts[0][:10]}  ..  {ts[-1][:10]}  ({days} วัน tape)")
    print(f"  position ปัจจุบัน: pos={last.get('pos')} (sig_now={last.get('sig_now')}) @ close {last.get('close')}")

    trades = _trades_from_tape(rows)
    longs = [t for t in trades if t["pos"] > 0]
    shorts = [t for t in trades if t["pos"] < 0]
    print(f"\n  discrete trades (จับกลุ่ม pos): รวม {len(trades)} (long {len(longs)} · short {len(shorts)})")
    _summ("ALL (raw signal)", trades)
    _summ("LONG-ONLY (= ทิศ edge จริง, ที่ live จะเทรด)", longs)
    if shorts:
        _summ("short (live บล็อกโดย LONG_ONLY_ALL — ref เฉยๆ)", shorts)

    closed_long = [t for t in longs if not t.get("open")]
    n = len(closed_long)
    span_days = days or 1
    rate_per_yr = n / (span_days / 365.0) if span_days else 0
    print(f"\n  progress → n≥{TARGET_N} (deflated-bar re-test): long ปิดแล้ว {n}/{TARGET_N}")
    if rate_per_yr > 0:
        eta_yr = (TARGET_N - n) / rate_per_yr
        print(f"  rate ~{rate_per_yr:.1f} long-trade/ปี (D1) → ETA ถึง n={TARGET_N} ≈ {eta_yr:.0f} ปี  ⚠️ ช้ามาก")
    print("  → forward D1 อย่างเดียวไม่พอทันใช้. accelerator = ส่ง BTC H1/H4 CSV (finer TF) มา re-test n โตเร็ว.")
    print("  หมายเหตุ: ret เป็น %-return ไม่ใช่ R-normalized; พอ trade พอค่อยแปลงเป็น R เทียบ backtest + placebo/deflated.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
