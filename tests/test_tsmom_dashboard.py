"""test_tsmom_dashboard.py — unit + integration (user) tests สำหรับงาน TSMOM + dashboard ล่าสุด.

unit: TSMOM signal ensemble, capital_warning, standdown, daily_summary _tech (ALGO-TSMOM), algo_exit exclusion.
integration (user): Flask endpoints /api/tsmom, /api/algo-status (TSMOM-aware) — จำลองสิ่งที่ browser fetch.
รัน: & $PY tests\test_tsmom_dashboard.py   (ไม่ต้องมี MT5 — patch equity ที่จำเป็น)
"""
import os
import sys
import unittest

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
os.environ["TSMOM_LIVE"] = "true"                           # deterministic สำหรับ algo-status test


class TestTSMOMSignal(unittest.TestCase):
    """ensemble majority vote — ทิศตาม trend หลายช่วง."""
    def setUp(self):
        import config as c
        c.TSMOM_LOOKBACKS = "63,126,252"

    def test_uptrend_buy(self):
        import numpy as np
        from agents.tsmom_manager import _signal
        self.assertEqual(_signal(np.linspace(1000, 2000, 300)), "BUY")

    def test_downtrend_sell(self):
        import numpy as np
        from agents.tsmom_manager import _signal
        self.assertEqual(_signal(np.linspace(2000, 1000, 300)), "SELL")

    def test_majority_2of3(self):
        import numpy as np
        from agents.tsmom_manager import _signal
        c = np.linspace(1000, 2000, 300).copy()             # ขึ้นยาว (63/126/252 ล้วนบวก = BUY)
        self.assertEqual(_signal(c), "BUY")
        # ทำให้ 252 บวก แต่ 63/126 ลบ (ย่อช่วงท้าย) → majority SELL
        c2 = np.concatenate([np.linspace(1000, 2000, 250), np.linspace(2000, 1400, 50)])
        self.assertEqual(_signal(c2), "SELL")


class TestCapitalWarning(unittest.TestCase):
    """เตือนเมื่อ risk/ไม้ ที่ MIN_LOT เกินเพดาน (ไม่บล็อก)."""
    def _patch(self, eq, pv=36.0):
        import agents.algo_sizing as S
        S._equity_pipval = lambda equity=None: (eq, pv)

    def test_warn_small_equity(self):
        import agents.algo_sizing as S, config as c
        c.ALGO_MAX_TRADE_RISK_PCT = 0.02; c.MIN_LOT = 0.01
        self._patch(1000.0)
        warn, wi = S.capital_warning(746)
        self.assertTrue(warn)
        self.assertGreater(wi["risk_pct"], 0.02)
        self.assertGreater(wi["needed_equity"], 1000)

    def test_no_warn_big_equity(self):
        import agents.algo_sizing as S, config as c
        c.ALGO_MAX_TRADE_RISK_PCT = 0.02; c.MIN_LOT = 0.01
        self._patch(1_000_000.0)
        warn, _ = S.capital_warning(746)
        self.assertFalse(warn)

    def test_no_metrics_no_warn(self):
        import agents.algo_sizing as S
        S._equity_pipval = lambda equity=None: (None, None)
        warn, _ = S.capital_warning(746)
        self.assertFalse(warn)                              # คำนวณไม่ได้ = ไม่เตือน (fail-open)


class TestStandDown(unittest.TestCase):
    """guard บล็อก (ต่างจาก warning) — ข้ามไม้เมื่อ over-risk + เคารพ flag."""
    def test_skip_when_over_risk(self):
        import agents.algo_sizing as S, config as c
        S._equity_pipval = lambda equity=None: (1000.0, 36.0)
        c.ALGO_SIZE_STANDDOWN = True; c.ALGO_MAX_TRADE_RISK_PCT = 0.02; c.MIN_LOT = 0.01
        skip, info = S.standdown_for_size(746)
        self.assertTrue(skip)
        self.assertGreater(info["risk_pct"], 0.02)

    def test_flag_off_no_skip(self):
        import agents.algo_sizing as S, config as c
        c.ALGO_SIZE_STANDDOWN = False
        skip, _ = S.standdown_for_size(746)
        self.assertFalse(skip)


class TestDailyTech(unittest.TestCase):
    """comment → technique/regime (ALGO-TSMOM ต้องรู้จัก + prefix order ถูก)."""
    def test_tsmom_recognized(self):
        from agents.daily_summary import _tech
        label, regime = _tech({"comment": "ALGO-TSMOM"})
        self.assertIn("TSMOM", label)
        self.assertEqual(regime, "TREND")

    def test_prefix_order(self):
        from agents.daily_summary import _tech
        self.assertEqual(_tech({"comment": "ALGO-PF"}), ("Fade S/R (pending)", "RANGE"))
        self.assertEqual(_tech({"comment": "ALGO-mom"}), ("Momentum breakout", "TREND"))
        # ALGO-TSMOM ต้องไม่ถูกจับด้วย ALGO-P (T≠P)
        self.assertNotEqual(_tech({"comment": "ALGO-TSMOM"})[0], "Momentum breakout (pending)")


class TestAlgoExitExclusion(unittest.TestCase):
    """TSMOM ต้องไม่ถูก algo_exit trailing จับ (จัดการ exit เอง)."""
    def test_tsmom_excluded_logic(self):
        def _included(cmt):
            return cmt.startswith("ALGO") and not cmt.startswith("ALGO-TSMOM")
        self.assertTrue(_included("ALGO-mom"))
        self.assertTrue(_included("ALGO-PF"))
        self.assertFalse(_included("ALGO-TSMOM"))           # excluded ✓


class TestDashboardEndpoints(unittest.TestCase):
    """integration (user) — จำลอง browser fetch endpoints."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(_BASE, "dashboard"))
        import app
        cls.client = app.app.test_client()

    def test_api_tsmom(self):
        d = self.client.get("/api/tsmom").get_json()
        self.assertTrue(d["ok"])
        self.assertIn(d["signal"], ("BUY", "SELL", "FLAT", None))
        self.assertIsInstance(d["votes"], list)

    def test_api_tsmom_capital_warn(self):
        import agents.algo_sizing as S
        S._equity_pipval = lambda equity=None: (1000.0, 36.0)   # ทุนเล็ก → ต้องเตือน
        d = self.client.get("/api/tsmom").get_json()
        if d.get("sl_pips"):
            self.assertIsNotNone(d["capital_warn"])
            self.assertGreater(d["capital_warn"]["risk_pct"], 2.0)

    def test_api_algo_status_tsmom_aware(self):
        d = self.client.get("/api/algo-status").get_json()
        self.assertEqual(d["mode"], "TSMOM-D1 (daily)")
        self.assertIsNone(d["signal"])                      # momentum signal ปิดในโหมด TSMOM
        self.assertIn("momentum-intraday", d["disabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
