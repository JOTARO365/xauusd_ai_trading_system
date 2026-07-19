#!/usr/bin/env python
"""
regime_lib.py — P1: deterministic regime detector + ONE-algo-per-regime library (OFFLINE, flag-OFF)

จาก DESIGN_minimal_ai_regime_router.md (§CORE INVARIANT) + RESEARCH_regime_algorithms.md.
**CORE INVARIANT:** entry = คำนวณจาก data เท่านั้น (ไม่ prediction); AI/ข่าว = แค่ guide เลือก algo (ยังไม่มีใน P1).
**directive 07-19:** ONE strategy ต่อ regime (data ไม่ตีกัน + multiple-testing ต่ำ).

REGIME DETECTOR (deterministic fusion): Efficiency Ratio (Kaufman) + ADX (Wilder 14) + realized-vol percentile
  → TREND / RANGE / RISK-OFF / NEUTRAL

ALGO LIBRARY (หลัง P2 OOS validation — ตัดตัวที่พิสูจน์แล้วแพ้):
  • TREND    → momentum_breakout : Donchian ทะลุ + ATR SL/TP  [trend-bet; shadow forward-test ตัดสิน]
  • RANGE    → STAND-DOWN (mean_reversion ตัดออก 07-19: P2 OOS พิสูจน์ −EV both periods 0/27 combos;
                          ฟังก์ชัน algo_mean_reversion คงไว้อ้างอิง backtest เท่านั้น ไม่อยู่ใน routing)
  • RISK-OFF → STAND-DOWN (ทอง −10%/yr ใน high-vol — HMM เรา)
  • NEUTRAL  → STAND-DOWN

รัน (demo sanity-check — regime distribution + signal counts, ยังไม่ validate edge):
  python scripts\\regime_lib.py [tf]   (default h1)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINT = 0.01

# ── params (= N ที่ต้องนับตอน validate P2) ──
ER_WIN, ADX_WIN = 20, 14
VOL_WIN, VOL_LOOKBACK = 24, 480
BRK_WIN = 20                        # Donchian lookback (TREND)
ATR_WIN, ATR_SL, RR = 14, 1.5, 2.0
MR_WIN = 20                         # mean-reversion window
S_ENTRY = 1.25                      # Avellaneda s-score entry (verified 3-0)
MR_HALFLIFE_MAX = 10               # OU gate: half-life < 1/2 window (Avellaneda: reversion เร็วพอ)
S_STOP = 2.5                       # zone-based SL: วางเลย band ที่ S_STOP·std (กัน stop-hunt — QTA S/R zone)
TIME_STOP_K = 3                    # OU time-stop: max-hold = TIME_STOP_K × half-life bars (QTA stop-loss model 6)
# regime thresholds
ADX_TREND, ADX_RANGE = 25.0, 20.0
ER_TREND, ER_RANGE = 0.35, 0.25
VOL_RISKOFF_PCT = 0.80


# ─────────────────────────── indicators (deterministic) ───────────────────────────
def efficiency_ratio(close, n=ER_WIN):
    er = np.full(len(close), np.nan)
    ad = np.abs(np.diff(close, prepend=close[0]))
    for i in range(n, len(close)):
        v = ad[i - n + 1:i + 1].sum()
        er[i] = abs(close[i] - close[i - n]) / v if v > 0 else 0.0
    return er


def atr(high, low, close, n=ATR_WIN):
    """Wilder ATR (RMA smoothing = นิยามมาตรฐาน "ATR(14)"; สอดคล้องกับ adx() ที่ Wilder-smooth TR ภายใน).
    (เดิมใช้ simple-mean = "โมเดลดินเหนียว" ที่คอร์ส QTA วิจารณ์ + inconsistent กับ adx เราเอง)."""
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    tr = np.concatenate([[np.nan], tr])                # tr[0]=nan, tr[i]=TR ของ bar i (i≥1)
    out = np.full(len(close), np.nan)
    if len(close) > n:
        out[n] = np.nanmean(tr[1:n + 1])               # seed = simple mean ของ n TR แรก
        for i in range(n + 1, len(close)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n  # Wilder RMA
    return out


def adx(high, low, close, n=ADX_WIN):
    """Wilder ADX (trend strength). คืน array align กับ close."""
    up = high[1:] - high[:-1]; dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))

    def wilder(x):
        s = np.full(len(x), np.nan)
        if len(x) < n:
            return s
        s[n - 1] = x[:n].sum()
        for i in range(n, len(x)):
            s[i] = s[i - 1] - s[i - 1] / n + x[i]
        return s
    str_ = wilder(tr); pdm = wilder(plus_dm); mdm = wilder(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * pdm / str_; mdi = 100 * mdm / str_
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx_ = np.full(len(dx), np.nan)
    valid = np.where(~np.isnan(dx))[0]
    if len(valid) >= n:
        start = valid[0] + n - 1
        if start < len(dx):
            adx_[start] = np.nanmean(dx[valid[0]:start + 1])
            for i in range(start + 1, len(dx)):
                if not np.isnan(dx[i]):
                    adx_[i] = (adx_[i - 1] * (n - 1) + dx[i]) / n
    return np.concatenate([[np.nan], adx_])


def vol_percentile(close, w=VOL_WIN, lb=VOL_LOOKBACK):
    ret = np.diff(np.log(close), prepend=np.log(close[0]))
    rv = np.full(len(close), np.nan)
    for i in range(w, len(close)):
        rv[i] = ret[i - w + 1:i + 1].std()
    pct = np.full(len(close), np.nan)
    for i in range(lb, len(close)):
        window = rv[i - lb:i]; window = window[~np.isnan(window)]
        if len(window) > 20 and not np.isnan(rv[i]):
            pct[i] = (window < rv[i]).mean()
    return pct


def ou_halflife(x):
    """AR(1) x_t = a + b·x_{t-1} → OU half-life = −ln2/ln(b). คืน half-life (inf ถ้าไม่ mean-revert).
    (Avellaneda: gate เทรดเฉพาะ reversion เร็ว = half-life สั้น)."""
    x0, x1 = x[:-1], x[1:]
    if len(x0) < 5 or np.var(x0) == 0:
        return np.inf
    b = np.cov(x0, x1)[0, 1] / np.var(x0)
    if not (0 < b < 1):
        return np.inf                      # b≥1 = ไม่ดึงกลับ (trending/random) → ไม่เทรด mean-rev
    return -np.log(2) / np.log(b)


# ─────────────────────────── regime detector (fusion, deterministic) ───────────────────────────
def detect_regime(er, adx_v, volpct):
    if np.isnan(er) or np.isnan(adx_v):
        return "WARMUP"
    if not np.isnan(volpct) and volpct >= VOL_RISKOFF_PCT:
        return "RISK-OFF"                  # HMM validated จะเสียบ slot นี้ (P2)
    if adx_v >= ADX_TREND and er >= ER_TREND:
        return "TREND"
    if adx_v <= ADX_RANGE and er <= ER_RANGE:
        return "RANGE"
    return "NEUTRAL"


REGIME_ALGO = {"TREND": "momentum_breakout"}   # display/analytics map (sync กับ STRATEGIES ด้านล่าง)


# ─────────────────────────── algorithm library (EXECUTION — deterministic, ONE/regime) ───────────────────────────
def algo_momentum_breakout(i, high, low, close, atr_v):
    """TREND: Donchian breakout + ATR SL/TP. entry = ราคาทะลุ N-bar high/low (คำนวณจาก data ไม่ prediction)."""
    if i < BRK_WIN or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    hh = high[i - BRK_WIN:i].max(); ll = low[i - BRK_WIN:i].min()
    d = "BUY" if close[i] > hh else ("SELL" if close[i] < ll else None)
    if d is None:
        return None
    sl_pips = round(ATR_SL * atr_v[i] / POINT)
    return {"algo": "momentum_breakout", "dir": d, "sl_pips": sl_pips, "tp_pips": round(sl_pips * RR)}


def momentum_levels(i, high, low, close, atr_v):
    """ระดับ Donchian breakout สำหรับ **แท่งที่กำลังก่อตัว** (per-tick): ราคาต้องทะลุเพื่อเข้า.
    i = แท่งปิดล่าสุด → level = max/min ของ BRK_WIN แท่งปิดล่าสุด (จบที่ i). คืน None ถ้า data ไม่พอ.
    ใช้คู่ detect_regime (เข้าเฉพาะ TREND). SL/TP = ATR เดียวกับ algo_momentum_breakout."""
    if i < BRK_WIN or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    hh = high[i - BRK_WIN + 1:i + 1].max()
    ll = low[i - BRK_WIN + 1:i + 1].min()
    sl_pips = round(ATR_SL * atr_v[i] / POINT)
    return {"buy_level": float(hh), "sell_level": float(ll),
            "sl_pips": sl_pips, "tp_pips": round(sl_pips * RR)}


def algo_mean_reversion(i, close, atr_v):
    """[DEPRECATED จาก routing 07-19 — P2 OOS พิสูจน์ −EV both periods] คงไว้อ้างอิง backtest เท่านั้น.
    RANGE: z-score fade |s|>1.25 (Avellaneda) + OU half-life gate. entry = คำนวณจาก data (ไม่ prediction)."""
    if i < MR_WIN or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    w = close[i - MR_WIN + 1:i + 1]
    hl = ou_halflife(w)
    if hl > MR_HALFLIFE_MAX:                            # gate: reversion เร็วพอเท่านั้น
        return None
    m, sd = w.mean(), w.std()
    if sd == 0:
        return None
    s = (close[i] - m) / sd
    d = "BUY" if s < -S_ENTRY else ("SELL" if s > S_ENTRY else None)
    if d is None:
        return None
    # zone-based SL: วางเลย band ที่ S_STOP·std (entry ที่ z-extreme คือเป้า stop-hunt), floor ด้วย ATR กันแคบเกิน
    sl_price = m - S_STOP * sd if d == "BUY" else m + S_STOP * sd
    atr_floor = round(ATR_SL * atr_v[i] / POINT)
    sl_pips = max(round(abs(close[i] - sl_price) / POINT), atr_floor)
    tp_pips = max(round(abs(close[i] - m) / POINT), atr_floor)             # TP = กลับสู่ mean
    return {"algo": "mean_reversion", "dir": d, "s": round(float(s), 2),
            "sl_pips": sl_pips, "tp_pips": tp_pips,
            "max_hold_bars": max(1, round(TIME_STOP_K * hl))}   # OU time-stop: ไม่ revert ใน ~3×half-life → thesis ตาย (≥1 bar)


# ── strategy registry: regime → กลยุทธ์ที่เหมาะ (เลือกกลยุทธ์+เครื่องมือให้เหมาะแต่ละสภาพตลาด) ──
# แต่ละ strategy รับ context ครบ (high/low/close/atr/er/adx/volpct) → ใช้ "เครื่องมือ" ไหนก็ได้ที่เหมาะ regime นั้น.
# เพิ่มกลยุทธ์ต่อ regime ได้ที่นี่ — แต่ **ต้องผ่าน gauntlet (backtest OOS+null) ก่อน** ค่อยเสียบเข้า routing จริง.
# validated ปัจจุบัน: TREND→momentum เท่านั้น. RANGE/RISK-OFF/NEUTRAL = STAND-DOWN จนเจอกลยุทธ์ที่ผ่าน (mean_rev ตัดแล้ว).
def _strat_momentum(i, high, low, close, atr_v, er, adx_v, volpct):
    return algo_momentum_breakout(i, high, low, close, atr_v)


STRATEGIES = {
    "TREND": _strat_momentum,
    # "RANGE":    _strat_xxx,   # รอกลยุทธ์ range ใหม่ผ่าน gauntlet (mean_reversion −EV แล้ว)
    # "RISK-OFF": _strat_xxx,   # รอกลยุทธ์ป้องกัน/vol ที่ผ่าน
    # "NEUTRAL":  _strat_xxx,
}


def route(i, high, low, close, atr_v, er, adx_v, volpct):
    """SELECTION: regime → กลยุทธ์ที่เหมาะ (STRATEGIES) → signal | STAND-DOWN.
    (P3: AI/sentiment จากข่าวจะช่วยเลือก regime แทน detect_regime แบบ rule)."""
    regime = detect_regime(er[i], adx_v[i], volpct[i])
    strat = STRATEGIES.get(regime)
    return regime, (strat(i, high, low, close, atr_v, er, adx_v, volpct) if strat else None)


# ─────────────────────────── demo / sanity-check (ยังไม่ใช่ validation) ───────────────────────────
def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    p = os.path.join(_BASE, "data", f"xau_{tf}.json")
    if not os.path.exists(p):
        print(f"❌ ไม่มี data/xau_{tf}.json"); return
    rows = json.load(open(p))
    high = np.array([r[2] for r in rows]); low = np.array([r[3] for r in rows]); close = np.array([r[4] for r in rows])
    print("=" * 72)
    print(f"REGIME LIB — P1 (ONE algo/regime) | gold {tf.upper()} {len(close)} bars")
    print("=" * 72)
    er = efficiency_ratio(close); adx_v = adx(high, low, close); volpct = vol_percentile(close); atr_v = atr(high, low, close)
    from collections import Counter
    reg_count = Counter(); sig_count = Counter(); start = max(VOL_LOOKBACK, BRK_WIN, ER_WIN) + 2
    for i in range(start, len(close) - 1):
        regime, sig = route(i, high, low, close, atr_v, er, adx_v, volpct)
        reg_count[regime] += 1
        if sig:
            sig_count[sig["algo"]] += 1
    n = sum(reg_count.values())
    print("\n── regime distribution ──")
    for r in ("TREND", "RANGE", "RISK-OFF", "NEUTRAL"):
        print(f"  {r:>9}: {reg_count[r]:>6} ({reg_count[r]/n*100:4.0f}%)  → {REGIME_ALGO.get(r, 'STAND-DOWN')}")
    print("\n── signals (ONE algo/regime) ──")
    for a in ("momentum_breakout", "mean_reversion"):
        print(f"  {a:>18}: {sig_count[a]:>5}")
    print(f"\n  รวม signal: {sum(sig_count.values())} จาก {n} bars ({sum(sig_count.values())/n*100:.1f}%)")
    print("\n" + "=" * 72)
    print("✅ ONE algo/regime, deterministic (ไม่ prediction, ไม่มี AI). **ยังไม่ validate edge**.")
    print("⏭️ P2: backtest 2 algo นี้ต่อ regime (intrabar+cost+DSR+PBO+null) → คัดตัวรอด. HMM เสียบ RISK-OFF. AI(news) P3.")


if __name__ == "__main__":
    main()
