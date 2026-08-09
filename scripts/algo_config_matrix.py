"""scripts/algo_config_matrix.py — รายงาน config ต่อ (algo × คู่): global vs per-pair override (user 08-09).

ตอบ "config แต่ละ algo ต่างกันแค่ไหนในแต่ละคู่": โชว์ baseline global + override ที่มีจริง
(TF, lookback, macro driver, session, SL/RR). per-pair = **structural เท่านั้น** (ไม่ tune edge param = กัน curve-fit).
read-only. 0 token. standalone: python scripts/algo_config_matrix.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))


def _parse_override(raw):
    """'algo:PAIR=val;...' → {(algo,pair): val}."""
    out = {}
    for part in str(raw or "").split(";"):
        part = part.strip()
        if ":" in part and "=" in part:
            key, val = part.split("=", 1)
            algo, pair = key.split(":", 1)
            out[(algo.strip(), pair.strip())] = val.strip()
    return out


def run():
    from dotenv import load_dotenv
    load_dotenv(override=True)
    import config as c
    import regime_lib as R
    from agents import algo_registry as reg

    tf_ov = _parse_override(getattr(c, "ALGO_TF_OVERRIDE", ""))
    lb_ov = _parse_override(getattr(c, "ALGO_LB_OVERRIDE", ""))
    universe = list(reg.UNIVERSE)
    sess = getattr(c, "CONF15M_SESSION", "13-21")

    # baseline global params ต่อ algo (จาก registry/regime_lib)
    BASE = {
        "regime_momentum":     {"TF": "H1", "donchian": R.BRK_WIN, "SL": "%.1f×ATR" % R.ATR_SL, "RR": R.RR, "gate": "TREND"},
        "regime_momentum_fvg": {"TF": "H1", "donchian": R.BRK_WIN, "SL": "%.1f×ATR" % R.ATR_SL, "RR": R.RR, "gate": "TREND+FVG6"},
        "macro_momentum":      {"TF": "H4", "donchian": 20, "SL": "1.5×ATR", "RR": 2.0, "gate": "macro-confirm"},
        "confluence_15m":      {"TF": "M15", "donchian": 12, "SL": "1.0×ATR", "RR": 2.0, "gate": "H1+H4+vol+session"},
        "tsmom_d1":            {"TF": "D1", "lookbacks": "21/63/126", "SL": "3.0×ATR", "gate": "confirm21"},
        "sweep_reversal":      {"TF": "H1", "SL": "wick+0.5×ATR", "RR": 1.5, "gate": "NEUTRAL/RANGE"},
        "mean_reversion":      {"TF": "H1", "win": R.MR_WIN, "SL": "z%.1fσ" % R.S_STOP, "gate": "RANGE+OU"},
    }

    print("=" * 90)
    print("ALGO CONFIG MATRIX — global baseline + per-pair override (structural)")
    print("=" * 90)
    print("\n[1] BASELINE (เหมือนกันทุกคู่ — ไม่ tune ต่อคู่ = กัน curve-fit):")
    for a, p in BASE.items():
        print("  %-20s %s" % (a, " · ".join("%s=%s" % (k, v) for k, v in p.items())))

    print("\n[2] PER-PAIR OVERRIDE ที่มีจริง (structural เท่านั้น):")
    print("\n  (a) macro driver (regime_lib.MACRO_MAP) — macro_momentum ต่อคู่:")
    for lg in universe:
        m, s = R.macro_for(lg)
        tag = "" if (m, s) == ("EURUSD", 1) else "  ← ต่างจาก default"
        print("      %-8s → %s (sign %+d)%s" % (lg, m, s, tag))

    print("\n  (b) session gate (confluence_15m): XAU=%s UTC · อื่นๆ=24/7" % sess)

    print("\n  (c) timeframe override (ALGO_TF_OVERRIDE):")
    if tf_ov:
        for (a, pr), v in tf_ov.items():
            print("      %-20s %-8s → TF %s  (default %s)" % (a, pr, v, BASE.get(a, {}).get("TF", "?")))
    else:
        print("      (ไม่มี)")

    print("\n  (d) lookback override (ALGO_LB_OVERRIDE):")
    if lb_ov:
        for (a, pr), v in lb_ov.items():
            print("      %-20s %-8s → lookbacks %s  (default %s)" % (a, pr, v, BASE.get(a, {}).get("lookbacks", "?")))
    else:
        print("      (ไม่มี)")

    print("\n  (e) auto per-symbol (ไม่ใช่ config แต่ปรับเอง): point/pip scale · ATR SL (ปรับตาม vol แต่ละคู่)")

    print("\n" + "=" * 90)
    print("สรุป: edge param (donchian/SL×ATR/RR/lookback core) = GLOBAL เหมือนกันทุกคู่ (กัน curve-fit).")
    print("ต่างต่อคู่เฉพาะ STRUCTURAL: macro driver, session, TF/LB override (BTC=H4, silver lookback สั้น).")
    print("=" * 90)


if __name__ == "__main__":
    run()
