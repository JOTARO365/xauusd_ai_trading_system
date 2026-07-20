"""agents/algo_journal.py — counterfactual signal→outcome journal (0 LLM, 0 order, data-only).

เก็บ "ทุก signal ที่ algo พิจารณาเข้า order" (momentum breakout ที่แท่งปิด) + resolve **ผลลัพธ์จริง**
จากราคาที่วิ่งต่อ → ได้ dataset counterfactual สำหรับพิสูจน์ edge (รวมไม้ที่เข้าจริง + ไม้ที่ถูกบล็อก
no-stack/dup). deterministic, ไม่ prediction, ไม่มี AI — ตรง CORE INVARIANT + directive "เก็บ data".

flow: journal_tick() เรียกทุก cycle จาก node_position_mgmt (ทุก execution mode).
  1. compute signal ที่แท่งปิดล่าสุด (regime_shadow.compute_shadow_signal) — เหมือน executor เป๊ะ
  2. ถ้าเป็น momentum_breakout บนแท่งใหม่ → append OPEN record (entry=close, SL/TP=entry±pips·POINT)
  3. resolve OPEN records จาก forward bars: first-touch (ชน SL+TP แท่งเดียว = assume SL, pessimistic ตาม gauntlet),
     net-of-cost, + MFE/MAE (สำหรับ exit research)

outcome fields: result TP/SL/TIMEOUT/OPEN · realized_R (net) · realized_R_gross · mfe_R · mae_R · bars_held
kill: ผูกกับ REGIME_LIVE/REGIME_SHADOW (ปิด = ไม่ journal). ไฟล์: logs/algo_journal.jsonl
วิเคราะห์ offline: python agents/algo_journal.py
"""
import json
import os
from datetime import datetime, timezone

import numpy as np

import config as _cfg
from agents.regime_shadow import _bars_from_feed, compute_shadow_signal

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG = os.path.join(_BASE, "logs", "algo_journal.jsonl")

POINT = 0.01                 # sync กับ regime_lib.POINT (ทอง)
COST_PIPS = 30               # spread+commission (sync regime_analytics cost_pips=30) — หัก realized_R ครั้งเดียว
MAX_HOLD_BARS = 48           # ไม่ชน TP/SL ใน 48 H1 bars (~2 วัน) → TIMEOUT (mark-to-market)


def _rows():
    """อ่าน journal ทั้งหมด (fail-soft, ข้าม line เสีย)."""
    out = []
    if not os.path.exists(_LOG):
        return out
    try:
        with open(_LOG, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return out


def _write(rows):
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        with open(_LOG, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _resolve(rec, high, low, close, times):
    """เติม outcome ให้ record จาก forward bars. คืน True ถ้าเปลี่ยนสถานะ (ต้อง rewrite).
    first-touch: ชน SL+TP แท่งเดียว → assume SL (pessimistic ตาม gauntlet). MFE/MAE เก็บทุกแท่ง."""
    entry = rec["entry"]
    dir_ = rec["dir"]
    risk = rec["sl_pips"] * POINT
    if risk <= 0:
        return False
    sign = 1 if dir_ == "BUY" else -1
    sl = entry - sign * rec["sl_pips"] * POINT
    tp = entry + sign * rec["tp_pips"] * POINT
    # หา index แท่ง signal ใน bars ปัจจุบัน (match bar_ts)
    i0 = None
    for k in range(len(times)):
        try:
            ts = datetime.fromtimestamp(int(times[k]), timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            continue
        if ts == rec["bar_ts"]:
            i0 = k
            break
    if i0 is None:
        return False                                 # แท่ง signal หลุด window แล้ว → รอ (หรือค้าง OPEN)
    mfe = (rec.get("outcome") or {}).get("mfe_R", 0.0) or 0.0
    mae = (rec.get("outcome") or {}).get("mae_R", 0.0) or 0.0
    for j in range(i0 + 1, len(close)):              # แท่งถัดจาก signal เป็นต้นไป
        hi, lo = float(high[j]), float(low[j])
        fav = (hi - entry) if dir_ == "BUY" else (entry - lo)     # excursion บวก (ไปทาง TP)
        adv = (entry - lo) if dir_ == "BUY" else (hi - entry)     # excursion ลบ (ไปทาง SL)
        mfe = max(mfe, fav / risk)
        mae = min(mae, -adv / risk)
        hit_sl = (lo <= sl) if dir_ == "BUY" else (hi >= sl)
        hit_tp = (hi >= tp) if dir_ == "BUY" else (lo <= tp)
        if hit_sl and hit_tp:
            return _close(rec, "SL", -1.0, j - i0, close[j], times[j], mfe, mae)   # assume SL
        if hit_sl:
            return _close(rec, "SL", -1.0, j - i0, close[j], times[j], mfe, mae)
        if hit_tp:
            return _close(rec, "TP", rec["tp_pips"] / rec["sl_pips"], j - i0, close[j], times[j], mfe, mae)
        if (j - i0) >= MAX_HOLD_BARS:
            r_gross = sign * (float(close[j]) - entry) / risk
            return _close(rec, "TIMEOUT", r_gross, j - i0, close[j], times[j], mfe, mae)
    # ยังไม่ resolve — เก็บ MFE/MAE ปัจจุบันไว้ (running), สถานะ OPEN
    prev = rec.get("outcome")
    rec["outcome"] = {"result": "OPEN", "bars_held": len(close) - 1 - i0,
                      "mfe_R": round(mfe, 3), "mae_R": round(mae, 3)}
    return rec["outcome"] != prev


def _close(rec, result, r_gross, bars, exit_px, exit_ts, mfe, mae):
    """ปิด record: realized_R (net cost) + รายละเอียด. คืน True (เปลี่ยนสถานะ)."""
    cost_R = COST_PIPS / rec["sl_pips"] if rec["sl_pips"] else 0.0
    try:
        ex_ts = datetime.fromtimestamp(int(exit_ts), timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        ex_ts = None
    rec["outcome"] = {
        "result": result,
        "realized_R": round(r_gross - cost_R, 3),           # net of cost
        "realized_R_gross": round(r_gross, 3),
        "bars_held": int(bars),
        "mfe_R": round(mfe, 3), "mae_R": round(mae, 3),
        "exit_px": round(float(exit_px), 2), "exit_ts": ex_ts,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    return True


_PENDING_EXPIRY_BARS = {"STOP": 2, "FADE": 6}    # sync expiry_hours ใน regime_pending (H1 bar)


def _idx_of(bar_ts, times):
    """หา index ของ bar_ts ใน times (None ถ้าหลุด window)."""
    if not bar_ts:
        return None
    for k in range(len(times)):
        try:
            if datetime.fromtimestamp(int(times[k]), timezone.utc).isoformat() == bar_ts:
                return k
        except (ValueError, OSError, OverflowError):
            continue
    return None


def record_pending(otype, level, sl_pips, tp_pips, mode, regime, bar_ts, grade=None):
    """บันทึก pending order (real/shadow) ตอนวาง → resolve lifecycle ทีหลัง. dedup 1/(otype,level) ที่ยัง unresolved.
    mode='STOP'(breakout)/'FADE'. bar_ts=แท่งปิดล่าสุด (ref สำหรับ resolve). fail-soft."""
    if not getattr(_cfg, "REGIME_LIVE", False):
        return
    try:
        rows = _rows()
        lv = round(float(level), 1)
        done = ("TP", "SL", "TIMEOUT", "EXPIRED")
        openp = {(r["otype"], round(float(r["level"]), 1)) for r in rows
                 if r.get("kind") == "pending" and (r.get("outcome") or {}).get("result") not in done}
        if (otype, lv) in openp:
            return
        direction = "BUY" if str(otype).startswith("BUY") else "SELL"
        sign = 1 if direction == "BUY" else -1
        entry = float(level)
        rows.append({
            "kind": "pending", "logged_at": datetime.now(timezone.utc).isoformat(), "bar_ts": bar_ts,
            "otype": otype, "mode": mode, "dir": direction, "level": round(entry, 2),
            "sl": round(entry - sign * sl_pips * POINT, 2), "tp": round(entry + sign * tp_pips * POINT, 2),
            "sl_pips": sl_pips, "tp_pips": tp_pips, "regime": regime, "grade": grade,
            "filled": False, "fill_ts": None, "outcome": None,
        })
        _write(rows)
    except Exception:
        pass


def _resolve_pending(rec, high, low, close, times):
    """2 เฟส: (1) fill เมื่อราคาแตะ level, (2) หลัง fill → TP/SL first-touch. EXPIRED ถ้าไม่ fill. คืน True ถ้าเปลี่ยน."""
    entry = float(rec["level"]); direction = rec["dir"]; is_stop = "STOP" in rec["otype"]
    risk = rec["sl_pips"] * POINT
    if risk <= 0:
        return False
    i0 = _idx_of(rec.get("bar_ts"), times)
    if i0 is None:
        return False
    sign = 1 if direction == "BUY" else -1
    sl = entry - sign * rec["sl_pips"] * POINT
    tp = entry + sign * rec["tp_pips"] * POINT
    expiry = _PENDING_EXPIRY_BARS.get(rec.get("mode"), 6)
    fill_j = _idx_of(rec.get("fill_ts"), times) if rec.get("filled") else None

    # ── เฟส 1: หา fill (LIMIT รอราคาย้อนแตะ · STOP รอทะลุ) ──
    if not rec.get("filled"):
        for j in range(i0 + 1, len(close)):
            hi, lo = float(high[j]), float(low[j])
            if direction == "BUY":
                filled = (hi >= entry) if is_stop else (lo <= entry)
            else:
                filled = (lo <= entry) if is_stop else (hi >= entry)
            if filled:
                rec["filled"] = True
                try:
                    rec["fill_ts"] = datetime.fromtimestamp(int(times[j]), timezone.utc).isoformat()
                except Exception:
                    rec["fill_ts"] = None
                fill_j = j
                break
            if (j - i0) >= expiry:
                rec["outcome"] = {"result": "EXPIRED", "bars_held": j - i0, "note": "ไม่ fill ใน expiry — ยกเลิก"}
                return True
        if not rec.get("filled"):
            prev = rec.get("outcome")
            rec["outcome"] = {"result": "WAITING", "bars_held": len(close) - 1 - i0}
            return rec["outcome"] != prev

    # ── เฟส 2: outcome จาก fill bar → TP/SL first-touch (entry = level) ──
    if fill_j is None:
        return False                                         # fill bar หลุด window (น่าจะ resolve ไปแล้ว)
    mfe = (rec.get("outcome") or {}).get("mfe_R", 0.0) or 0.0
    mae = (rec.get("outcome") or {}).get("mae_R", 0.0) or 0.0
    for j in range(fill_j + 1, len(close)):
        hi, lo = float(high[j]), float(low[j])
        fav = (hi - entry) if direction == "BUY" else (entry - lo)
        adv = (entry - lo) if direction == "BUY" else (hi - entry)
        mfe = max(mfe, fav / risk); mae = min(mae, -adv / risk)
        hit_sl = (lo <= sl) if direction == "BUY" else (hi >= sl)
        hit_tp = (hi >= tp) if direction == "BUY" else (lo <= tp)
        if hit_sl:
            return _close(rec, "SL", -1.0, j - fill_j, close[j], times[j], mfe, mae)
        if hit_tp:
            return _close(rec, "TP", rec["tp_pips"] / rec["sl_pips"], j - fill_j, close[j], times[j], mfe, mae)
        if (j - fill_j) >= MAX_HOLD_BARS:
            return _close(rec, "TIMEOUT", sign * (float(close[j]) - entry) / risk, j - fill_j, close[j], times[j], mfe, mae)
    prev = rec.get("outcome")
    rec["outcome"] = {"result": "FILLED", "bars_held": len(close) - 1 - fill_j,
                      "mfe_R": round(mfe, 3), "mae_R": round(mae, 3)}
    return rec["outcome"] != prev


def _capture_fade(rows, high, low, close, times):
    """P-B shadow: อ่าน sr_meta (bot_status) + cluster (MT5) → entry_gate.entry_direction → fade record.
    dedup: 1 OPEN fade / (dir, level). คืน record ใหม่ หรือ None. fail-soft."""
    import sys as _sys
    _sys.path.insert(0, os.path.join(_BASE, "scripts"))
    import regime_lib as _R
    from agents.sr_engine import build_sr_view
    from agents.entry_gate import entry_direction
    try:
        with open(os.path.join(_BASE, "logs", "bot_status.json"), encoding="utf-8") as f:
            st = json.load(f)
    except OSError:
        return None
    sr_meta = ((st.get("zones") or {}).get("sr_meta")) or []
    if not sr_meta:
        return None
    price = float(close[-1])
    cluster = None
    try:                                                    # cluster density จาก bars ที่ journal มี (ไม่ fetch MT5 ซ้ำ)
        from agents.cluster_map import compute_cluster_map
        cluster = compute_cluster_map(high, low, close)
        if not (cluster or {}).get("ok"):
            cluster = None
    except Exception:
        cluster = None
    atr = (cluster or {}).get("atr")
    if not atr:                                             # fallback: ATR จาก bars (density แค่หายไป)
        try:
            atr = float(_R.atr(high, low, close)[-1])
        except Exception:
            return None
    if not atr or atr <= 0:
        return None
    sr_view = build_sr_view(sr_meta, price, float(atr), cluster)
    if not sr_view.get("ok"):
        return None
    market = dict(st.get("market") or {})
    market.setdefault("fast_move_pips", (st.get("last_signal") or {}).get("fast_move_pips", 0))
    market["volume_profile"] = st.get("volume_profile")
    dec = entry_direction(sr_view, market)                  # rsi=None (ไม่มีใน bot_status) → graceful
    if not dec.get("dir"):
        return None
    lvl = round(float(dec["level"]), 1)
    open_fades = {(r["dir"], round(float(r.get("fade_level", 0)), 1)) for r in rows
                  if r.get("kind") == "fade" and (r.get("outcome") or {}).get("result") not in ("TP", "SL", "TIMEOUT")}
    if (dec["dir"], lvl) in open_fades:
        return None                                         # มี fade เปิดที่ level นี้แล้ว → ไม่ซ้ำ
    tp_price = (dec.get("tp") or {}).get("tp")
    if tp_price is None:
        return None
    sign = 1 if dec["dir"] == "BUY" else -1
    entry = price
    return {
        "kind": "fade", "logged_at": datetime.now(timezone.utc).isoformat(),
        "bar_ts": datetime.fromtimestamp(int(times[-2]), timezone.utc).isoformat(),   # แท่งปิดล่าสุด (resolve จากถัดไป)
        "dir": dec["dir"], "at": dec.get("at"), "fade_level": dec["level"],
        "entry": round(entry, 2),
        "sl": round(entry - sign * dec["sl_pips"] * POINT, 2),
        "tp": round(tp_price, 2),
        "sl_pips": dec["sl_pips"], "tp_pips": max(1, round(abs(tp_price - entry) / POINT)),
        "grade": dec.get("grade"), "significance": dec.get("significance"),
        "p_edge": dec.get("p_edge"), "ev_R": dec.get("ev_R"), "rr": dec.get("rr"),
        "features": dec.get("features"), "outcome": None,
    }


def journal_tick(bars=None):
    """เรียกทุก cycle. บันทึก signal ใหม่ + resolve ที่ค้าง. fail-soft. คืน record ใหม่ (ถ้ามี) หรือ None."""
    if not (getattr(_cfg, "REGIME_LIVE", False) or getattr(_cfg, "REGIME_SHADOW", False)):
        return None
    if bars is None:
        bars = _bars_from_feed()
    if bars is None:
        return None
    high, low, close, times = bars
    rows = _rows()
    changed = False
    new_rec = None

    # ── 1. capture signal ใหม่ (momentum breakout ที่แท่งปิด) ──
    rec = compute_shadow_signal(high, low, close, times)
    if rec and rec.get("bar_ts"):
        sig = rec.get("signal")
        if sig and sig.get("algo") == "momentum_breakout":
            seen = {r["bar_ts"] for r in rows if r.get("kind") == "signal"}
            if rec["bar_ts"] not in seen:              # dedup: 1 signal / H1 bar
                entry = float(rec["close"])
                new_rec = {
                    "kind": "signal",
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                    "bar_ts": rec["bar_ts"], "regime": rec["regime"],
                    "dir": sig["dir"], "entry": round(entry, 2),
                    "sl": round(entry - (1 if sig["dir"] == "BUY" else -1) * sig["sl_pips"] * POINT, 2),
                    "tp": round(entry + (1 if sig["dir"] == "BUY" else -1) * sig["tp_pips"] * POINT, 2),
                    "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"],
                    "er": rec.get("er"), "adx": rec.get("adx"), "volpct": rec.get("volpct"), "atr": rec.get("atr"),
                    "outcome": None,
                }
                rows.append(new_rec)
                changed = True

    # ── 1b. capture fade candidate (P-B entry_gate) — REGIME_SR_ENTRY shadow ──
    if getattr(_cfg, "REGIME_SR_ENTRY", False):
        try:
            fr = _capture_fade(rows, high, low, close, times)
            if fr:
                rows.append(fr)
                new_rec = new_rec or fr
                changed = True
        except Exception:
            pass

    # ── 2. resolve OPEN records จาก forward bars (momentum signal + fade + pending lifecycle) ──
    for r in rows:
        k = r.get("kind")
        if k not in ("signal", "fade", "pending"):
            continue
        oc = r.get("outcome")
        if oc and oc.get("result") in ("TP", "SL", "TIMEOUT", "EXPIRED"):
            continue                                   # ปิดแล้ว
        if (_resolve_pending if k == "pending" else _resolve)(r, high, low, close, times):
            changed = True

    if changed:
        _write(rows)
    return new_rec


def _summ(closed, open_n):
    """สรุปสถิติชุด closed records (มี outcome). คืน dict หรือ note ถ้าว่าง."""
    if not closed:
        return {"n_closed": 0, "n_open": open_n, "note": "ยังไม่มีไม้ปิด — รอเก็บ"}
    Rs = [r["outcome"]["realized_R"] for r in closed]
    wins = sum(1 for r in closed if r["outcome"]["result"] == "TP")
    return {
        "n_closed": len(closed), "n_open": open_n,
        "win_rate": round(wins / len(closed), 3),
        "exp_R": round(float(np.mean(Rs)), 3),
        "sigma_R": round(float(np.std(Rs, ddof=1)) if len(Rs) > 1 else 0.0, 3),
        "sum_R": round(float(np.sum(Rs)), 2),
        "by_result": {k: sum(1 for r in closed if r["outcome"]["result"] == k) for k in ("TP", "SL", "TIMEOUT")},
        "avg_mfe_R": round(float(np.mean([r["outcome"]["mfe_R"] for r in closed])), 2),
        "avg_mae_R": round(float(np.mean([r["outcome"]["mae_R"] for r in closed])), 2),
    }


def summary():
    """สรุป offline แยก momentum signal / fade / pending (จริง lifecycle) + รวม. 0 token.
    เทียบ needed-N (σ≈1.41): δ=0.2R→389, δ=0.3R→173. counterfactual net cost 30p."""
    all_ = [r for r in _rows() if r.get("outcome")]
    sf = [r for r in all_ if r.get("kind") in ("signal", "fade")]

    def split(rows_k):
        closed = [r for r in rows_k if r["outcome"].get("result") in ("TP", "SL", "TIMEOUT")]
        open_n = sum(1 for r in rows_k if r["outcome"].get("result") in ("OPEN", "WAITING", "FILLED"))
        return _summ(closed, open_n)

    # pending: filled+resolved = closed trades · EXPIRED/WAITING/FILLED แยก
    pend = [r for r in all_ if r.get("kind") == "pending"]
    pclosed = [r for r in pend if r["outcome"].get("result") in ("TP", "SL", "TIMEOUT")]
    pend_summ = _summ(pclosed, sum(1 for r in pend if r["outcome"].get("result") in ("WAITING", "FILLED")))
    pend_summ["expired"] = sum(1 for r in pend if r["outcome"].get("result") == "EXPIRED")
    pend_summ["by_mode"] = {m: sum(1 for r in pclosed if r.get("mode") == m) for m in ("STOP", "FADE")}

    closed_all = [r for r in sf if r["outcome"].get("result") in ("TP", "SL", "TIMEOUT")]
    open_all = sum(1 for r in sf if r["outcome"].get("result") == "OPEN")
    return {
        "momentum": split([r for r in sf if r.get("kind") == "signal"]),   # TREND breakout signal counterfactual
        "fade": split([r for r in sf if r.get("kind") == "fade"]),         # P-B entry_gate fade counterfactual
        "pending": pend_summ,                                              # pending order จริง (placed→fill→TP/SL)
        "combined": _summ(closed_all, open_all),
        "needed_n": {"δ=0.2": 389, "δ=0.3": 173},
        "note": "counterfactual (signal) + pending (lifecycle จริง placed→fill→TP/SL) net cost 30p",
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    s = summary()
    print("=" * 60)
    print("ALGO COUNTERFACTUAL JOURNAL — signal → ผลลัพธ์จริง")
    print("=" * 60)
    print(json.dumps(s, ensure_ascii=False, indent=2))
