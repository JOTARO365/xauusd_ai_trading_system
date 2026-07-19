"""agents/entry_gate.py — P-B: ทิศทาง entry จาก S/R + indicator + vol/momentum gate (DESIGN_algo_v2 §2).

deterministic, 0 LLM, 0 order. ต่อยอด docs/proposals/evidence_entry_reference.py (zone-prior Beta-smoothed
P(bounce) + log-odds + EV + falling-knife veto) — **generalize เป็น fade 2 ทาง**: BUY@support / SELL@resistance.
ดึง level จาก sr_engine (P-A) ที่มี bounce_pct/grade/cluster/confluence อยู่แล้ว.

⚠️ weights ยังไม่ fit (ILLUSTRATIVE) → `conf`/`p_edge` = evidence score สำหรับ **journal เก็บ data ไป fit** เท่านั้น
ยังไม่ใช้ตัดสิน fill จริง. gate ตัดสินด้วยกฎ interpretable: EV>0 (จาก empirical bounce_pct) + RR floor + veto.

CORE INVARIANT: entry = คำนวณจาก data (bounce_pct empirical + momentum/vol) ไม่ prediction, ไม่มี AI.
"""
import math

# ── weights (ILLUSTRATIVE — NOT FITTED; เก็บ data ผ่าน journal แล้วค่อย fit) ──
W = {
    "w_news": 1.4, "w_rev": 1.0, "w_mom": 0.9, "w_fast": 0.5, "w_vol": 0.2, "b0": 0.0,
    "beta_prior_strength": 2.0, "global_bounce_rate": 0.5,
    "rr_floor": 1.5,                          # iron-rule: RR ต่ำกว่านี้ = SKIP
    "near_atr": 0.6,                          # ราคาต้องใกล้ level ≤ near_atr·ATR ถึงพิจารณา
    "fast_break_pips": 500,                    # fast_move สวน fade เกินนี้ = ราคากำลัง break → gate block
}


def _logit(p):
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def zone_prior(level, w=W):
    """F5: Beta-smoothed empirical bounce prob ที่ level นี้ (จาก sr_meta.bounce_pct/n_tests).
    thin/absent → shrink สู่ global_bounce_rate. คืน (p, n_tests)."""
    if not level:
        return w["global_bounce_rate"], 0
    n = int(level.get("n_tests") or 0)
    bp = level.get("bounce_pct")
    if bp is None or n <= 0:
        return w["global_bounce_rate"], n
    bounces = round(float(bp) / 100.0 * n)
    a = w["beta_prior_strength"] * w["global_bounce_rate"]
    b = w["beta_prior_strength"] * (1.0 - w["global_bounce_rate"])
    p = (bounces + a) / (n + a + b)
    return max(1e-4, min(1 - 1e-4, p)), n


def _mom_align(momentum_tf, direction):
    """F4: vote m15/h1 momentum เทียบทิศ (สำหรับ fade: want = ทิศเด้งกลับ). [-1,+1]."""
    mom = momentum_tf or {}
    want = "UP" if direction == "BUY" else "DOWN"

    def vote(tf, sw, ww):
        d = (tf or {}).get("direction")
        if d not in ("UP", "DOWN"):
            return 0.0
        wt = sw if (tf or {}).get("strength") == "STRONG" else ww
        return wt if d == want else -wt
    return max(-1.0, min(1.0, vote(mom.get("m15"), 0.6, 0.3) + vote(mom.get("h1"), 0.4, 0.2)))


def _fast_signed(fast_move_pips, direction):
    """F6: fast move เทียบทิศ fade, bounded tanh. + = ไปทางที่ fade อยากได้."""
    fast = float(fast_move_pips or 0.0)
    signed = fast if direction == "BUY" else -fast
    return math.tanh(signed / 500.0)


def _vol_tilt(volume_profile, direction):
    """F7: tick-volume tilt (proxy, น้ำหนักต่ำ)."""
    tilt = (volume_profile or {}).get("tilt")
    if tilt == "buy":
        return 1.0 if direction == "BUY" else -1.0
    if tilt == "sell":
        return 1.0 if direction == "SELL" else -1.0
    return 0.0


def _rsi_confirm(rsi, direction):
    """RSI ยืนยัน fade: BUY@support อยาก oversold (<40), SELL@resistance อยาก overbought (>60). [-1,+1]."""
    if rsi is None:
        return 0.0
    rsi = float(rsi)
    if direction == "BUY":
        return max(-1.0, min(1.0, (45 - rsi) / 20.0))     # ยิ่ง oversold ยิ่ง +
    return max(-1.0, min(1.0, (rsi - 55) / 20.0))         # ยิ่ง overbought ยิ่ง +


def p_edge(level, market, direction, rsi=None, w=W):
    """P(fade สำเร็จ) = sigmoid(logit(zone_prior) + Σ w·feature). zone_prior = offset (empirical จริง)."""
    zp, n = zone_prior(level, w)
    f_mom = _mom_align(market.get("momentum_tf"), direction)
    f_fast = _fast_signed(market.get("fast_move_pips"), direction)
    f_vol = _vol_tilt(market.get("volume_profile"), direction)
    f_rsi = _rsi_confirm(rsi, direction)
    logodds = (_logit(zp) + w["w_mom"] * f_mom + w["w_fast"] * f_fast
               + w["w_vol"] * f_vol + 0.6 * f_rsi + w["b0"])
    return _sigmoid(logodds), {"zone_prior": round(zp, 3), "n_tests": n, "mom": round(f_mom, 2),
                               "fast": round(f_fast, 2), "vol": round(f_vol, 2), "rsi": round(f_rsi, 2)}


def vol_momentum_gate(market, direction, w=W):
    """ก่อน fill: ราค่าแรงผิดจังหวะ (กำลัง break ผ่าน level ที่จะ fade) → block รอ.
    BUY@support: ราคาดิ่งแรง (fast<<0) / m15+h1 DOWN STRONG = กำลังทะลุลง → ไม่ควร buy สวน.
    คืน {pass, reason}."""
    fast = float(market.get("fast_move_pips") or 0.0)
    thr = w["fast_break_pips"]
    mom = market.get("momentum_tf") or {}
    m15 = (mom.get("m15") or {}); h1 = (mom.get("h1") or {})
    against = "DOWN" if direction == "BUY" else "UP"
    breaking_fast = (fast <= -thr) if direction == "BUY" else (fast >= thr)
    breaking_mom = (m15.get("direction") == against and m15.get("strength") == "STRONG"
                    and h1.get("direction") == against)
    if breaking_fast:
        return {"pass": False, "reason": f"ราคาแรงสวน fade ({fast:+.0f}p ≥ {thr}p) — กำลัง break, รอ"}
    if breaking_mom:
        return {"pass": False, "reason": f"momentum m15+h1 {against} STRONG — กำลังทะลุ level, รอ"}
    return {"pass": True, "reason": "vol/momentum ok"}


def entry_direction(sr_view, market, rsi=None, w=W):
    """เลือกทิศ fade จาก S/R ที่ราคาใกล้ + indicator. RANGE = fade (BUY@support/SELL@resistance).
    คืน dict decision. dir=None = ยืนดู. **journal เก็บ p_edge/ev เพื่อ fit — ยังไม่ fill จริง.**"""
    if not sr_view.get("ok"):
        return {"dir": None, "reason": "sr_view ไม่พร้อม"}
    price = sr_view["price"]; atr = sr_view["atr"]
    sup = sr_view.get("support"); res = sr_view.get("resistance")
    near = w["near_atr"]
    # candidate: ราคาใกล้ support (พิจารณา BUY) หรือ resistance (พิจารณา SELL) — เลือกอันใกล้กว่า
    cand = []
    if sup and sup.get("dist_atr") is not None and sup["dist_atr"] <= near:
        cand.append(("BUY", "SUPPORT", sup))
    if res and res.get("dist_atr") is not None and res["dist_atr"] <= near:
        cand.append(("SELL", "RESISTANCE", res))
    if not cand:
        return {"dir": None, "reason": f"ราคาไม่ใกล้ S/R (≤{near}·ATR)", "price": price}
    cand.sort(key=lambda c: c[2]["dist_atr"])                # ใกล้สุดก่อน
    direction, at, level = cand[0]
    # veto: fade ต้องที่แนว "แข็งแรง" — แนวที่ประวัติมัก break (break_pct สูง, n พอ) = ห้าม fade
    bpct = level.get("break_pct"); nt = int(level.get("n_tests") or 0)
    if bpct is not None and nt >= 4 and float(bpct) >= 60:
        return {"dir": None, "at": at, "level": level["level"],
                "reason": f"แนว {at} มัก break ({bpct}% จาก {nt} tests) — ไม่ fade แนวอ่อน", "price": price}
    p, feats = p_edge(level, market, direction, rsi, w)
    # RR = ระยะไป target / ระยะ SL(ใต้ level) — ใช้ dist ไป opposite เป็น proxy TP, SL = 0.5·ATR ใต้ level
    from agents import sr_engine as SR
    sl_pips = max(1, round((abs(price - level["level"]) + 0.5 * atr) / SR.R.POINT))
    tp = SR.pick_tp_target(sr_view, direction, price, sl_pips, w["rr_floor"])
    rr = tp["rr"] if tp else 0.0
    ev = p * rr - (1.0 - p)
    gate = vol_momentum_gate(market, direction, w)
    ok = (rr >= w["rr_floor"]) and (ev > 0) and gate["pass"]
    return {
        "dir": direction if ok else None, "at": at, "level": level["level"],
        "grade": level.get("grade"), "significance": SR.level_significance(level),
        "p_edge": round(p, 3), "ev_R": round(ev, 3), "rr": round(rr, 2), "conf": round(p, 3),
        "tp": tp, "sl_pips": sl_pips, "gate": gate, "features": feats,
        "why": (f"fade {direction}@{at} lvl={level['level']} p={p:.2f} EV={ev:+.2f}R RR={rr:.1f} "
                f"{'✓' if ok else '✗ '+(gate['reason'] if not gate['pass'] else ('RR<floor' if rr<w['rr_floor'] else 'EV≤0'))}"),
        "price": price,
    }


if __name__ == "__main__":
    import json, sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from agents.sr_engine import from_live
    v = from_live()
    print("sr_view ok:", v.get("ok"))
    if v.get("ok"):
        import os
        st = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                          "logs", "bot_status.json"), encoding="utf-8"))
        market = st.get("market", {})
        market["fast_move_pips"] = st.get("last_signal", {}).get("fast_move_pips", 0)
        print(json.dumps(entry_direction(v, market), ensure_ascii=False, indent=2, default=str))
