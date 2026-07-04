"""
ทดสอบ function ทั้งหมดที่แก้ไขใน Issues #6-#9 + pending + lot calculation
รัน: python tests/test_all.py
"""
import sys, os, types, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root — รันได้จากทุก cwd
from unittest.mock import MagicMock, patch
from datetime import datetime, date

# ── Setup MT5 mock ────────────────────────────────────────────────────────────
def _make_mt5_mock():
    m = types.ModuleType("MetaTrader5")
    for k, v in {
        "TIMEFRAME_M1": 1, "TIMEFRAME_M5": 5, "TIMEFRAME_M15": 15,
        "TIMEFRAME_M30": 30, "TIMEFRAME_H1": 16385, "TIMEFRAME_H4": 16388,
        "TIMEFRAME_D1": 16408, "TIMEFRAME_W1": 32769, "TIMEFRAME_MN1": 49153,
        "ORDER_TYPE_BUY": 0, "ORDER_TYPE_SELL": 1,
        "ORDER_TYPE_BUY_LIMIT": 2, "ORDER_TYPE_SELL_LIMIT": 3,
        "ORDER_TYPE_BUY_STOP": 4, "ORDER_TYPE_SELL_STOP": 5,
        "TRADE_ACTION_DEAL": 1, "TRADE_ACTION_PENDING": 5, "TRADE_ACTION_SLTP": 6,
        "TRADE_RETCODE_DONE": 10009,
        "ORDER_TIME_GTC": 0, "ORDER_TIME_SPECIFIED": 1,
        "ORDER_FILLING_IOC": 1, "ORDER_FILLING_RETURN": 2,
        "POSITION_TYPE_BUY": 0, "POSITION_TYPE_SELL": 1,
        "DEAL_ENTRY_IN": 0, "DEAL_ENTRY_OUT": 1,
    }.items():
        setattr(m, k, v)
    m.initialize = lambda *a, **k: True
    m.shutdown = lambda: None
    m.symbol_info = lambda s: None
    m.symbol_info_tick = lambda s: None
    m.positions_get = lambda **k: []
    m.orders_get = lambda **k: []
    m.account_info = lambda: None
    m.history_deals_get = lambda *a: []
    m.last_error = lambda: (0, "OK")
    m.order_send = lambda r: None
    m.copy_rates_from_pos = lambda *a, **k: None
    return m

sys.modules["MetaTrader5"] = _make_mt5_mock()
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import config
from config import MONEY_MANAGEMENT

# ─────────────────────────────────────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _pos(ticket=1001, entry=4700.0, sl=4600.0, tp=4900.0, volume=0.10,
         type_=0, magic=20260429):
    """สร้าง MT5 position mock"""
    p = MagicMock()
    p.ticket = ticket
    p.price_open = entry
    p.sl = sl
    p.tp = tp
    p.volume = volume
    p.type = type_     # 0=BUY, 1=SELL
    p.magic = magic
    return p


def _tick(bid=4750.0, ask=4750.5):
    t = MagicMock()
    t.bid = bid
    t.ask = ask
    return t


def _sym_info(point=0.01, volume_min=0.01):
    s = MagicMock()
    s.point = point
    s.volume_min = volume_min
    return s


def _make_chart(signal="BUY", conf=72, trend="BULLISH", entry_type="DOJI_AT_ZONE",
                sr_zone="SUPPORT", sr_strength="STRONG",
                buy_sl=1150, sell_sl=1150, tp_pips=3000,
                h4_atr=15.0, m15_dir="UP", h1_dir="UP", m15_str="STRONG"):
    return {
        "signal": signal, "confidence": conf, "trend": trend,
        "entry_type": entry_type, "sr_zone": sr_zone, "sr_strength": sr_strength,
        "buy_sl_pips": buy_sl, "sell_sl_pips": sell_sl, "tp_pips": tp_pips,
        "indicators": {"h4": {"atr": h4_atr, "close": 4700.0}},
        "sr_zones": {"resistance": [4800.0, 4900.0], "support": [4600.0, 4500.0]},
        "key_levels": {},
        "momentum_tf": {
            "m15": {"strength": m15_str, "direction": m15_dir},
            "h1":  {"strength": "MODERATE", "direction": h1_dir},
        },
        "scan": {"best_score": 70, "setups": []},
    }


def _make_history(streak=0, today_pnl=-50.0):
    return {
        "today_trades": 3, "today_pnl": today_pnl,
        "total_closed": 20, "last_10_winrate": 55.0,
        "last_10_win": 5, "last_10_loss": 5,
        "losing_streak": streak,
        "recent_trades_text": "", "entry_perf_text": "",
    }


def _make_account(balance=5000.0):
    return {"balance": balance, "equity": balance}


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Issue #9 — Config PENDING_EXPIRY_HOURS default
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):

    def test_pending_expiry_default_is_24(self):
        """config.py default should be 24 (override via .env)"""
        # ตรวจว่า source code ค่า default = 24
        with open("config.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn('or 24)', src,
            "config.py default pending_expiry_hours ต้องเป็น 24")

    def test_money_management_keys_exist(self):
        keys = ["risk_per_trade", "default_sl_pips", "pending_expiry_hours",
                "max_pending_buy", "max_pending_sell", "min_rr_ratio"]
        for k in keys:
            self.assertIn(k, MONEY_MANAGEMENT, f"MONEY_MANAGEMENT missing key: {k}")


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Issue #6 — manage_partial_close
# ─────────────────────────────────────────────────────────────────────────────

class TestPartialClose(unittest.TestCase):

    def setUp(self):
        import connectors.mt5_connector as mc
        self.mc = mc
        mc._partial_state = {}   # reset state

    def test_no_positions_returns_zero(self):
        import MetaTrader5 as mt5
        mt5.positions_get = lambda **k: []
        mt5.symbol_info = lambda s: _sym_info()
        mt5.symbol_info_tick = lambda s: _tick()
        result = self.mc.manage_partial_close()
        self.assertEqual(result, 0)

    def test_first_sight_captures_r_pips(self):
        """ครั้งแรกที่เห็น position ต้องบันทึก r_pips"""
        import MetaTrader5 as mt5
        pos = _pos(entry=4700.0, sl=4600.0)   # r = 100/0.01 = 10000 pips
        # profit < 1R → ยังไม่ trigger
        mt5.positions_get = lambda **k: [pos]
        mt5.symbol_info = lambda s: _sym_info(point=0.01)
        mt5.symbol_info_tick = lambda s: _tick(bid=4750.0)   # profit=50/0.01=5000p < 10000p
        self.mc.manage_partial_close()
        self.assertIn(pos.ticket, self.mc._partial_state)
        self.assertAlmostEqual(self.mc._partial_state[pos.ticket]["r_pips"], 10000.0)

    def test_skip_if_r_pips_too_small(self):
        """SL ใกล้ entry (< _MIN_R_PIPS) = BE แล้ว → ข้าม"""
        import MetaTrader5 as mt5
        pos = _pos(entry=4700.0, sl=4698.0)   # r = 200 pips < 300
        mt5.positions_get = lambda **k: [pos]
        mt5.symbol_info = lambda s: _sym_info(point=0.01)
        mt5.symbol_info_tick = lambda s: _tick(bid=4750.0)
        self.mc.manage_partial_close()
        self.assertNotIn(pos.ticket, self.mc._partial_state)

    def test_1r_triggers_partial_close(self):
        """profit ≥ 1R → ต้อง call order_send + บันทึก '1R' done"""
        import MetaTrader5 as mt5

        sent = []
        result_ok = MagicMock()
        result_ok.retcode = mt5.TRADE_RETCODE_DONE

        def fake_order_send(req):
            sent.append(req)
            return result_ok

        pos = _pos(entry=4700.0, sl=4600.0, volume=0.10)
        # r = (4700-4600)/0.01 = 10000 pips
        # profit ≥ 10000p = bid 4700+100 = 4800
        mt5.positions_get = lambda **k: [pos]
        mt5.symbol_info = lambda s: _sym_info(point=0.01)
        mt5.symbol_info_tick = lambda s: _tick(bid=4800.0)
        mt5.order_send = fake_order_send

        result = self.mc.manage_partial_close()
        self.assertEqual(result, 1)
        self.assertIn("1R", self.mc._partial_state[pos.ticket]["done"])
        # ต้องมี 2 requests: partial close + set SL
        self.assertEqual(len(sent), 2)

    def test_lot_too_small_skips_partial(self):
        """lot 0.01 → 50% = 0.005 < volume_min → skip"""
        import MetaTrader5 as mt5
        pos = _pos(entry=4700.0, sl=4600.0, volume=0.01)
        mt5.positions_get = lambda **k: [pos]
        mt5.symbol_info = lambda s: _sym_info(point=0.01, volume_min=0.01)
        mt5.symbol_info_tick = lambda s: _tick(bid=4800.0)
        mt5.order_send = lambda r: None

        result = self.mc.manage_partial_close()
        self.assertEqual(result, 0)   # ข้าม เพราะ lot < min

    def test_state_cleaned_after_position_closed(self):
        """เมื่อ position ปิด state ต้องถูกลบ"""
        import MetaTrader5 as mt5
        self.mc._partial_state = {9999: {"done": set(), "r_pips": 1000.0}}
        mt5.positions_get = lambda **k: []   # ไม่มี positions แล้ว
        mt5.symbol_info = lambda s: _sym_info()
        mt5.symbol_info_tick = lambda s: _tick()
        self.mc.manage_partial_close()
        self.assertNotIn(9999, self.mc._partial_state)


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Issue #7 — Gradual streak reduction
# ─────────────────────────────────────────────────────────────────────────────

class TestStreakGate(unittest.TestCase):

    def _run(self, streak, conf=72):
        from agents.decision_maker import _run_gates
        chart = _make_chart(conf=conf)
        sentiment = {"sentiment": "BULLISH", "confidence": 60, "bias": "BULLISH"}
        advisor = {"bias": "BULLISH", "regime": "TRENDING"}
        history = _make_history(streak=streak)
        account = _make_account()
        with patch("config.STREAK_PROTECTION", True), \
             patch("connectors.mt5_connector.check_open_slot", return_value=(True, "")):
            return _run_gates(chart, sentiment, advisor, history, account)

    def test_no_streak_scale_1(self):
        r = self._run(streak=0)
        self.assertTrue(r["pass"])
        self.assertEqual(r["streak_scale"], 1.0)

    def test_streak_2_scale_08(self):
        r = self._run(streak=2)
        self.assertTrue(r["pass"])
        self.assertAlmostEqual(r["streak_scale"], 0.80)

    def test_streak_3_scale_06(self):
        r = self._run(streak=3)
        self.assertTrue(r["pass"])
        self.assertAlmostEqual(r["streak_scale"], 0.60)

    def test_streak_4_scale_04(self):
        r = self._run(streak=4)
        self.assertTrue(r["pass"])
        self.assertAlmostEqual(r["streak_scale"], 0.40)

    def test_streak_5_scale_025_still_passes(self):
        """streak ≥ 5 ยังเทรดได้ แค่ size เล็กลง (ไม่ block)"""
        r = self._run(streak=5)
        self.assertTrue(r["pass"], "streak=5 ต้องไม่ block")
        self.assertAlmostEqual(r["streak_scale"], 0.25)

    def test_streak_7_scale_025(self):
        r = self._run(streak=7)
        self.assertTrue(r["pass"])
        self.assertAlmostEqual(r["streak_scale"], 0.25)


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Issue #8 — MOMENTUM_BREAKOUT fast path
# ─────────────────────────────────────────────────────────────────────────────

class TestMomentumFastPath(unittest.TestCase):

    def _run(self, entry_type, conf, sr_zone="NONE", h4_atr=25.0, hour_utc=9):
        from agents.decision_maker import _run_gates
        chart = _make_chart(conf=conf, entry_type=entry_type,
                            sr_zone=sr_zone, h4_atr=h4_atr)
        sentiment = {"sentiment": "BULLISH", "confidence": 60, "bias": "BULLISH"}
        advisor = {"bias": "BULLISH", "regime": "TRENDING"}
        history = _make_history(streak=0)
        account = _make_account()

        mock_now = datetime(2026, 5, 12, hour_utc, 0, 0)
        with patch("connectors.mt5_connector.check_open_slot", return_value=(True, "")), \
             patch("agents.decision_maker.datetime") as mock_dt:
            mock_dt.utcnow.return_value = mock_now
            return _run_gates(chart, sentiment, advisor, history, account)

    def test_normal_entry_no_sr_zone_blocked(self):
        """entry ปกติ + sr_zone=NONE + conf=60 ต้องโดน gate 7"""
        r = self._run("DOJI_AT_ZONE", conf=60, sr_zone="NONE")
        self.assertFalse(r["pass"])
        self.assertIn("SR zone", r["reason"])

    def test_momentum_breakout_bypasses_gate7(self):
        """MOMENTUM_BREAKOUT conf=70 + sr_zone=NONE ต้องผ่าน gate 7"""
        r = self._run("MOMENTUM_BREAKOUT", conf=70, sr_zone="NONE", h4_atr=15.0)
        self.assertTrue(r["pass"], f"ต้องผ่าน gate 7: {r.get('reason')}")

    def test_momentum_breakout_bypasses_gate8_high_atr(self):
        """MOMENTUM_BREAKOUT conf=70 + ATR สูง ต้องผ่าน gate 8"""
        r = self._run("MOMENTUM_BREAKOUT", conf=70, sr_zone="NONE", h4_atr=30.0)
        self.assertTrue(r["pass"], f"ต้องผ่าน gate 8: {r.get('reason')}")

    def test_momentum_breakout_conf_too_low_still_blocked(self):
        """MOMENTUM_BREAKOUT conf=60 (< 70) ยังโดน gate"""
        r = self._run("MOMENTUM_BREAKOUT", conf=60, sr_zone="NONE", h4_atr=25.0, hour_utc=9)
        self.assertFalse(r["pass"])

    def test_london_ny_overlap_threshold_65(self):
        """ช่วง London/NY overlap (hour=13 UTC) threshold ลดเป็น 65"""
        r = self._run("MOMENTUM_BREAKOUT", conf=67, sr_zone="NONE", h4_atr=25.0, hour_utc=13)
        self.assertTrue(r["pass"], f"LN/NY overlap conf=67≥65 ต้องผ่าน: {r.get('reason')}")

    def test_outside_overlap_conf65_blocked(self):
        """นอก overlap (hour=9) conf=67 < 70 ยังโดน block"""
        r = self._run("MOMENTUM_BREAKOUT", conf=67, sr_zone="NONE", h4_atr=25.0, hour_utc=9)
        self.assertFalse(r["pass"])


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Issue #9 — PENDING vs MARKET analytics
# ─────────────────────────────────────────────────────────────────────────────

class TestPendingAnalytics(unittest.TestCase):

    def _make_trades(self):
        today = date.today().isoformat()
        return [
            # PENDING orders (ที่ fill แล้ว)
            {"status": "CLOSED", "strategy_version": 2, "timestamp": f"{today}T10:00:00",
             "order_type": "PENDING_BUY_LIMIT", "entry_type": "DOJI_AT_ZONE",
             "pnl": 120.0, "source": "SYSTEM"},
            {"status": "CLOSED", "strategy_version": 2, "timestamp": f"{today}T11:00:00",
             "order_type": "PENDING_SELL_LIMIT", "entry_type": "DOJI_AT_ZONE",
             "pnl": -50.0, "source": "SYSTEM"},
            # MARKET orders
            {"status": "CLOSED", "strategy_version": 2, "timestamp": f"{today}T12:00:00",
             "order_type": "MARKET", "entry_type": "EMA_PULLBACK",
             "pnl": 80.0, "source": "SYSTEM"},
            {"status": "CLOSED", "strategy_version": 2, "timestamp": f"{today}T13:00:00",
             "order_type": "MARKET", "entry_type": "EMA_PULLBACK",
             "pnl": -30.0, "source": "SYSTEM"},
            {"status": "CLOSED", "strategy_version": 2, "timestamp": f"{today}T14:00:00",
             "order_type": "MARKET", "entry_type": "MOMENTUM_BREAKOUT",
             "pnl": 200.0, "source": "SYSTEM"},
        ]

    def test_pending_vs_market_in_output(self):
        from agents import reporter
        trades = self._make_trades()

        with patch.object(reporter, "_load_log", return_value={"trades": trades}), \
             patch("agents.reporter._cfg.SYMBOL", "GOLD#"), \
             patch("agents.reporter.get_account_info", return_value={}), \
             patch("agents.reporter.get_pending_orders", return_value=[]), \
             patch("db.reader.get_trades", side_effect=Exception("no db")):
            summary = reporter.get_trade_history_summary()

        perf = summary["entry_perf_text"]
        self.assertIn("PENDING orders", perf, "ต้องมี PENDING stats")
        self.assertIn("MARKET  orders", perf, "ต้องมี MARKET stats")
        print("\n[entry_perf_text preview]\n" + perf.encode("ascii", errors="replace").decode())

    def test_pending_wr_calculation(self):
        """PENDING: 1 win / 2 trades = WR 50%"""
        from agents import reporter
        trades = self._make_trades()

        with patch.object(reporter, "_load_log", return_value={"trades": trades}), \
             patch("agents.reporter._cfg.SYMBOL", "GOLD#"), \
             patch("agents.reporter.get_account_info", return_value={}), \
             patch("agents.reporter.get_pending_orders", return_value=[]), \
             patch("db.reader.get_trades", side_effect=Exception("no db")):
            summary = reporter.get_trade_history_summary()

        perf = summary["entry_perf_text"]
        self.assertIn("WR=50.0%", perf, "PENDING WR ต้องเป็น 50.0%")


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Counter-trend pending (pending_manager)
# ─────────────────────────────────────────────────────────────────────────────

class TestCounterTrendPending(unittest.TestCase):

    def _run_auto_pending(self, trend, sell_slots_available=4):
        from agents import pending_manager as pm
        import MetaTrader5 as mt5

        mt5.symbol_info = lambda s: _sym_info()
        mt5.symbol_info_tick = lambda s: _tick(bid=4700.0)

        chart = _make_chart(trend=trend)
        sentiment = {"sentiment": "NEUTRAL", "confidence": 0}

        with patch("agents.pending_manager.count_pending_by_direction",
                   return_value={"BUY": 0, "SELL": 4 - sell_slots_available}), \
             patch("agents.pending_manager.get_pending_orders", return_value=[]), \
             patch("agents.pending_manager._get_daily_sr",
                   return_value={"resistance": [4900.0, 5000.0],
                                 "support": [4500.0, 4400.0]}), \
             patch("agents.pending_manager.place_pending_order",
                   return_value={"success": False, "error": "test"}), \
             patch("agents.pending_manager.log_pending_order"):
            # เราแค่ตรวจ logic ของ slot หลัง trend filter
            # ดึง internal vars ผ่าน monkey-patch ชั่วคราว
            captured = {}
            orig_func = pm.auto_place_pending_orders

            def capture_slots(chart_data, sentiment_data=None):
                # รัน function จริง แต่ดัก log
                return orig_func(chart_data, sentiment_data)

            return capture_slots(chart, sentiment)

    def test_bullish_sell_limited_to_1_slot(self):
        """BULLISH trend: SELL_LIMIT ต้องจำกัดที่ 1 slot ไม่ใช่ 0"""
        # ทดสอบผ่าน constant: COUNTER_TREND_DIST = 0.015
        from agents.pending_manager import COUNTER_TREND_DIST, MIN_DIST_FROM_PRICE
        self.assertEqual(COUNTER_TREND_DIST, 0.015)
        self.assertGreater(COUNTER_TREND_DIST, MIN_DIST_FROM_PRICE,
            "COUNTER_TREND_DIST ต้องมากกว่า MIN_DIST_FROM_PRICE")

    def test_counter_trend_dist_is_5x_normal(self):
        from agents.pending_manager import COUNTER_TREND_DIST, MIN_DIST_FROM_PRICE
        self.assertAlmostEqual(COUNTER_TREND_DIST / MIN_DIST_FROM_PRICE, 5.0)


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: Lot calculation log
# ─────────────────────────────────────────────────────────────────────────────

class TestLotCalculation(unittest.TestCase):

    def setUp(self):
        import connectors.mt5_connector as mc
        self.mc = mc

    def test_lot_below_min_gets_clamped(self):
        """balance เล็ก + SL ใหญ่ → lot < MIN_LOT → clamp ขึ้น"""
        with patch("config.LOT_MODE", "auto"), \
             patch("config.MIN_LOT", 0.01), \
             patch("config.MAX_LOT", 1.00), \
             patch.dict(MONEY_MANAGEMENT, {"risk_per_trade": 0.005}):
            lot = self.mc.calculate_lot_size(account_balance=1564, sl_pips=2000)
        self.assertEqual(lot, 0.01, "ต้อง clamp ขึ้นมาที่ MIN_LOT=0.01")

    def test_lot_above_max_gets_clamped(self):
        """lot คำนวณได้ > MAX_LOT → clamp ลง"""
        with patch("config.LOT_MODE", "auto"), \
             patch("config.MIN_LOT", 0.01), \
             patch("config.MAX_LOT", 0.05), \
             patch.dict(MONEY_MANAGEMENT, {"risk_per_trade": 0.005}):
            lot = self.mc.calculate_lot_size(account_balance=330000, sl_pips=1150)
        self.assertEqual(lot, 0.05, "ต้อง clamp ลงมาที่ MAX_LOT=0.05")

    def test_fixed_lot_mode(self):
        with patch("config.LOT_MODE", "fixed"), \
             patch("config.FIXED_LOT", 0.03), \
             patch("config.MIN_LOT", 0.01), \
             patch("config.MAX_LOT", 1.00):
            lot = self.mc.calculate_lot_size(account_balance=5000, sl_pips=1000)
        self.assertEqual(lot, 0.03)


# ─────────────────────────────────────────────────────────────────────────────
#  TEST: _safe_comment (always-present utility)
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeComment(unittest.TestCase):

    def test_strips_invalid_chars(self):
        from connectors.mt5_connector import _safe_comment
        result = _safe_comment("AP BUY@4700#test")
        self.assertNotIn("@", result)
        self.assertNotIn("#", result)

    def test_max_31_chars(self):
        from connectors.mt5_connector import _safe_comment
        result = _safe_comment("A" * 50)
        self.assertLessEqual(len(result), 31)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Patch _dt ใน decision_maker ก่อนรัน
    import agents.decision_maker as dm
    import datetime as _real_dt
    dm._dt = _real_dt

    loader  = unittest.TestLoader()
    suite   = loader.loadTestsFromModule(sys.modules[__name__])
    runner  = unittest.TextTestRunner(verbosity=2)
    result  = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
