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


def _ess(n, n_accounts, rho=0.5):
    """effective sample size แก้ correlated users (P1.5): trade จาก account เดียวกัน = correlated.
    design-effect = 1+(avg_cluster−1)·ρ · ESS = N/deff. หลาย account → ESS→N; account เดียว → ESS ต่ำ."""
    if n <= 0:
        return 0.0
    k = max(1, int(n_accounts or 1))
    avg_cluster = n / k
    deff = 1.0 + (avg_cluster - 1.0) * rho
    return n / deff if deff > 0 else float(n)


def shrink(cells):
    """cells: [{algo, symbol, wins, n, exp_R, [regime, n_accounts]}]. shrink ตาม **effective-N (ESS)** ถ้ามี n_accounts.
    n เล็ก/correlated → ดึงเข้า global; n อิสระมาก → เกือบเท่าเดิม. James-Stein shrink exp_R เข้า global."""
    import os as _os
    rho = float(_os.getenv("ALGO_SEL_RHO") or 0.5)
    cells = [dict(c) for c in cells if c.get("n")]
    if not cells:
        return {"cells": [], "prior": None}
    # ESS ต่อ cell (ถ้ามี n_accounts) — ใช้เป็น effective count ใน shrink
    for c in cells:
        c["ess"] = round(_ess(c["n"], c.get("n_accounts"), rho), 1) if c.get("n_accounts") else c["n"]
    a0, b0 = _fit_beta_prior(cells)
    k = a0 + b0                                           # prior strength (pseudo-count)
    tot = sum(c["ess"] for c in cells)
    g_expR = sum((c.get("exp_R") or 0.0) * c["ess"] for c in cells) / tot
    g_wr = a0 / k
    for c in cells:
        n, w, ne = c["n"], c["wins"], c["ess"]
        w_eff = w * (ne / n) if n else 0                 # scale wins ตาม ESS (correlated → นับน้อยลง)
        c["raw_wr"] = round(100 * w / n, 1)
        c["shrunk_wr"] = round(100 * (w_eff + a0) / (ne + k), 1)          # beta-binomial บน effective count
        raw_e = c.get("exp_R") or 0.0
        c["shrunk_exp_R"] = round((ne * raw_e + k * g_expR) / (ne + k), 3)
        c["shrink_pull"] = round(c["shrunk_wr"] - c["raw_wr"], 1)
        c["confident"] = ne >= 30                                         # ใช้ ESS ไม่ใช่ raw n
    return {"cells": cells, "prior": {"a0": round(a0, 2), "b0": round(b0, 2),
                                      "global_wr": round(100 * g_wr, 1), "global_exp_R": round(g_expR, 3),
                                      "prior_strength_k": round(k, 1), "rho": rho}}


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


def _regime_bucket(trend):
    """map DB trend → regime bucket ง่ายๆ (BULLISH/BEARISH/NEUTRAL). None → NEUTRAL."""
    t = (str(trend or "")).upper()
    if "BULL" in t and "BEAR" not in t:
        return "BULLISH"
    if "BEAR" in t and "BULL" not in t:
        return "BEARISH"
    return "NEUTRAL"


def _cells_from_db(by_regime=True):
    """cross-user cells จาก DB (ทุก account). attribute algo จาก comment · regime จาก trend · +n_accounts (ESS).
    เฉพาะ CLOSED + มี comment (attribute ได้). คืน [] ถ้า DB ไม่ต่อ."""
    try:
        import config  # noqa
        from db.connection import get_client
        from agents.trade_recorder import _algo_of
        try:
            from db.reader import _norm
        except Exception:
            _norm = lambda s: s
        rows = (get_client().table("trades")
                .select("comment,account_login,symbol,pnl,trend,status")
                .eq("status", "CLOSED").limit(2000).execute().data)
    except Exception:
        return []
    agg = {}          # key → {n, wins, pnl_sum, accounts:set}
    for r in rows:
        cm = r.get("comment")
        if not cm:
            continue                                     # ไม่มี comment = attribute algo ไม่ได้ (ข้าม)
        algo = _algo_of(cm)
        sym = _norm(str(r.get("symbol") or ""))
        reg = _regime_bucket(r.get("trend")) if by_regime else "ALL"
        key = (algo, sym, reg)
        pnl = float(r.get("pnl") or 0.0)
        d = agg.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0, "acc": set()})
        d["n"] += 1
        d["wins"] += 1 if pnl > 0 else 0
        d["pnl"] += pnl
        if r.get("account_login"):
            d["acc"].add(r["account_login"])
    out = []
    for (algo, sym, reg), d in agg.items():
        out.append({"algo": algo, "symbol": sym, "regime": reg, "n": d["n"], "wins": d["wins"],
                    "n_accounts": len(d["acc"]) or 1,
                    "exp_R": round(d["pnl"] / d["n"], 2) if d["n"] else None})   # NB: pnl-avg (ไม่ใช่ R จริง — P2 normalize)
    return out


def build(source="db", by_regime=True):
    """P1.5 shadow output: shrunk edge cross-user + ESS + regime. source='db'(cross-user) / 'local'(real_fills). DISPLAY-ONLY."""
    from datetime import datetime, timezone
    cells = _cells_from_db(by_regime=by_regime) if source == "db" else []
    used = "db(cross-user)"
    if not cells:                                        # DB ไม่ต่อ/ว่าง → fallback local real_fills
        cells = _cells_from_real_edge()
        used = "local(real_fills)"
    res = shrink(cells)
    res["ok"] = True
    res["source"] = used
    res["generated"] = datetime.now(timezone.utc).isoformat()[:16] + "Z"
    res["note"] = ("P1.5: cross-user DB + ESS (correlated-user correction) + regime split · shrinkage แก้ n เล็ก · "
                   "exp_R=avg pnl (ยังไม่ R-normalize=P2) · shadow-only ไม่แตะ entry")
    return res


if __name__ == "__main__":
    import json
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    print(json.dumps(build(), ensure_ascii=False, indent=2))
