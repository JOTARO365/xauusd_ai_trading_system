"""scripts/validate_cluster_filter.py — OFFLINE: algo จริงของเรา vs ML cluster-filter (gauntlet).

replay momentum_breakout (regime_lib — algo เดียวกับ live) + managed resolver (BE+trailing เหมือน live) บน
price จริง → คำนวณ cluster-quality (cluster_filter, KMeans/GMM) ต่อไม้ → เทียบว่า "กรองด้วย ML" ทำให้ exp_R
ดีขึ้นแบบ **ชนะ OOS + ทน null** ไหม. ถ้าไม่ชนะ = ไม่ผ่าน (เหมือน cluster-signal เดิมที่ตก).

data: default data/xau_h1.json (ทอง 12ปี offline). WTI → รันตอน MT5 เปิด: symbol=WTIUSD.
รัน:  & $PY scripts/validate_cluster_filter.py [logical] [method kmeans|gmm]
ยังไม่แตะ live — validate ก่อน wire เข้า shadow.
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
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "scripts"))

import regime_lib as R                                    # noqa: E402
from agents.shadow_resolve_managed import resolve_managed  # noqa: E402  (การจัดการเหมือน live: BE+trailing)
from scripts.cluster_filter import breakout_quality       # noqa: E402

_MIN_BARS = 520
MAX_HOLD = 48
_BRK = R.BRK_WIN


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def _load(logical):
    """คืน (high, low, close, times) จาก data offline หรือ MT5. list rows = [t,o,h,l,c,v]."""
    fp = os.path.join(_BASE, "data", f"{'xau' if logical.upper().startswith('XAU') else logical.lower()}_h1.json")
    if os.path.exists(fp):
        rows = json.load(open(fp, encoding="utf-8"))
        a = np.array(rows, float)
        return a[:, 2], a[:, 3], a[:, 4], a[:, 0].astype(np.int64), fp
    # fallback: MT5 (ตอน terminal เปิด)
    import MetaTrader5 as mt5
    from connectors.price_feed import get_ohlcv
    from connectors.pair_collector import _broker_map
    broker = _broker_map().get(logical, logical)
    rates = get_ohlcv(symbol=broker, timeframe=mt5.TIMEFRAME_H1, count=120000)
    if rates is None:
        raise SystemExit(f"no data for {logical} (MT5 ไม่ต่อ + ไม่มีไฟล์ offline)")
    return (rates["high"].astype(float), rates["low"].astype(float),
            rates["close"].astype(float), rates["time"].astype(np.int64), f"MT5:{broker}")


def replay(high, low, close, times, point=0.01, digits=2, cost_pips=20.0, method="kmeans"):
    """replay momentum_breakout จริง + resolve managed + cluster-quality ต่อไม้ (non-overlapping)."""
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    n = len(close)
    trades = []
    flat_until = -1
    for i in range(_MIN_BARS, n - 1):
        regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct, point=point)
        if not sig or sig.get("algo") != "momentum_breakout":
            continue
        if i <= flat_until:
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]),
               "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"], "bar_ts": _iso(times[i])}
        out = resolve_managed(rec, high, low, close, times, atr_v=atr_v, point=point,
                              cost_pips=cost_pips, max_hold_bars=MAX_HOLD, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":
            break
        # Donchian level ที่ถูกทะลุ (คู่กับ momentum_breakout)
        level = float(high[i - _BRK:i].max()) if rec["dir"] == "BUY" else float(low[i - _BRK:i].min())
        q = breakout_quality(high, low, close, i, level, rec["dir"], float(atr_v[i]), method=method)
        trades.append({"i": i, "t": int(times[i]), "R": out["realized_R"], "q": q})
        flat_until = i + out["bars_held"]
    return [t for t in trades if t["q"] is not None]


def _exp(trades):
    return (sum(t["R"] for t in trades) / len(trades)) if trades else 0.0


def _threshold_sweep(trades, feat, min_keep=0.35):
    """หา threshold ของ feat ที่ max exp_R (เก็บไม้ ≥ min_keep). คืน (thr, exp_kept, keep_frac)."""
    vals = sorted(set(t["q"][feat] for t in trades))
    best = (None, -9, 0.0)
    for thr in vals:
        kept = [t for t in trades if t["q"][feat] >= thr]
        if len(kept) < max(30, int(min_keep * len(trades))):
            continue
        e = _exp(kept)
        if e > best[1]:
            best = (thr, e, len(kept) / len(trades))
    return best


def analyze(trades, feats=("quality", "wall_strength", "clearance_atr")):
    raw = _exp(trades)
    n = len(trades)
    print(f"\n=== algo จริง (raw momentum, managed) ===")
    print(f"n={n} · exp_R raw = {raw:+.4f} · WR {100*sum(1 for t in trades if t['R']>0)/n:.1f}%")

    print(f"\n=== correlation feature ↔ realized_R (มีสัญญาณไหม) ===")
    Rs = np.array([t["R"] for t in trades])
    for f in feats:
        fv = np.array([t["q"][f] for t in trades])
        c = np.corrcoef(fv, Rs)[0, 1] if fv.std() > 0 else 0.0
        print(f"  {f:16s} corr={c:+.4f}")

    # OOS: split by time 70/30 → fit threshold บน train, apply บน test
    order = sorted(trades, key=lambda t: t["t"])
    cut = int(0.7 * n)
    tr, te = order[:cut], order[cut:]
    print(f"\n=== OOS (train {len(tr)} → test {len(te)}) · เกณฑ์ผ่าน: filtered ชนะ raw บน TEST ===")
    print(f"{'feat':16s} {'thr':>7s} {'keep%':>6s} {'train_exp':>10s} {'test_raw':>9s} {'test_filt':>10s} {'Δtest':>8s}")
    results = {}
    for f in feats:
        thr, e_tr, keep = _threshold_sweep(tr, f)
        if thr is None:
            print(f"  {f:16s}  (ไม่พอไม้)")
            continue
        te_kept = [t for t in te if t["q"][f] >= thr]
        te_raw, te_filt = _exp(te), (_exp(te_kept) if te_kept else 0.0)
        delta = te_filt - te_raw
        results[f] = (thr, delta, len(te_kept), len(te))
        print(f"  {f:16s} {thr:>7.3f} {100*keep:>5.0f}% {e_tr:>+10.4f} {te_raw:>+9.4f} {te_filt:>+10.4f} {delta:>+8.4f}")

    # null: permutation — สลับ quality ข้ามไม้ แล้วทำ OOS เดิม B รอบ → real Δ ชนะ null บ่อยแค่ไหน
    print(f"\n=== null test (permutation, B=200) · Δtest จริง vs สุ่ม ===")
    for f, (thr, delta, *_ ) in results.items():
        rng = np.random.RandomState(0)
        qv = np.array([t["q"][f] for t in order])
        null_deltas = []
        for _b in range(200):
            perm = rng.permutation(qv)
            teq = perm[cut:]
            keep_mask = teq >= thr
            te_R = np.array([t["R"] for t in te])
            nd = (te_R[keep_mask].mean() if keep_mask.any() else 0.0) - te_R.mean()
            null_deltas.append(nd)
        null_deltas = np.array(null_deltas)
        p = float((null_deltas >= delta).mean())
        verdict = "✅ ผ่าน" if (delta > 0 and p < 0.05) else "❌ ไม่ผ่าน"
        print(f"  {f:16s} Δtest={delta:+.4f} · null p={p:.3f} · {verdict}")


def main():
    logical = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    method = sys.argv[2] if len(sys.argv) > 2 else "kmeans"
    high, low, close, times, src = _load(logical)
    print(f"data: {src} · bars={len(close)} · method={method} · logical={logical}")
    trades = replay(high, low, close, times, method=method)
    if len(trades) < 60:
        print(f"ไม้น้อยเกิน ({len(trades)}) — validate ไม่ได้"); return
    analyze(trades)
    print("\n⚠️ นี่คือ in-sample gauntlet (OOS+null). ผ่าน = candidate → shadow ต่อ. ไม่ผ่าน = reject (อย่า wire live).")


if __name__ == "__main__":
    main()
