"""scripts/survival_sim.py — Monte-Carlo survival test ของระบบ 5 ปีข้างหน้า (user 08-09).

คำถาม: ระบบนี้ (roster ทอง-คอมเพล็กซ์ LIVE) เริ่มด้วยทุน X บาท จะ "รอด" 5 ปีข้างหน้าแค่ไหน
ภายใต้ scenario เศรษฐกิจที่นักลงทุน/กองทุนโลกมองว่าน่าจะเกิดมากสุด ณ 2026?

วิธี (ตามที่ user เลือก):
- price path: block-bootstrap return ทองจริง (เก็บ fat-tails/autocorr/gap) + overlay drift/vol ต่อ scenario
- regime-switch: Markov chain 6 scenario (persistence ~ regime กินเวลาหลายเดือน) ตลอด 5 ปี
- รันระบบจริงบน path สังเคราะห์: trend-breakout 2 sleeve (ช้า/เร็ว) + sentiment-gated direction
- money model บาทจริง = ตัวชี้เป็นตาย: min-lot 0.01 floor · structural SL กว้าง · margin · stop-out ruin
                                        · force-close lock double (<20k) · per-algo cap · fixed-fractional
- Monte-Carlo N path × 4 tier ทุน (1000/3000/20000/50000) → survival% · ruin-time · equity dist

sentiment: ระบบ flip buy/sell ตามข่าว/regime — โมเดลเป็น sentiment เอียงตาม scenario drift (แม่น ~62%)
เข้าเฉพาะทิศที่ sentiment หนุน (breakout เป็น trigger, sentiment เลือกฝั่ง = คง minimal-AI invariant).

สโคป (ชัดเจน ไม่ปิดบัง): sleeve ทอง directional = ตัวชี้เป็นตายเรื่องทุน (structural SL ทองที่ min-lot).
BTC + FX เดี่ยว + pairs (market-neutral) ตัดออก — เพิ่มแค่จำนวนไม้/ลดความเสี่ยง ไม่ใช่ตัวฆ่าพอร์ต.
ผล = lower-bound ความอยู่รอดของ core directional.

⚠️ ไม่ใช่คำทำนายราคา — เป็น stress-test เชิงสถิติว่า money mechanics + edge บาง จะทน tail 5 ปีไหวไหม.
base = 4H bar (6/วัน) เพื่อความเร็ว. 0 token. standalone: python scripts/survival_sim.py [--paths N]
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ── constants (วัดจริงจาก MT5 08-09) ──
THB_PER_USD_PER_LOT = 3305.7          # กำไร/ขาดทุน บาท ต่อ $1 ราคาเคลื่อน ต่อ 1.0 lot ทอง
MARGIN_PER_LOT_THB = 14353.4          # margin บาท ต่อ 1.0 lot (1:1000)
MIN_LOT = 0.01
LOT_STEP = 0.01
MAX_LOT = 0.30
GOLD_PX0 = 4342.0
BARS_PER_DAY = 6                       # base = 4H bar
DAYS_PER_YEAR = 260
YEARS = 5
BARS_PER_YEAR = BARS_PER_DAY * DAYS_PER_YEAR

RISK_PCT = 0.005                      # fixed-fractional 0.5%/ไม้ (over-risk อัตโนมัติเมื่อโดน min-lot floor)
FORCE_CLOSE_MIN_CAP = 20000.0        # < นี้ = lock double (roll baseline); ≥ = ปล่อยวิ่ง
FORCE_CLOSE_PCT = 100.0
SENTIMENT_ACC = 0.62                  # sentiment/ข่าว อ่านทิศ regime ถูก ~62% (edge บางจริง ไม่ perfect)

# ── scenarios (อิง consensus กองทุน/นักลงทุนโลก 2026 · gold-centric · 5-yr) ──
SCENARIOS = {
    "soft_landing":  {"prob": 0.35, "drift": 0.06, "vol": 0.14, "type": "mixed"},
    "recession":     {"prob": 0.20, "drift": 0.15, "vol": 0.20, "type": "trend"},   # safe-haven bid
    "stagflation":   {"prob": 0.12, "drift": 0.20, "vol": 0.22, "type": "trend"},
    "yield_spike":   {"prob": 0.13, "drift": -0.12, "vol": 0.24, "type": "trend"},  # ทองร่วง
    "chop_range":    {"prob": 0.15, "drift": 0.02, "vol": 0.10, "type": "range"},   # ฆ่า momentum
    "tail_crisis":   {"prob": 0.05, "drift": 0.10, "vol": 0.32, "type": "crash"},
}
_SC_KEYS = list(SCENARIOS.keys())
_SC_PROB = np.array([SCENARIOS[k]["prob"] for k in _SC_KEYS]); _SC_PROB /= _SC_PROB.sum()
_DRIFT = np.array([SCENARIOS[k]["drift"] for k in _SC_KEYS])
_VOL = np.array([SCENARIOS[k]["vol"] for k in _SC_KEYS])
_ISCRASH = np.array([SCENARIOS[k]["type"] == "crash" for k in _SC_KEYS])
_REGIME_DAYS = 150                    # regime เฉลี่ยกินเวลา ~150 วันเทรด


def _load_returns():
    """log-return ทองจริง 4H (block-bootstrap source). fallback Gaussian ถ้าไม่มี MT5."""
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            r = mt5.copy_rates_from_pos("GOLD#", mt5.TIMEFRAME_H4, 0, 12000)
            mt5.shutdown()
            if r is not None and len(r) > 500:
                lr = np.diff(np.log(r["close"].astype(float)))
                return lr[np.isfinite(lr)]
    except Exception:
        pass
    print("  [warn] ไม่มี MT5 → Gaussian returns (fat-tails หาย, ผลดูดีกว่าจริง)")
    return None


def _roll_prev_ext(price, win):
    """hi[i]=max(price[i-win:i]), lo[i]=min(...) แบบ vectorized (sliding-window). ก่อน win = nan."""
    n = len(price)
    hi = np.full(n, np.nan); lo = np.full(n, np.nan)
    if n <= win:
        return hi, lo
    sw = np.lib.stride_tricks.sliding_window_view(price, win)   # len n-win+1, sw[j]=price[j:j+win]
    m = n - win
    hi[win:] = sw[:m].max(axis=1)                               # hi[i]=max(price[i-win:i]) สำหรับ i in [win,n)
    lo[win:] = sw[:m].min(axis=1)
    return hi, lo


def _gen_path(rng, hist_lr):
    """สร้าง price + sentiment path 5 ปี (4H base). vectorized. คืน (price, sent) ยาว n."""
    n_days = YEARS * DAYS_PER_YEAR
    hpd = BARS_PER_DAY
    # regime รายวัน (Markov)
    reg = np.empty(n_days, dtype=int)
    cur = rng.choice(len(_SC_KEYS), p=_SC_PROB); p_sw = 1.0 / _REGIME_DAYS
    switch = rng.random(n_days) < p_sw
    draws = rng.choice(len(_SC_KEYS), size=n_days, p=_SC_PROB)
    for d in range(n_days):
        if switch[d]:
            cur = draws[d]
        reg[d] = cur
    # sentiment รายวัน (เอียงตาม drift regime, แม่น ~ACC)
    tb = np.where(_DRIFT[reg] > 0.04, 1, np.where(_DRIFT[reg] < -0.04, -1, 0))
    correct = rng.random(n_days) < SENTIMENT_ACC
    sent_day = np.where(correct, tb, rng.choice([-1, 0, 1], size=n_days))
    # block-bootstrap returns (1 วัน = 1 block; เก็บ autocorr ในวัน) + overlay
    if hist_lr is not None:
        bmu, bsd = float(hist_lr.mean()), float(hist_lr.std()) + 1e-12
        starts = rng.integers(0, len(hist_lr) - hpd, size=n_days)
        seg = np.stack([hist_lr[s:s + hpd] for s in starts])   # (n_days, hpd)
        seg = (seg - bmu) / bsd                                 # standardize
    else:
        seg = rng.standard_normal((n_days, hpd))
    tgt_mu = (_DRIFT[reg] / BARS_PER_YEAR)[:, None]
    tgt_sd = (_VOL[reg] / np.sqrt(BARS_PER_YEAR))[:, None]
    # tail gap: วัน crash บางวันมี jump
    crash_day = _ISCRASH[reg] & (rng.random(n_days) < 0.03)
    if crash_day.any():
        jcol = rng.integers(0, hpd, size=n_days)
        jmag = rng.choice([-1, 1], size=n_days) * rng.uniform(4, 8, size=n_days)
        for d in np.where(crash_day)[0]:
            seg[d, jcol[d]] += jmag[d]
    ret = (seg * tgt_sd + tgt_mu).ravel()
    price = GOLD_PX0 * np.exp(np.cumsum(ret))
    sent = np.repeat(sent_day, hpd)
    return price, sent


# sleeve params (4H units): (breakout_win, max_hold, rr, structural_lookback)
_SLEEVES = [(30, 40, 2.0, 12), (8, 16, 2.0, 8)]   # ช้า(trend) · เร็ว(intraday breakout)


def _run_system(price, sent, start_equity, ext, force_close=True):
    """รัน 2 sleeve breakout + sentiment gate + money model บาท. ext = pre-computed (hi,lo) ต่อ sleeve.
    force_close: ปิดตะกร้าลอยทั้งหมดเมื่อ floating equity ≥ baseline×2 (ระหว่างทุน < เกณฑ์) = lock กำไร."""
    n = len(price)
    equity = start_equity; baseline = start_equity; peak = start_equity
    maxdd = 0.0; ruined = False; ruin_bar = None; n_trades = 0; wins = 0; sumR = 0.0; n_forced = 0
    ruin_floor = MARGIN_PER_LOT_THB * MIN_LOT           # ต่ำกว่านี้ = stop-out
    opens = [None, None]                                 # open trade ต่อ sleeve (cap 1 = per-algo×pair)
    start = max(s[0] for s in _SLEEVES) + 1

    def _float_pnl(px):                                  # กำไร/ขาดทุนลอยของ position ที่เปิดอยู่ (บาท)
        tot = 0.0
        for op in opens:
            if op is not None:
                tot += ((px - op["entry"]) * op["dir"]) * op["lot"] * THB_PER_USD_PER_LOT
        return tot

    for i in range(start, n):
        px = price[i]
        # ── force-close ตะกร้าลอย: floating equity ≥ baseline×2 (ทุน < เกณฑ์) → ปิดหมด lock ──
        if force_close and equity < FORCE_CLOSE_MIN_CAP and any(o is not None for o in opens):
            fe = equity + _float_pnl(px)
            if fe >= baseline * (1 + FORCE_CLOSE_PCT / 100):
                for k, op in enumerate(opens):
                    if op is None:
                        continue
                    r_mult = ((px - op["entry"]) * op["dir"]) / op["risk_px"]
                    equity += r_mult * op["lot"] * op["risk_px"] * THB_PER_USD_PER_LOT
                    n_trades += 1; sumR += r_mult; wins += (r_mult > 0); opens[k] = None
                baseline = equity; n_forced += 1
                peak = max(peak, equity); dd = (peak - equity) / peak if peak > 0 else 0
                maxdd = max(maxdd, dd)
        # ── manage ──
        for k, (brk, mh, rr, lb) in enumerate(_SLEEVES):
            op = opens[k]
            if op is None:
                continue
            hit = None
            if op["dir"] == 1:
                if px <= op["sl"]:   hit = op["sl"]
                elif px >= op["tp"]: hit = op["tp"]
            else:
                if px >= op["sl"]:   hit = op["sl"]
                elif px <= op["tp"]: hit = op["tp"]
            if hit is None and i >= op["expiry"]:
                hit = px
            if hit is None:
                continue
            r_mult = ((hit - op["entry"]) * op["dir"]) / op["risk_px"]
            equity += r_mult * op["lot"] * op["risk_px"] * THB_PER_USD_PER_LOT
            n_trades += 1; sumR += r_mult; wins += (r_mult > 0); opens[k] = None
            if equity <= ruin_floor:
                ruined = True; ruin_bar = i; equity = max(equity, 0.0); break
            peak = max(peak, equity); dd = (peak - equity) / peak if peak > 0 else 0
            maxdd = max(maxdd, dd)
        if ruined:
            break
        # ── entries ──
        s = sent[i]
        for k, (brk, mh, rr, lb) in enumerate(_SLEEVES):
            if opens[k] is not None:
                continue
            hi, lo = ext[k][0][i], ext[k][1][i]
            if not (np.isfinite(hi) and np.isfinite(lo)):
                continue
            direction = 1 if px > hi else (-1 if px < lo else 0)
            if direction == 0:
                continue
            if s != 0 and direction != s:               # sentiment gate: เข้าเฉพาะทิศที่ข่าว/regime หนุน
                continue
            seg = price[max(0, i - lb):i + 1]
            slp = seg.min() if direction == 1 else seg.max()
            risk_px = (px - slp) if direction == 1 else (slp - px)
            if risk_px <= 0.5:
                continue
            tp = px + direction * rr * risk_px
            risk_thb = RISK_PCT * equity
            loss_minlot = MIN_LOT * risk_px * THB_PER_USD_PER_LOT
            if risk_thb >= loss_minlot:
                lot = np.floor(risk_thb / (risk_px * THB_PER_USD_PER_LOT) / LOT_STEP) * LOT_STEP
                lot = min(max(lot, MIN_LOT), MAX_LOT)
            else:
                lot = MIN_LOT                           # บังคับ min-lot → over-risk (จุดตายทุนเล็ก)
            if equity < lot * MARGIN_PER_LOT_THB:       # margin ไม่พอ
                continue
            opens[k] = {"entry": px, "sl": slp, "tp": tp, "dir": direction,
                        "risk_px": risk_px, "lot": lot, "expiry": i + mh}
    survived = (not ruined) and equity > ruin_floor
    return {"survived": survived, "ruin_year": (ruin_bar / BARS_PER_YEAR) if ruin_bar else None,
            "final_eq": equity, "maxdd": maxdd, "n_trades": n_trades, "n_forced": n_forced,
            "wr": (wins / n_trades * 100) if n_trades else None, "exp_R": (sumR / n_trades) if n_trades else None}


def run(paths=600, tiers=(1000, 3000, 20000, 50000), seed=12345):
    hist = _load_returns()
    rng = np.random.default_rng(seed)
    print("=" * 78)
    print("MONTE-CARLO SURVIVAL · ระบบทอง directional · 5 ปีข้างหน้า · %d paths" % paths)
    print("scenarios:", ", ".join("%s %.0f%%" % (k, SCENARIOS[k]["prob"] * 100) for k in _SC_KEYS))
    print("money: min-lot %.2f · SL structural · margin/stop-out · force-close<%.0f · risk %.2f%%/ไม้ · sentiment %.0f%%acc"
          % (MIN_LOT, FORCE_CLOSE_MIN_CAP, RISK_PCT * 100, SENTIMENT_ACC * 100))
    print("=" * 78)
    acc = {(c, fc): {"fin": [], "surv": 0, "dd": [], "ntr": [], "expR": [], "wr": []}
           for c in tiers for fc in (True, False)}
    for _ in range(paths):                              # gen path ครั้งเดียว รันทุก tier × force-close on/off
        price, sent = _gen_path(rng, hist)
        ext = [_roll_prev_ext(price, s[0]) for s in _SLEEVES]
        for c in tiers:
            for fc in (True, False):
                r = _run_system(price, sent, float(c), ext, force_close=fc)
                a = acc[(c, fc)]; a["fin"].append(r["final_eq"]); a["dd"].append(r["maxdd"]); a["ntr"].append(r["n_trades"])
                if r["exp_R"] is not None:
                    a["expR"].append(r["exp_R"]); a["wr"].append(r["wr"])
                if r["survived"]:
                    a["surv"] += 1
    print("A/B: force-close ON (ปิดตะกร้าลอย +100% ทุน<20k) vs OFF\n")
    print("%-9s %-10s %7s %10s %9s %10s %7s" % ("ทุนเริ่ม", "force-close", "รอด%", "median฿", "p10฿", "p90฿", "medDD%"))
    results = {}
    for c in tiers:
        for fc in (True, False):
            a = acc[(c, fc)]; fin = np.array(a["fin"])
            row = {"survive_pct": round(a["surv"] / paths * 100, 1),
                   "median": round(float(np.median(fin))), "p10": round(float(np.percentile(fin, 10))),
                   "p90": round(float(np.percentile(fin, 90))), "med_dd": round(float(np.median(a["dd"])) * 100, 1)}
            results[(c, fc)] = row
            print("%-9d %-10s %6.1f%% %10d %9d %10d %6.1f%%" % (
                c, "ON" if fc else "OFF", row["survive_pct"], row["median"], row["p10"], row["p90"], row["med_dd"]))
        d = results[(c, True)]["survive_pct"] - results[(c, False)]["survive_pct"]
        print("          → force-close ช่วย survival %+.1f pp\n" % d)
    print("=" * 78)
    ref = acc[(max(tiers), True)]
    if ref["expR"]:
        print("realized edge (tier %d): exp_R %.3f · WR %.1f%%  ← เทียบ backtest จริง ~0.04-0.16"
              % (max(tiers), float(np.mean(ref["expR"])), float(np.mean(ref["wr"]))))
    print("\nสโคป: sleeve ทอง directional (structural SL) เท่านั้น. BTC/FX/pairs ตัดออก.")
    print("ตีความ: survival ขับด้วย min-lot vs ทุน — ไม้ทองแพ้ที่ทุนเล็ก = ล้างทันที.")
    return results


if __name__ == "__main__":
    p = 600
    if "--paths" in sys.argv:
        p = int(sys.argv[sys.argv.index("--paths") + 1])
    run(paths=p)
