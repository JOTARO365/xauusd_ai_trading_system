"""TREND-MODE shadow scorer — ให้คะแนนไม้ที่โดน block ว่า "ถ้าปล่อยเข้า" ได้/เสียเท่าไหร่

การทดลอง (pre-registered 2026-07-03):
  สมมติฐาน: ไม้ที่โดน htf_direction/counter_spike block ทั้งที่ trend หนุนทิศ
  (= reversal/pullback entries ที่ user เห็นบอทไม่ยอมเข้า) ถ้าปล่อยเข้าจะกำไร
  เกณฑ์เปิด TREND MODE จริง: n ≥ 30 โอกาส (dedupe แล้ว) AND pnl บวกทั้ง SL1000/TP2000
  และ SL1500/TP3000 AND WR > 40% — ต่ำกว่านี้ = คง gates เดิม
  baseline 07-03: n=5 (ตัดสินไม่ได้), control ไม่หนุนทิศ n=15 −3,978฿ (gates ถูก)

รัน: python scripts/score_trend_mode.py   (ต้องมี MT5 + logs/gate_blocks.jsonl)
"""
import bisect
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os
os.chdir(ROOT)
import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL

PV001      = 0.3315      # THB/point @0.01 lot (GOLD# broker-measured)
DEDUP_SEC  = 3600        # block signal เดิมภายใน 1 ชม. = โอกาสเดียว
CONF_MIN   = 62
TARGET_GATES = ("htf_direction", "counter_spike")

# เกณฑ์ pre-registered — ห้ามแก้กลางทางเพื่อให้ผ่าน
CRITERIA = {"min_n": 30, "min_wr": 40.0}


def main():
    already = mt5.terminal_info() is not None
    if not already:
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER,
                              timeout=15000):
            print("MT5 init fail:", mt5.last_error()); sys.exit(1)

    rows = [json.loads(l) for l in open("logs/gate_blocks.jsonl", encoding="utf-8")
            if l.strip()]
    first = min((r["at"] for r in rows), default=None)
    if not first:
        print("gate_blocks ว่าง"); return
    m15 = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M15,
                               datetime.fromisoformat(first).replace(tzinfo=None),
                               datetime.now())
    m15_t = [int(b["time"]) for b in m15]

    def simulate(ts, direction, sl_p, tp_p, max_bars=96 * 5):
        i0 = bisect.bisect_right(m15_t, ts)
        if i0 >= len(m15):
            return None, None
        entry = float(m15[i0]["open"])
        is_buy = direction == "BUY"
        sl = entry - sl_p * 0.01 if is_buy else entry + sl_p * 0.01
        tp = entry + tp_p * 0.01 if is_buy else entry - tp_p * 0.01
        for i in range(i0, min(i0 + max_bars, len(m15))):
            hi, lo = float(m15[i]["high"]), float(m15[i]["low"])
            if is_buy:
                if lo <= sl: return -sl_p * PV001, "SL"
                if hi >= tp: return tp_p * PV001, "TP"
            else:
                if hi >= sl: return -sl_p * PV001, "SL"
                if lo <= tp: return tp_p * PV001, "TP"
        last = float(m15[min(i0 + max_bars, len(m15)) - 1]["close"])
        d = (last - entry) if is_buy else (entry - last)
        return d / 0.01 * PV001, "MTM"

    # candidates
    cand = []
    for r in rows:
        sig = r.get("signal")
        if sig not in ("BUY", "SELL") or (r.get("conf") or 0) < CONF_MIN:
            continue
        trend = (r.get("trend") or "").upper()
        h4_align = (sig == "BUY" and trend == "BULLISH") or \
                   (sig == "SELL" and trend == "BEARISH")
        # เงื่อนไข momentum จริง (มี field ตั้งแต่ 07-03) — fallback H4 proxy สำหรับ row เก่า
        mom_ok = None
        if r.get("mom_h1") is not None:
            want = "UP" if sig == "BUY" else "DOWN"
            mom_ok = (r.get("mom_h1") == want and r.get("mom_m15") == want)
        cand.append({"ts": datetime.fromisoformat(r["at"]).timestamp(),
                     "sig": sig, "conf": r.get("conf"), "gate": r.get("gate"),
                     "align": h4_align, "mom_ok": mom_ok, "at": r["at"][:16]})
    cand.sort(key=lambda c: c["ts"])
    ops, last_sig = [], {}
    for c in cand:
        k = c["sig"]
        if k in last_sig and c["ts"] - last_sig[k] < DEDUP_SEC:
            last_sig[k] = c["ts"]; continue
        last_sig[k] = c["ts"]
        ops.append(c)

    def seg(g, lbl, sl_p, tp_p):
        res = [simulate(c["ts"], c["sig"], sl_p, tp_p) for c in g]
        res = [(p, k) for p, k in res if p is not None]
        if not res:
            print(f"  {lbl:<40} n=0"); return None
        n = len(res); tot = sum(p for p, _ in res)
        wr = sum(1 for p, _ in res if p > 0) / n * 100
        print(f"  {lbl:<40} n={n:<4} WR={wr:4.0f}% pnl={tot:>+9.0f}฿ avg={tot/n:+7.0f}")
        return {"n": n, "wr": wr, "pnl": tot}

    tm = [c for c in ops if c["align"] and c["gate"] in TARGET_GATES]
    tm_mom = [c for c in tm if c["mom_ok"]]   # เงื่อนไขจริง (rows ใหม่เท่านั้น)
    print(f"blocks {len(rows)} → conf≥{CONF_MIN} {len(cand)} → dedupe {len(ops)} โอกาส "
          f"| TREND-MODE target {len(tm)} (momentum-confirmed {len(tm_mom)})")
    ns = []        # n per SL/TP combo — used by n-guard below
    verdict = []
    for sl_p, tp_p in ((1000, 2000), (1500, 3000)):
        print(f"\n── SL{sl_p}/TP{tp_p} ──")
        s = seg(tm, "TREND-MODE (H4-align + target gates)", sl_p, tp_p)
        if tm_mom:
            seg(tm_mom, "  เฉพาะ momentum-confirmed", sl_p, tp_p)
        seg([c for c in ops if not c["align"]], "control: H4 ไม่หนุน", sl_p, tp_p)
        if s:
            ns.append(s["n"])
            verdict.append(s["n"] >= CRITERIA["min_n"] and s["pnl"] > 0
                           and s["wr"] > CRITERIA["min_wr"])

    print(f"\n{'='*60}")
    # n-guard: ห้ามออก verdict ถ้า sample ยังไม่ถึง 30 (pre-registered)
    if not ns or min(ns) < CRITERIA["min_n"]:
        print(f"⛔ sample ไม่พอตัดสิน (n={min(ns) if ns else 0}, "
              f"ต้อง≥{CRITERIA['min_n']}) — เก็บข้อมูลต่อ")
    elif verdict and all(verdict):
        print("✅ ผ่านเกณฑ์ pre-registered — พิจารณาเปิด TREND MODE จริงได้")
    else:
        print(f"⏳ ยังไม่ผ่านเกณฑ์ (ต้อง pnl บวกทั้ง 2 ค่า SL + "
              f"WR>{CRITERIA['min_wr']:.0f}%) — คง gates เดิม เก็บข้อมูลต่อ")

    if not already:
        mt5.shutdown()


if __name__ == "__main__":
    main()
