"""
Monte Carlo Simulation — XAUUSD AI Trading System v2
ทดสอบ robustness ของ strategy โดยไม่ใช้ trade history จริง
(ข้อมูลเก่ามาจาก v1 strategy ที่มี parameter ต่างออกไป — ใช้ assumptions แทน)

ใช้งาน:
    python -m backtest.monte_carlo                  # default config
    python -m backtest.monte_carlo --wr 0.42        # กำหนด win rate
    python -m backtest.monte_carlo --wr 0.45 --rr 2.2 --trades 300
    python -m backtest.monte_carlo --sweep          # sweep หลาย WR พร้อมกัน
"""
from __future__ import annotations

import argparse
import random
import statistics
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────

@dataclass
class SimConfig:
    win_rate:        float = 0.42    # assumed WR (breakeven at 2.0 R:R = 33%)
    rr_ratio:        float = 2.0     # R:R ratio (current min_rr_ratio)
    risk_pct:        float = 0.005   # risk per trade as fraction of equity (0.5%)
    avg_conf_scale:  float = 0.80    # avg confidence scale (conf ~65-80%)
    n_trades:        int   = 200     # trades to simulate per path
    n_simulations:   int   = 5_000   # number of Monte Carlo paths
    ruin_dd_pct:     float = 0.10    # drawdown % considered "ruin" (10%)


# ─────────────────────────────────────────────────────────────
#  Core simulation
# ─────────────────────────────────────────────────────────────

def _simulate_path(cfg: SimConfig, rng: random.Random) -> tuple[float, float]:
    """
    Simulate one sequence of n_trades trades.
    Returns (final_return_pct, max_drawdown_pct).
    """
    equity      = 1.0
    peak        = 1.0
    max_dd      = 0.0
    eff_risk    = cfg.risk_pct * cfg.avg_conf_scale   # effective risk per trade

    for _ in range(cfg.n_trades):
        if rng.random() < cfg.win_rate:
            equity *= 1.0 + eff_risk * cfg.rr_ratio
        else:
            equity *= 1.0 - eff_risk

        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    return (equity - 1.0), max_dd


def run(cfg: SimConfig | None = None) -> dict:
    """
    Run Monte Carlo simulation, return stats dict.

    Returns:
        {
          "config": cfg,
          "ev_per_trade_pct": float,         # expected value per trade
          "final_return": {"p5", "median", "p95"},
          "max_drawdown": {"median", "p95"},
          "prob_ruin":    float,              # P(max_dd > ruin_dd_pct)
          "prob_profit":  float,              # P(final return > 0)
          "prob_20pct":   float,              # P(final return > 20%)
          "paths":        int,
        }
    """
    if cfg is None:
        cfg = SimConfig()

    rng      = random.Random()
    returns  = []
    max_dds  = []

    for _ in range(cfg.n_simulations):
        ret, dd = _simulate_path(cfg, rng)
        returns.append(ret)
        max_dds.append(dd)

    returns.sort()
    max_dds.sort()
    n = len(returns)

    eff_risk = cfg.risk_pct * cfg.avg_conf_scale
    ev = cfg.win_rate * eff_risk * cfg.rr_ratio - (1 - cfg.win_rate) * eff_risk

    def _pct(x: float, n_: int, lst: list[float]) -> float:
        idx = min(int(x * n_), n_ - 1)
        return round(lst[idx] * 100, 2)

    return {
        "config":           cfg,
        "ev_per_trade_pct": round(ev * 100, 4),
        "final_return": {
            "p5":    _pct(0.05, n, returns),
            "median":_pct(0.50, n, returns),
            "p95":   _pct(0.95, n, returns),
        },
        "max_drawdown": {
            "median": _pct(0.50, n, max_dds),
            "p95":    _pct(0.95, n, max_dds),
        },
        "prob_ruin":   round(sum(1 for d in max_dds if d >= cfg.ruin_dd_pct) / n * 100, 1),
        "prob_profit": round(sum(1 for r in returns if r > 0)                / n * 100, 1),
        "prob_20pct":  round(sum(1 for r in returns if r > 0.20)             / n * 100, 1),
        "paths":       n,
    }


# ─────────────────────────────────────────────────────────────
#  Pretty print
# ─────────────────────────────────────────────────────────────

def _print_result(res: dict) -> None:
    cfg = res["config"]
    print(f"\n{'='*58}")
    print("  Monte Carlo — XAUUSD AI Trading System v2")
    print(f"{'='*58}")
    print(
        f"  WR={cfg.win_rate*100:.1f}% | R:R={cfg.rr_ratio} | "
        f"Risk={cfg.risk_pct*100:.2f}% | Scale={cfg.avg_conf_scale:.2f}"
    )
    print(f"  {cfg.n_trades} trades × {cfg.n_simulations:,} paths")
    print(f"  Expected value/trade: {res['ev_per_trade_pct']:+.4f}%")
    print(f"{'-'*58}")

    fr = res["final_return"]
    dd = res["max_drawdown"]
    print(f"  Final return   — p5: {fr['p5']:+.1f}% | median: {fr['median']:+.1f}% | p95: {fr['p95']:+.1f}%")
    print(f"  Max drawdown   — median: {dd['median']:.1f}% | p95: {dd['p95']:.1f}%")
    print(f"{'-'*58}")
    print(f"  P(ruin >{cfg.ruin_dd_pct*100:.0f}% DD):  {res['prob_ruin']:.1f}%")
    print(f"  P(profitable):   {res['prob_profit']:.1f}%")
    print(f"  P(return >20%):  {res['prob_20pct']:.1f}%")
    print(f"{'='*58}\n")


def _print_sweep() -> None:
    """ทดสอบ WR หลายค่าพร้อมกัน เพื่อเห็น sensitivity"""
    cfgs = [SimConfig(win_rate=wr) for wr in [0.35, 0.38, 0.40, 0.42, 0.45, 0.48, 0.50]]
    print(f"\n{'='*78}")
    print("  WR Sweep — XAUUSD v2 | R:R=2.0 | Risk=0.5% | Scale=0.80 | 200 trades × 5,000 paths")
    print(f"{'='*78}")
    print(f"  {'WR':>5} | {'EV/trade':>9} | {'Ret med':>8} | {'DD p95':>7} | {'P(ruin)':>8} | {'P(+)':>6} | {'P(>20%)':>8}")
    print(f"  {'-'*5}-+-{'-'*9}-+-{'-'*8}-+-{'-'*7}-+-{'-'*8}-+-{'-'*6}-+-{'-'*8}")
    for cfg in cfgs:
        r = run(cfg)
        fr = r["final_return"]
        dd = r["max_drawdown"]
        print(
            f"  {cfg.win_rate*100:>4.0f}% | {r['ev_per_trade_pct']:>+8.4f}% | "
            f"{fr['median']:>+7.1f}% | {dd['p95']:>6.1f}% | "
            f"{r['prob_ruin']:>7.1f}% | {r['prob_profit']:>5.1f}% | {r['prob_20pct']:>7.1f}%"
        )
    print(f"{'='*78}\n")
    print("  Breakeven WR at R:R 2.0 = 33.3% — ทุก row ด้านบนควรมี EV > 0")
    print("  P(ruin) < 5% = acceptable risk | < 10% = borderline | > 20% = high risk\n")


# ─────────────────────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monte Carlo simulation for XAUUSD v2 strategy")
    parser.add_argument("--wr",     type=float, default=0.42, help="Win rate (default 0.42)")
    parser.add_argument("--rr",     type=float, default=2.0,  help="R:R ratio (default 2.0)")
    parser.add_argument("--risk",   type=float, default=0.5,  help="Risk %% per trade (default 0.5)")
    parser.add_argument("--scale",  type=float, default=0.80, help="Avg confidence scale (default 0.80)")
    parser.add_argument("--trades", type=int,   default=200,  help="Trades per path (default 200)")
    parser.add_argument("--sims",   type=int,   default=5000, help="Number of simulations (default 5000)")
    parser.add_argument("--ruin",   type=float, default=10.0, help="Ruin drawdown threshold %% (default 10)")
    parser.add_argument("--sweep",  action="store_true",      help="Run WR sweep instead of single config")
    args = parser.parse_args()

    if args.sweep:
        _print_sweep()
    else:
        cfg = SimConfig(
            win_rate       = args.wr,
            rr_ratio       = args.rr,
            risk_pct       = args.risk / 100,
            avg_conf_scale = args.scale,
            n_trades       = args.trades,
            n_simulations  = args.sims,
            ruin_dd_pct    = args.ruin / 100,
        )
        result = run(cfg)
        _print_result(result)
