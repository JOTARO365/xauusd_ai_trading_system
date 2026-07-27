"""agents/algo_selector.py — P1: hierarchical/empirical-Bayes shrinkage ต่อ (algo, symbol[, regime]).

แก้ "winner's curse / n เล็ก" (memory: 97% กำไรจากไม้เดียว n=6) — cell ที่ n น้อยถูก shrink เข้าหา global prior
แทนเชื่อ win-rate ดิบ. beta-binomial empirical Bayes (win-rate) + James-Stein-style shrink (exp_R).
DISPLAY/SHADOW-ONLY · 0 token · ไม่แตะ entry/gate (CORE INVARIANT). ดู docs/DESIGN_algo_selector.md P1.

⚠️ P1 = local real_fills เท่านั้น. cross-user (DB) + ESS correction = P1.5/P2.
"""
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

_MIN_CELLS_FOR_PRIOR = 2      # ต้องมี ≥2 cell ถึง fit prior; ไม่พอ → prior อ่อน (uniform)


def _fit_beta_prior(cells):
    """method-of-moments fit beta(a0,b0) จาก win-rate ของ cells (ถ่วง n). คืน (a0,b0). fallback uniform (1,1)."""
    obs = [(c["wins"] / c["n"], c["n"]) for c in cells if c["n"] > 0]
    if len(obs) < _MIN_CELLS_FOR_PRIOR:
        return 1.0, 1.0                                  # uniform prior (shrink เข้า 0.5 อ่อนๆ)
    tot = sum(n for _, n in obs)
    m = sum(p * n for p, n in obs) / tot                 # weighted mean win-rate
    var = sum(n * (p - m) ** 2 for p, n in obs) / tot    # weighted variance
    if var <= 1e-9 or not (0 < m < 1):
        return 1.0, 1.0
    k = m * (1 - m) / var - 1                             # concentration
    if k <= 0:
        return 1.0, 1.0
    return max(m * k, 0.1), max((1 - m) * k, 0.1)


def shrink(cells):
    """cells: [{algo, symbol, wins, n, exp_R, [regime]}]. คืน cells +shrunk_wr/shrunk_exp_R/raw_wr/prior_strength.
    n เล็ก → ดึงเข้า global; n ใหญ่ → เกือบเท่าเดิม. James-Stein: exp_R ดึงเข้า global mean ถ่วง k/(n+k)."""
    cells = [dict(c) for c in cells if c.get("n")]
    if not cells:
        return {"cells": [], "prior": None}
    a0, b0 = _fit_beta_prior(cells)
    k = a0 + b0                                           # prior strength (pseudo-count)
    tot = sum(c["n"] for c in cells)
    g_expR = sum((c.get("exp_R") or 0.0) * c["n"] for c in cells) / tot   # global mean exp_R (ถ่วง n)
    g_wr = a0 / k
    for c in cells:
        n, w = c["n"], c["wins"]
        c["raw_wr"] = round(100 * w / n, 1)
        c["shrunk_wr"] = round(100 * (w + a0) / (n + k), 1)               # beta-binomial posterior mean
        raw_e = c.get("exp_R") or 0.0
        c["shrunk_exp_R"] = round((n * raw_e + k * g_expR) / (n + k), 3)  # shrink เข้า global
        c["shrink_pull"] = round(c["shrunk_wr"] - c["raw_wr"], 1)         # ถูกดึงเท่าไหร่ (บอก overfit-risk)
        c["confident"] = n >= 30                                          # n ต่ำ = อย่าเพิ่งเชื่อ
    return {"cells": cells, "prior": {"a0": round(a0, 2), "b0": round(b0, 2),
                                      "global_wr": round(100 * g_wr, 1), "global_exp_R": round(g_expR, 3),
                                      "prior_strength_k": round(k, 1)}}


def _cells_from_real_edge():
    """สร้าง cells ต่อ (algo, symbol) จาก real_edge (local real_fills). regime split = P1.5 (features ยังว่าง)."""
    try:
        from agents import real_edge
        out = []
        for r in real_edge.build().get("rows", []):
            n = r.get("n") or 0
            if n <= 0:
                continue
            wr = r.get("wr")
            wins = round((wr or 0) / 100 * n) if wr is not None else 0
            out.append({"algo": r["algo_id"], "symbol": r["symbol"], "n": n, "wins": wins,
                        "exp_R": r.get("exp_R")})
        return out
    except Exception:
        return []


def build():
    """P1 shadow output: shrunk edge ต่อ (algo,symbol) จาก real_fills. DISPLAY-ONLY."""
    from datetime import datetime, timezone
    res = shrink(_cells_from_real_edge())
    res["ok"] = True
    res["generated"] = datetime.now(timezone.utc).isoformat()[:16] + "Z"
    res["note"] = "P1: local real_fills · shrinkage แก้ n เล็ก · cross-user(DB)+ESS = P1.5 · shadow-only"
    return res


if __name__ == "__main__":
    import json
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    print(json.dumps(build(), ensure_ascii=False, indent=2))
