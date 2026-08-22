"""scripts/quant_metrics.py — tail-risk / robustness metrics (cway distill 08-22, [[cway-channel-distilled]]).

reusable helpers ต่อ R-series (ผลต่อไม้ = pnl/risk) หรือ daily-return series. เสริม t-stat/Sharpe เดิม
ด้วย downside-focused metrics (Sortino/CVaR) ที่ซื่อสัตย์กว่ากับ asymmetric SL/TP + SQN/Recovery/PF.
offline · 0 token · pure functions.
"""
import math

import numpy as np


def sharpe(r, ann=1.0):
    r = np.asarray(r, float); sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return (r.mean() / sd * math.sqrt(ann)) if sd > 0 else 0.0


def sortino(r, ann=1.0, target=0.0):
    """downside-deviation only (penalize ขาลงเท่านั้น) — ตรงกับ SL/TP asymmetric กว่า Sharpe."""
    r = np.asarray(r, float); dn = r[r < target] - target
    dd = math.sqrt((dn ** 2).mean()) if len(dn) else 0.0
    return (r.mean() / dd * math.sqrt(ann)) if dd > 0 else 0.0


def cvar(r, alpha=0.05):
    """Conditional VaR = ค่าเฉลี่ยของ tail แย่สุด alpha% (expected shortfall). คืนค่าลบ = ขาดทุนคาดหวังใน tail."""
    r = np.asarray(r, float)
    if len(r) < int(1 / alpha):
        return float(r.min()) if len(r) else 0.0
    q = np.quantile(r, alpha)
    tail = r[r <= q]
    return float(tail.mean()) if len(tail) else float(q)


def sqn(r):
    """System Quality Number (Van Tharp) = expectancy/σ × √N (cap N=100 กัน inflate). ≈ t-stat ของ expectancy."""
    r = np.asarray(r, float); n = len(r); sd = r.std(ddof=1) if n > 1 else 0.0
    return (r.mean() / sd * math.sqrt(min(n, 100))) if sd > 0 else 0.0


def profit_factor(r):
    r = np.asarray(r, float); g = r[r > 0].sum(); l = -r[r < 0].sum()
    return float(g / l) if l > 0 else float("inf") if g > 0 else 0.0


def max_drawdown(r):
    """max drawdown ของ equity curve (cumsum ของ R). คืนค่าบวก = ขนาด DD."""
    eq = np.cumsum(np.asarray(r, float)); peak = np.maximum.accumulate(eq)
    return float((peak - eq).max()) if len(eq) else 0.0


def recovery_factor(r):
    """net profit / max DD — สูง = ฟื้นตัวดีเทียบ DD."""
    r = np.asarray(r, float); dd = max_drawdown(r)
    return float(r.sum() / dd) if dd > 0 else float("inf") if r.sum() > 0 else 0.0


def panel(r, ann=252):
    """สรุปทุก metric เป็น dict — เรียกท้าย backtest แทน print เดี่ยว."""
    r = np.asarray(r, float); n = len(r)
    return {"n": n, "exp_R": float(r.mean()) if n else 0.0, "wr": round(float((r > 0).mean()) * 100, 1) if n else 0.0,
            "t": sqn(r) if n else 0.0, "sharpe": round(sharpe(r, ann), 2), "sortino": round(sortino(r, ann), 2),
            "cvar5": round(cvar(r, 0.05), 4), "sqn": round(sqn(r), 2),
            "profit_factor": round(profit_factor(r), 2), "max_dd": round(max_drawdown(r), 1),
            "recovery": round(recovery_factor(r), 2)}
