#!/usr/bin/env python
"""
build_entry_dataset.py — P1 data builder (OFFLINE, read-only — ไม่แตะ live / ไม่ต่อ MT5)

สร้าง labeled dataset (features-at-decision -> outcome) เป็น foundation ของ evidence-based
entry model (docs/DESIGN_evidence_based_entry.md §7.0 "P1 enabler").

INTERIM version (ตรงตาม design §7.0 item 4):
  - label = forward-price replay ของ blocked-BUY counter_spike จาก gate_blocks
    (เข้า BUY ที่ราคานั้น, SL=2000p, TP=RR·SL, RR=2 -> WIN ถ้าถึง TP ก่อน SL ภายใน 24h)
  - price series = spot จาก gate_blocks (at, price) — resolution ~cycle, ไม่ใช่ OHLCV
    => label เอียง WIN (มองไม่เห็น wick ชน SL ระหว่าง sample) — ป้ายไว้ในผลเสมอ
  - features = เท่าที่ gate_blocks บันทึกไว้จริง (F4 momentum, F6 fast_move, sr_zone, trend, conf)
  - feature ที่ยังขาด (F1 news score, F3 reversal_confirm, F5 zone bounce_pct, F7 vol_tilt)
    = MISSING => เอกสารช่องว่าง P1b: ต้อง log full feature snapshot ตอน decision (แก้ pipeline, ขออนุมัติ)

Output:
  - data/entry_dataset.jsonl  (1 row/event: features + label + meta)
  - print สรุป: n, label balance, feature coverage, base-rate p0 (Beta prior)

รัน: $PY = "C:\\Users\\pornnatcha\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe"
     & $PY scripts\\build_entry_dataset.py
"""
import json
import os
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")   # กัน cp874 พังตอน print ไทย
except Exception:
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_BLOCKS = os.path.join(_BASE, "logs", "gate_blocks.jsonl")
TRADES_JSON = os.path.join(_BASE, "logs", "trades.json")
OUT_PATH    = os.path.join(_BASE, "data", "entry_dataset.jsonl")

# ตรงกับ MONEY_MANAGEMENT (config.py) — pip ทอง = 0.01
SL_PIPS   = 2000
RR        = 2.0
PIP       = 0.01
EXPIRY_H  = 24


def _parse_iso(s: str) -> float | None:
    """ISO -> epoch seconds (fail-soft)."""
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _load_gate_blocks() -> list[dict]:
    rows = []
    with open(GATE_BLOCKS, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return rows


def _build_timeline(rows: list[dict]) -> list[tuple[float, float]]:
    """spot price timeline จาก (at, price) ของทุก row — sorted by time. resolution ~cycle."""
    pts = []
    for r in rows:
        t = _parse_iso(r.get("at"))
        px = r.get("price")
        if t is not None and isinstance(px, (int, float)) and px > 0:
            pts.append((t, float(px)))
    pts.sort()
    return pts


def _label_buy(entry: float, t0: float, timeline: list[tuple[float, float]]) -> str | None:
    """WIN/LOSS/None(censored) สำหรับ BUY ที่ราคา entry เวลา t0 — first-touch บน spot timeline."""
    sl = entry - SL_PIPS * PIP
    tp = entry + RR * SL_PIPS * PIP
    horizon = t0 + EXPIRY_H * 3600
    for t, px in timeline:
        if t <= t0:
            continue
        if t > horizon:
            break
        if px <= sl:
            return "LOSS"     # ชน SL ก่อน (spot: เช็ค close ไม่เห็น wick -> เอียง WIN)
        if px >= tp:
            return "WIN"
    return None


def _extract_features(r: dict) -> dict:
    """feature เท่าที่ gate_blocks มีจริง + mark feature ที่ขาด (=P1b gap)."""
    return {
        # --- มีจริงใน gate_blocks ---
        "F4_mom_h1":   r.get("mom_h1"),
        "F4_mom_m15":  r.get("mom_m15"),
        "F6_fast_move": r.get("fast_move"),
        "sr_zone":     r.get("sr_zone"),
        "sr_strength": r.get("sr_strength"),
        "trend":       r.get("trend"),
        "d1_trend":    r.get("d1_trend"),
        "conf":        r.get("conf"),
        "sentiment_bias": r.get("sentiment_bias"),
        # --- ยังขาด: ต้อง log ตอน decision (P1b) ---
        "F1_news_score":       None,   # data/news_impact.json ตอนนั้น (ไม่ถูก snapshot)
        "F3_reversal_confirm": None,   # signals.reversal_confirm
        "F5_zone_bounce_pct":  None,   # sr_meta[nearest].bounce_pct (empirical prior)
        "F5_zone_grade":       None,
        "F7_vol_tilt":         None,   # volume_profile.tilt
    }


def _base_rate_p0() -> dict:
    """global support-bounce base-rate จาก trades.json — SYSTEM BUY ที่ SUPPORT, closed, WR."""
    try:
        data = json.load(open(TRADES_JSON, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"p0": None, "n": 0, "note": "trades.json อ่านไม่ได้"}
    trades = data if isinstance(data, list) else data.get("trades", [])
    buy_sup = [t for t in trades
               if str(t.get("source")) == "SYSTEM" and t.get("status") == "CLOSED"
               and t.get("direction") == "BUY" and t.get("sr_zone") == "SUPPORT"]
    n = len(buy_sup)
    wins = sum(1 for t in buy_sup if (t.get("pnl") or 0) > 0)
    p0 = round(wins / n, 4) if n else None
    # เทียบ base-rate BUY ทั้งหมด (ทุก zone) เผื่อ n น้อย
    buy_all = [t for t in trades if str(t.get("source")) == "SYSTEM"
               and t.get("status") == "CLOSED" and t.get("direction") == "BUY"]
    p0_all = round(sum(1 for t in buy_all if (t.get("pnl") or 0) > 0) / len(buy_all), 4) if buy_all else None
    return {"p0_buy_support": p0, "n_buy_support": n,
            "p0_buy_all": p0_all, "n_buy_all": len(buy_all)}


def main():
    rows = _load_gate_blocks()
    timeline = _build_timeline(rows)
    # negative-class candidates: counter_spike ที่บล็อก BUY (dip-buy)
    cs_buys = [r for r in rows
               if (r.get("gate") == "counter_spike" or "Counter-spike" in str(r.get("reason", "")))
               and r.get("signal") == "BUY"]

    dataset, lbl_counts = [], {"WIN": 0, "LOSS": 0, "CENSORED": 0}
    for r in cs_buys:
        t0 = _parse_iso(r.get("at"))
        entry = r.get("price")
        if t0 is None or not isinstance(entry, (int, float)) or entry <= 0:
            continue
        lbl = _label_buy(float(entry), t0, timeline)
        lbl_counts["CENSORED" if lbl is None else lbl] += 1
        feat = _extract_features(r)
        feat.update({
            "at": r.get("at"), "price": entry, "class": "blocked_buy_counter_spike",
            "label": lbl,
            "label_source": "counter_spike_replay(spot-proxy, WIN-biased)",
        })
        dataset.append(feat)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for row in dataset:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ── coverage report ──
    present = ["F4_mom_h1", "F4_mom_m15", "F6_fast_move", "sr_zone", "trend", "conf"]
    missing = ["F1_news_score", "F3_reversal_confirm", "F5_zone_bounce_pct", "F7_vol_tilt"]

    def cov(k):
        vals = [d.get(k) for d in dataset]
        return sum(1 for v in vals if v not in (None, "")) / len(dataset) if dataset else 0

    labeled = lbl_counts["WIN"] + lbl_counts["LOSS"]
    print("=" * 66)
    print("P1 ENTRY DATASET (interim) — OFFLINE, spot-proxy labels")
    print("=" * 66)
    print(f"blocked-BUY counter_spike events : {len(cs_buys)}")
    print(f"labeled (WIN/LOSS)               : {labeled}  "
          f"(WIN {lbl_counts['WIN']} / LOSS {lbl_counts['LOSS']} / censored {lbl_counts['CENSORED']})")
    if labeled:
        print(f"raw WR (spot-proxy, เอียง WIN)     : {lbl_counts['WIN']/labeled*100:.0f}%  "
              f"⚠️ ไม่ใช่ OHLCV — ใช้ประเมินหยาบเท่านั้น")
    print(f"\nfeature coverage (มีค่า/rows):")
    for k in present:
        print(f"  ✅ {k:16s}: {cov(k)*100:.0f}%")
    for k in missing:
        print(f"  ❌ {k:20s}: 0%  <- P1b gap (ต้อง log snapshot ตอน decision)")
    print(f"\nbase-rate p0 (สำหรับ Beta prior, จาก trades.json):")
    for k, v in _base_rate_p0().items():
        print(f"  {k}: {v}")
    print(f"\nเขียน: {OUT_PATH}  ({len(dataset)} rows)")
    print("\n⚠️  dataset นี้ label ได้แต่ feature ยังไม่ครบ (4 ตัวหลัก=0%). fit model จริงต้องทำ P1b")
    print("    (log full feature snapshot ตอน decision — แตะ pipeline, ขออนุมัติ) ก่อน")


if __name__ == "__main__":
    main()
