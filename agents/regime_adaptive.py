"""agents/regime_adaptive.py — weekly adaptive cycle (owner-approved disciplined version).

**ไม่จูน param** (พิสูจน์แล้ว: จูน-ตาม-recent พัง OOS+null; min-N = เดือน-ปี). adaptation = **ปิดกลยุทธ์ที่ decay**
(kill switch) + เสนอ owner จาก macro context. รันทุก 5 วันเทรด (=1 สัปดาห์, ตลาดปิด). ตัดสินจากหลายสัปดาห์สะสม.

- disabled_strategies()/is_enabled(): executors เช็คก่อนเข้า order (cache 60s)
- run_weekly_review(): monitor score จริง → ถ้า decay → auto-disable + log; + macro context (LLM-maintained
  macro_regime.md, 0 new token) → เสนอกลยุทธ์ → log logs/weekly_review.jsonl ให้ owner อนุมัติ (ไม่ auto-enable)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE = os.path.join(_BASE, "data", "regime_strategy_state.json")
_REVIEW_LOG = os.path.join(_BASE, "logs", "weekly_review.jsonl")
_cache = {"t": 0.0, "disabled": []}


def _iso():
    return datetime.now(timezone.utc).isoformat()


def disabled_strategies():
    """รายชื่อกลยุทธ์ที่ถูก disable (cache 60s — executors เรียกถี่)."""
    now = time.time()
    if now - _cache["t"] < 60:
        return _cache["disabled"]
    try:
        with open(_STATE, "r", encoding="utf-8") as f:
            _cache["disabled"] = json.load(f).get("disabled", [])
    except Exception:
        _cache["disabled"] = []
    _cache["t"] = now
    return _cache["disabled"]


def is_enabled(name):
    return name not in disabled_strategies()


def _set_state(disabled, reason):
    try:
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump({"disabled": disabled, "updated": _iso(), "reason": reason}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    _cache["t"] = 0.0        # force reload


def _macro_head(n=18):
    """macro context (LLM-maintained macro_regime.md — 0 new token) = "ช่วงเศรษฐกิจ" input."""
    p = os.path.join(_BASE, "agents", "prompts", "macro_regime.md")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return "".join(f.readlines()[:n]).strip()
    except Exception:
        return ""


def run_weekly_review():
    """เรียกทุก 5 วันเทรด (scheduled). monitor → auto-disable decay → log review. คืน summary."""
    sys.path.insert(0, os.path.join(_BASE, "scripts"))
    import regime_monitor as M
    trades = M.fetch_algo_trades()
    rep = M.analyze(trades)
    disabled = list(disabled_strategies())
    action = "none"
    dec = rep.get("decay")
    if dec and dec.get("decaying") and "momentum_breakout" not in disabled:
        disabled.append("momentum_breakout")
        _set_state(disabled, f"weekly decay: expR late {dec.get('late_expR')} < early {dec.get('early_expR')}")
        action = "AUTO-DISABLED momentum_breakout (decay)"
    suggestion = ("momentum เหมาะช่วง macro เทรนด์ชัด; ถ้า macro two-sided/uncertain → stand-down. "
                  "เพิ่มกลยุทธ์ใหม่ต้องผ่าน gauntlet ก่อน (owner อนุมัติ ไม่ auto-enable).")
    review = {"ts": _iso(), "n_trades": rep.get("n", 0), "verdict": rep.get("verdict"),
              "action": action, "disabled_now": disabled, "macro_context": _macro_head(), "suggestion": suggestion}
    try:
        os.makedirs(os.path.dirname(_REVIEW_LOG), exist_ok=True)
        with open(_REVIEW_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(review, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
    return review


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    r = run_weekly_review()
    print(f"weekly review: action={r['action']} | disabled={r['disabled_now']} | {r['verdict']}")
