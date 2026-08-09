"""agents/preflight.py — startup safety check ก่อน cycle แรก (user 08-09).

เตือนก่อนบอทเริ่มเทรด: config lot vs account จริง (micro/standard mismatch, risk/ไม้ เกินทุน, FF off).
กันรันผิดบัญชี (เช่น FIXED_LOT=0.3 micro บน terminal standard = lot ใหญ่ 100× = ระเบิด).
คืน list ของ (level, msg). fail-soft (ไม่ crash startup). 0 order.
"""


def _risk_pct(mt5, sym, lot, sl_dollar, equity):
    """risk (%) ของ lot นั้นถ้าโดน SL sl_dollar. คืน (risk_thb, pct)."""
    t = mt5.symbol_info_tick(sym)
    if not t or equity <= 0:
        return None, None
    px = t.ask or t.bid
    r = abs(mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, lot, px, px - sl_dollar) or 0.0)
    return r, r / equity * 100


def check():
    """คืน [(level, msg)] · level: CRIT/WARN/OK/INFO. fail-soft."""
    out = []
    try:
        import MetaTrader5 as mt5
        import config as cfg
        from connectors.pair_collector import _broker_map
        a = mt5.account_info()
        if not a:
            return [("WARN", "preflight: อ่าน account ไม่ได้ — ข้าม")]
        eq = float(a.equity); bm = _broker_map() or {}
        fixed_lot = float(getattr(cfg, "FIXED_LOT", 0.01))
        ff = bool(getattr(cfg, "FF_SIZING_ENABLE", False))
        gate = bool(getattr(cfg, "CAPITAL_GATE_ENABLE", False))
        floor = float(getattr(cfg, "CAPITAL_GATE_FLOOR", 20000))
        out.append(("INFO", "บัญชี: %s %.0f %s · lev 1:%s · FIXED_LOT=%.2f · FF=%s · gate=%s(<%.0f)"
                    % (a.login, eq, a.currency, a.leverage, fixed_lot, "on" if ff else "off",
                       "on" if gate else "off", floor)))
        # 1) micro/standard scale — จากทอง contract
        gs = bm.get("XAUUSD", "XAUUSD"); mt5.symbol_select(gs, True)
        gsi = mt5.symbol_info(gs)
        gc = float(getattr(gsi, "trade_contract_size", 100)) if gsi else 100
        is_micro = gc <= 10
        out.append(("INFO", "ทอง %s contract=%.0f → บัญชี %s" % (gs, gc, "MICRO" if is_micro else "STANDARD")))
        if fixed_lot >= 0.1 and not is_micro:
            out.append(("CRIT", "FIXED_LOT=%.2f = micro-scale แต่ทอง contract=%.0f (STANDARD) → lot ใหญ่ ~%.0f× ! "
                        "ต่อบัญชี MICRO หรือแก้ FIXED_LOT" % (fixed_lot, gc, gc)))
        if fixed_lot <= 0.03 and is_micro:
            out.append(("WARN", "FIXED_LOT=%.2f เล็กมากบน MICRO — อาจตั้งใจ (FF คุมอยู่) หรือลืมสเกล ×100" % fixed_lot))
        # 2) per-symbol min-lot risk vs equity (focus XAU + BTC)
        for lg, sld in [("XAUUSD", 40.0), ("BTCUSD", 800.0)]:
            s = bm.get(lg, lg); mt5.symbol_select(s, True)
            si = mt5.symbol_info(s)
            if not si:
                continue
            rthb, pct = _risk_pct(mt5, s, si.volume_min, sld, eq)
            if pct is None:
                continue
            lvl = "CRIT" if pct > 100 else "WARN" if pct > 30 else "OK"
            out.append((lvl, "%s min-lot %.2f: risk ~%.0f%s (%.0f%% ของทุน) ที่ SL~$%.0f%s"
                        % (lg, si.volume_min, rthb, a.currency, pct, sld,
                           " — เทรดไม่ได้ปลอดภัย" if pct > 100 else (" — เสี่ยงสูง" if pct > 30 else ""))))
        # 3) FF off ที่ทุนเล็ก
        if not ff and eq < floor:
            out.append(("WARN", "FF_SIZING off ที่ทุน %.0f < %.0f → ใช้ FIXED_LOT ตรงๆ = อาจ over-risk (แนะนำเปิด FF)" % (eq, floor)))
        crit = sum(1 for l, _ in out if l == "CRIT")
        out.append(("CRIT" if crit else "OK", "preflight: %d CRITICAL · %d WARN"
                    % (crit, sum(1 for l, _ in out if l == "WARN"))))
    except Exception as e:
        out.append(("WARN", "preflight fail-soft: %s" % e))
    return out
