"""Smoke test หลัง refactor knobs → config.py (รัน: python scripts/smoke_test.py)
เช็ก: import + reload_config + guard 4 ตัวผ่าน _cfg.* + X_KEYWORDS ใหม่
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import config

config.reload_config()

from agents.decision_maker import (
    _counter_spike_reason,
    _news_bias_dir,
    _htf_fade_reason,
    _news_override_ok,
)

checks = {
    "floor=62":        config.MIN_TECHNICAL_CONFIDENCE == 62,
    "asian=72":        config.ASIAN_MIN_CONF == 72,
    "capital=150":     config.MIN_AI_EQUITY == 150,
    "counter-spike":   _counter_spike_reason("SELL", {"fast_move_pips": 600}) is not None,
    "news-bias=BUY":   _news_bias_dir({"bias": "BUY", "confidence": 70}, {"bias": "NEUTRAL"})[0] == "BUY",
    "htf-fade":        _htf_fade_reason("SELL", {"htf_zone": {"zone_type": "SUPPORT", "tf": "W1", "level": 4000}}) is not None,
    "news-override":   _news_override_ok("BUY", {"fast_move_pips": 600}, "BUY", 70)[0] is True,
    "kw>=15":          len(config.X_KEYWORDS) >= 15,
}

failed = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS" if ok else "FAIL"), k)
print("=" * 30)
print("SMOKE", "ALL PASS" if not failed else f"FAILED: {failed}")
sys.exit(0 if not failed else 1)
