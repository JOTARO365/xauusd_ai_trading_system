#!/usr/bin/env python
"""
regime_monitor.py — weekly monitor ของ algo-live (ชิ้น #5). อ่านผล **ALGO trades จริงจาก MT5** →
score ต่อกลยุทธ์ + **N-gauge (สะสมพอตัดสินยัง)** + จับ decay. **ไม่จูน param** — แค่บอกความจริง.

หลักฐาน (regime_null / min-N calc): variance สูง (σ≈1.4R) + edge เล็ก → ต้อง ~หลายร้อยไม้ = เดือน-ปี
กว่าจะแยก edge จาก noise. monitor นี้ทำให้เห็น "N ที่มี vs N ที่ต้องมี" ตรงๆ → กัน overfit จาก sample จิ๋ว.

รัน:  python scripts\\regime_monitor.py         (ต้องมี MT5; เขียน data/regime_monitor.json → dashboard)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_BASE, "data", "regime_monitor.json")
SIGMA_R = 1.41          # per-trade R std (วัดจาก momentum backtest) — ใช้คำนวณ needed-N
Z2 = 7.84               # (z_0.975 + z_0.80)² = (1.96+0.84)² — 95% conf, 80% power


def needed_n(delta_r, sigma=SIGMA_R):
    """จำนวนไม้ที่ต้องมีเพื่อแยก edge ขนาด delta_r (R/ไม้) จาก noise. N ≈ 7.84·σ²/δ²."""
    return int(Z2 * sigma ** 2 / delta_r ** 2)


def analyze(trades):
    """trades = list ของ {pnl: float, win: bool, R: float|None}. คืน score + N-gauge + verdict.
    pure function (ไม่พึ่ง MT5) → เทสได้."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "verdict": "ยังไม่มีไม้ ALGO — เปิด REGIME_LIVE แล้วรอเก็บ",
                "needed": {f"δ={d}": needed_n(d) for d in (0.15, 0.20, 0.30)}}
    wins = [t for t in trades if t.get("win")]
    wr = len(wins) / n
    pnl = sum(t.get("pnl", 0.0) for t in trades)
    rs = [t["R"] for t in trades if t.get("R") is not None]
    exp_r = sum(rs) / len(rs) if rs else None
    # decay: เทียบครึ่งแรก vs ครึ่งหลัง (ต้องมีไม้พอ)
    decay = None
    if len(rs) >= 40:
        half = len(rs) // 2
        early = sum(rs[:half]) / half
        late = sum(rs[half:]) / (len(rs) - half)
        decay = {"early_expR": round(early, 3), "late_expR": round(late, 3),
                 "decaying": late < early - 0.10}
    need20 = needed_n(0.20)
    # ลำดับ: decay (safety, ปิดของกำลังพังก่อน) → N-gauge → ok. live money = protective bias
    if decay and decay["decaying"]:
        verdict = (f"⚠ DECAY — expR ครึ่งหลัง {decay['late_expR']} ต่ำกว่าครึ่งแรก {decay['early_expR']} "
                   f"→ พิจารณา disable (N={n}). safety ก่อน แม้ N ยังไม่ครบ")
    elif n < need20:
        verdict = f"ยังไม่พอตัดสิน — มี {n} ไม้ / ต้องการ ~{need20} (แยก edge δ=0.2R). ห้ามจูน (= noise)"
    else:
        verdict = f"เริ่มประเมินได้ (N={n}≥{need20}) — ยังไม่ decay"
    return {"n": n, "wr": round(wr, 3), "pnl": round(pnl, 2),
            "exp_R": round(exp_r, 3) if exp_r is not None else None,
            "decay": decay, "needed": {f"δ={d}": needed_n(d) for d in (0.15, 0.20, 0.30)},
            "verdict": verdict}


def fetch_algo_trades(days=180):
    """อ่าน ALGO- closed trades จาก MT5 deal history (mirror api_ride_stats). ต้องมี MT5 + regime_live.jsonl
    สำหรับ R (sl_pips). คืน list {pnl, win, R}. ถ้าไม่มี MT5 → []."""
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        if not mt5.initialize():
            return []
        from collections import defaultdict
        deals = mt5.history_deals_get(datetime.now() - timedelta(days=days), datetime.now()) or []
        # sl_pips ต่อ position จาก regime_live.jsonl (join ด้วย ticket)
        sl_by_ticket = {}
        p = os.path.join(_BASE, "logs", "regime_live.jsonl")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                try:
                    r = json.loads(line)
                    tk = (r.get("order") or {}).get("ticket")
                    if tk:
                        sl_by_ticket[tk] = (r.get("signal") or {}).get("sl_pips")
                except Exception:
                    pass
        pos = defaultdict(lambda: {"pnl": 0.0, "entry": None, "closed": False})
        for d in deals:
            if getattr(d, "magic", 0) != 20260429:       # SYSTEM_MAGIC — algo/system trades
                continue                                  # (กรอง magic ไม่ใช่ comment: exit deal ถูก broker เปลี่ยนเป็น sl/tp)
            pp = pos[d.position_id]
            pp["pnl"] += d.profit + d.swap + d.commission
            if d.entry == 0 and pp["entry"] is None:
                pp["entry"] = d
            elif d.entry in (1, 2):
                pp["closed"] = True
                pp["close_time"] = getattr(d, "time", None)
        out = []
        for pid, pp in pos.items():
            if not pp["closed"]:
                continue
            sl = sl_by_ticket.get(pid)
            # R ≈ pnl / (planned risk). ประมาณ risk จาก sl_pips·lot·pip_value — ถ้าไม่มี sl ให้ R=None
            R = None
            if sl and pp["entry"]:
                pip_val = 0.01 * getattr(pp["entry"], "volume", 0.01) * 100   # XAU: $0.01/pip/0.01lot ≈ ปรับตามบัญชี
                risk = sl * pip_val if pip_val else 0
                R = pp["pnl"] / risk if risk else None
            out.append({"pnl": pp["pnl"], "win": pp["pnl"] > 0, "R": round(R, 3) if R is not None else None,
                        "close_ts": pp.get("close_time")})
        return out
    except Exception:
        return []


def main():
    trades = fetch_algo_trades()
    rep = {"generated": datetime.now(timezone.utc).isoformat(), "strategy": "momentum_breakout (TREND)",
           "sigma_R": SIGMA_R, **analyze(trades)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"✅ wrote {OUT}")
    print(f"N={rep['n']}  verdict: {rep['verdict']}")
    print(f"needed-N: {rep['needed']}")


if __name__ == "__main__":
    main()
