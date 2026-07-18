#!/usr/bin/env python
"""fetch_risk_regime.py — compute regime ปัจจุบันจาก cross-asset HMM → data/risk_regime_now.json
สำหรับ dashboard /api/risk-regime. ดึง gold/VIX/DXY daily สด (Yahoo) → fit HMM → decode วันล่าสุด.

= risk CONTEXT (validated: ทำนาย forward vol) ไม่ใช่ entry signal. graceful: fail → เก็บไฟล์เดิม exit 0.
ตั้ง scheduler รายวัน (อยู่ใน refresh_dashboard_data.py แล้ว). 0 token (Yahoo ฟรี).
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_BASE, "data", "risk_regime_now.json")

try:
    import numpy as np
    from hmm_risk_regime import GaussianHMM, _yahoo, VOL_W, YR
except Exception as e:  # noqa: BLE001
    print(f"WARNING import: {e}", file=sys.stderr); sys.exit(0)

NAMES = ["RISK-ON", "NEUTRAL", "RISK-OFF", "S3", "S4"]


def main():
    try:
        g = _yahoo("GC=F"); v = _yahoo("%5EVIX"); x = _yahoo("DX-Y.NYB")
        dates = sorted(set(g) & set(v) & set(x))
        gold = np.array([g[d] for d in dates]); vix = np.array([v[d] for d in dates])
        dxy = np.array([x[d] for d in dates])
        gret = np.diff(np.log(gold)); dret = np.diff(np.log(dxy))
        gvol = np.array([gret[max(0, i - VOL_W):i].std() if i >= VOL_W else np.nan for i in range(len(gret))])
        vixL = vix[1:]
        m = ~np.isnan(gvol) & (gvol > 0)
        F = np.column_stack([gret[m], np.log(gvol[m]), np.log(vixL[m]), dret[m]])
        Fz = (F - F.mean(0)) / F.std(0)
        K = 3
        hmm = GaussianHMM(K).fit(Fz); s = hmm.decode(Fz)
        gr = gret[m]; vx = vixL[m]
        order = sorted(range(K), key=lambda k: vx[s == k].mean())   # RISK-ON→RISK-OFF
        rank = {k: r for r, k in enumerate(order)}
        cur = s[-1]
        cur_rank = rank[cur]
        gold_yr = gr[s == cur].mean() * YR * 100
        payload = {
            "ok": True,
            "regime": NAMES[cur_rank],
            "vix": round(float(vx[-1]), 1),
            "gold_ctx_yr": round(float(gold_yr), 1),   # ทองใน regime นี้ทำ %/ปี (contemporaneous)
            "freq_pct": round(float((s == cur).mean() * 100), 0),
            "as_of": dates[-1],
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        json.dump(payload, open(OUT, "w"), ensure_ascii=False, indent=2)
        print(json.dumps(payload, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: {e} — เก็บ risk_regime_now.json เดิม", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
