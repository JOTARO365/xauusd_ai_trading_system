#!/usr/bin/env python
"""backtest_viz.py — visual backtest: ราคาย้อนหลัง → แท่งเทียน + รัน algo + โชว์จุดเข้า order

⚠️ OFFLINE display tool. รัน regime-routed algo (momentum breakout ใน TREND = algo market จริงของบอท)
บนราคาย้อนหลัง แล้ว render เป็น HTML standalone (lightweight-charts inline — เปิด offline ได้ ตรงกับ dashboard):
แท่งเทียน + ลูกศรเข้า (▲BUY/▼SELL) + จุด exit (win/loss) + ตารางไม้คลิกดู SL/TP.

รัน:  & $PY scripts\backtest_viz.py [tf] [n_bars]
ตัวอย่าง: & $PY scripts\backtest_viz.py h1 800   → reports\backtest_viz.html
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)                                 # ให้ import agents.* ได้
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAX_HOLD = 48
EQUITY = 50000.0       # ทุนสำหรับสรุป ฿ P&L (demo 50k)
PIP_VALUE = 36.0       # ฿/lot/point (gold: 100oz×$1×USDTHB~36 — ประเมิน; เลขจริงจาก MT5 pip_value)
# fade (RANGE) params — ตรงกับ _place_range_fade ใน regime_pending.py
FADE_EXPIRY = 6        # bars — LIMIT fill ภายใน 6 H1 bar (live expiry_hours=6)
FADE_SL_ATR = 0.6      # SL 0.6·ATR เลย level (กัน stop-hunt)
FADE_RR = 2.0          # RR floor
FADE_COOLDOWN = 12     # ไม่ fade level เดิมซ้ำภายใน 12 bar
EMA_HTF = 200          # HTF trend gate: close > EMA200 = BULL (ไม่ fade สวนเทรนด์)
LIB = os.path.join(_BASE, "dashboard", "static", "lightweight-charts.standalone.production.js")


def _load(tf):
    d = np.array(json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json"))), dtype=float)
    return d[:, 0], d[:, 1], d[:, 2], d[:, 3], d[:, 4]     # ts, open, high, low, close


def _ema(x, n):
    a = 2.0 / (n + 1); out = np.full(len(x), np.nan); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _sim_limit(fi, entry, direction, sl, tp, high, low, close):
    """sim LIMIT fill: entry = level (ไม่ใช่ close). intrabar, pessimistic (SL ถ้า SL+TP บาร์เดียว)."""
    sign = 1.0 if direction == "BUY" else -1.0
    risk = abs(entry - sl)
    end = min(fi + MAX_HOLD, len(close) - 1)
    for j in range(fi, end + 1):
        hit_sl = low[j] <= sl if direction == "BUY" else high[j] >= sl
        hit_tp = high[j] >= tp if direction == "BUY" else low[j] <= tp
        if hit_sl and hit_tp:
            return -1.0, j, sl, "SL_TP_ambig"
        if hit_sl:
            return -1.0, j, sl, "SL"
        if hit_tp:
            return round((tp - entry) / risk * sign, 2), j, tp, "TP"
    return round(sign * (close[end] - entry) / risk, 2), end, float(close[end]), "TIME"


def _fade_signals(ts, h, l, c, atr, er, adx, vp, start, end):
    """RANGE fade (offline proxy ของ _place_range_fade): cluster S/R + HTF-EMA gate + LIMIT fill.
    ⚠️ ใช้ price-cluster (ส่วน reproduce ได้ของ live sr_view); ไม่มี sr_meta LLM zone + weak-veto break_pct."""
    from agents.cluster_map import compute_cluster_map
    ema = _ema(c, EMA_HTF)
    out = []; last_lvl = {}
    for i in range(start, end):
        if R.detect_regime(er[i], adx[i], vp[i]) != "RANGE":
            continue
        a0 = max(0, i - 400)
        cm = compute_cluster_map(h[a0:i + 1], l[a0:i + 1], c[a0:i + 1])
        if not cm.get("ok"):
            continue
        bull = c[i] > ema[i]
        atr_i = float(atr[i])
        if atr_i <= 0:
            continue
        for side, lvl_obj, otype in (("BUY", cm.get("support"), "BUY_LIMIT"),
                                     ("SELL", cm.get("resistance"), "SELL_LIMIT")):
            if not lvl_obj:
                continue
            if (bull and side == "SELL") or (not bull and side == "BUY"):   # HTF-trend gate
                continue
            lvl = float(lvl_obj["level"]); key = round(lvl, 1)
            if i - last_lvl.get(key, -10 ** 9) < FADE_COOLDOWN:
                continue
            sign = 1.0 if side == "BUY" else -1.0
            sl = lvl - sign * FADE_SL_ATR * atr_i
            tp = lvl + sign * FADE_RR * FADE_SL_ATR * atr_i
            fi = None                                       # หา bar ที่ LIMIT fill (ภายใน expiry)
            for j in range(i + 1, min(i + 1 + FADE_EXPIRY, end + 1)):
                if (side == "BUY" and l[j] <= lvl) or (side == "SELL" and h[j] >= lvl):
                    fi = j; break
            if fi is None:
                continue
            last_lvl[key] = i
            r, xi, xp, why = _sim_limit(fi, lvl, side, sl, tp, h, l, c)
            out.append({"type": "FADE", "regime": "RANGE", "dir": side,
                        "et": int(ts[fi]), "ep": round(lvl, 2),
                        "xt": int(ts[xi]) if xi <= end else None, "xp": round(xp, 2),
                        "sl": round(sl, 2), "tp": round(tp, 2),
                        "slp": max(1, round(FADE_SL_ATR * atr_i / R.POINT)),
                        "tpp": max(1, round(FADE_RR * FADE_SL_ATR * atr_i / R.POINT)),
                        "R": r, "why": why, "touches": int(lvl_obj.get("touches") or 0)})
    return out


def build(tf="h1", n_bars=800):
    ts, o, h, l, c = _load(tf)
    n = len(c)
    er = R.efficiency_ratio(c, R.VOL_WIN); adx = R.adx(h, l, c)
    vp = R.vol_percentile(c); atr = R.atr(h, l, c)
    w0 = max(R.BRK_WIN, R.VOL_LOOKBACK) + 2                 # warmup — signal เริ่มหลัง indicator พร้อม
    start = max(w0, n - n_bars)                             # หน้าต่างแสดงผล (บาร์ล่าสุด n_bars)
    end = n - 1

    trades = []
    for i in range(start, end):
        regime, sig = R.route(i, h, l, c, atr, er, adx, vp)
        if not sig:
            continue
        d = sig["dir"]; slp = sig["sl_pips"]; tpp = sig.get("tp_pips", round(slp * R.RR))
        entry = float(c[i]); sign = 1.0 if d == "BUY" else -1.0
        sl_price = entry - sign * slp * R.POINT
        tp_price = entry + sign * tpp * R.POINT
        r_g, bars, mfe, mae, why = BT.simulate_trade(i, d, slp, tpp, MAX_HOLD, h, l, c)
        xi = min(i + bars, end)
        exit_price = tp_price if why == "TP" else (sl_price if why in ("SL", "SL_TP_ambig") else float(c[xi]))
        trades.append({
            "type": "MOM", "regime": regime, "dir": d,
            "et": int(ts[i]), "ep": round(entry, 2),
            "xt": int(ts[xi]) if xi <= end else None, "xp": round(exit_price, 2),
            "sl": round(sl_price, 2), "tp": round(tp_price, 2),
            "slp": int(slp), "tpp": int(tpp), "R": round(r_g, 2), "why": why,
        })

    # + fade (RANGE) เข้าที่ cluster S/R → merge เรียงตามเวลา + เลขไม้ใหม่
    trades += _fade_signals(ts, h, l, c, atr, er, adx, vp, start, end)
    trades.sort(key=lambda t: t["et"])
    # ฿ P&L @ EQUITY (risk-based sizing เหมือน algo_lot: lot = eq×risk% / (sl_pips×pipval), clamp MIN/MAX_LOT)
    import config as _cfg
    rp = float(getattr(_cfg, "REGIME_SR_RISK_PCT", 0.005))
    mnl = float(getattr(_cfg, "MIN_LOT", 0.01)); mxl = float(getattr(_cfg, "MAX_LOT", 0.03))
    for k, t in enumerate(trades, 1):
        t["n"] = k
        raw = (EQUITY * rp) / (t["slp"] * PIP_VALUE) if t["slp"] > 0 else mnl
        t["lot"] = max(mnl, min(round(raw, 2), mxl))
        t["baht"] = round(t["R"] * t["lot"] * t["slp"] * PIP_VALUE)

    candles = [{"time": int(ts[i]), "open": round(float(o[i]), 2), "high": round(float(h[i]), 2),
                "low": round(float(l[i]), 2), "close": round(float(c[i]), 2)} for i in range(start, end + 1)]

    # summary (รวม + แยก MOM/FADE + ฿ P&L @ EQUITY)
    def _agg(tl):
        Rs = np.array([t["R"] for t in tl]) if tl else np.array([])
        w = Rs[Rs > 0]; baht = sum(t["baht"] for t in tl)
        return {"n": len(tl), "wr": round(len(w) / len(Rs) * 100, 1) if len(Rs) else 0,
                "expR": round(float(Rs.mean()), 3) if len(Rs) else 0,
                "sumR": round(float(Rs.sum()), 1) if len(Rs) else 0,
                "avgW": round(float(w.mean()), 2) if len(w) else 0,
                "avgL": round(float(Rs[Rs <= 0].mean()), 2) if len(Rs) and (Rs <= 0).any() else 0,
                "baht": baht}
    mom = [t for t in trades if t["type"] == "MOM"]; fade = [t for t in trades if t["type"] == "FADE"]
    tot_baht = sum(t["baht"] for t in trades)
    summary = {"tf": tf.upper(), "bars": len(candles), "from": int(ts[start]), "to": int(ts[end]),
               "equity": int(EQUITY), "pipval": PIP_VALUE, "risk_pct": rp,
               "baht": tot_baht, "ret_pct": round(tot_baht / EQUITY * 100, 1),
               "end_eq": int(EQUITY + tot_baht),
               "all": _agg(trades), "mom": _agg(mom), "fade": _agg(fade)}
    return candles, trades, summary


def render(candles, trades, summary, out):
    lib_js = open(LIB, encoding="utf-8").read()
    html = _TEMPLATE
    html = html.replace("/*@@LIB@@*/", lib_js)
    html = html.replace("@@CANDLES@@", json.dumps(candles))
    html = html.replace("@@TRADES@@", json.dumps(trades, ensure_ascii=False))
    html = html.replace("@@SUMMARY@@", json.dumps(summary, ensure_ascii=False))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)


_TEMPLATE = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest Visualization — XAUUSD algo</title>
<style>
 :root{--bg:#0e1117;--panel:#161b22;--line:#30363d;--txt:#c9d1d9;--green:#26a69a;--red:#ef5350;--muted:#8b949e}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 "Segoe UI",system-ui,sans-serif}
 header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:baseline;flex-wrap:wrap}
 h1{font-size:16px;margin:0;font-weight:600} .stat{color:var(--muted)} .stat b{color:var(--txt)}
 .pos{color:var(--green)} .neg{color:var(--red)}
 #chart{width:100%;height:60vh;position:relative}
 #wrap{padding:0 12px 24px}
 table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
 th,td{padding:5px 8px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
 th{position:sticky;top:0;background:var(--panel);color:var(--muted);font-weight:600;cursor:pointer}
 td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
 tbody tr{cursor:pointer} tbody tr:hover{background:#1c2333} tr.sel{background:#243044!important;outline:1px solid #3b82f6}
 .tbl-wrap{max-height:28vh;overflow:auto;border:1px solid var(--line);border-radius:6px}
 .buy{color:var(--green)} .sell{color:var(--red)}
 .badge{padding:1px 6px;border-radius:4px;background:#21262d;font-size:11px;color:var(--muted)}
 .hint{color:var(--muted);font-size:12px;margin:8px 2px}
</style></head><body>
<header>
 <h1>📊 Backtest — XAUUSD algo (momentum TREND + fade RANGE)</h1>
 <span class="stat" id="s"></span>
 <span class="stat" id="pnl" style="width:100%"></span>
</header>
<div id="chart"></div>
<div id="wrap">
 <div class="hint">▲ BUY / ▼ SELL momentum (TREND) · ■ fade (RANGE) BUY@แนวรับ/SELL@แนวต้าน · ● เขียว/แดง = exit กำไร/ขาดทุน · คลิกแถว → วางเส้น SL/TP + เลื่อนกราฟ · ฿ = P&L ที่ทุนตั้งต้น</div>
 <div class="tbl-wrap"><table id="tbl"><thead><tr>
  <th>#</th><th>ชนิด</th><th>Regime</th><th>Dir</th><th>เวลาเข้า</th><th>Entry</th><th>SL</th><th>TP</th><th>Exit</th><th>R</th><th>฿</th><th>ผล</th>
 </tr></thead><tbody></tbody></table></div>
</div>
<script>/*@@LIB@@*/</script>
<script>
const CANDLES=@@CANDLES@@, TRADES=@@TRADES@@, SUM=@@SUMMARY@@;
const fmtT=t=>{const d=new Date(t*1000);return d.toLocaleString('th-TH',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})};
// header
const A=SUM.all, sg=v=>v>=0?'pos':'neg', pm=v=>v>=0?'+':'';
document.getElementById('s').innerHTML=
 `<b>${SUM.tf}</b> · ${SUM.bars} แท่ง · ไม้ <b>${A.n}</b> (MOM ${SUM.mom.n} / FADE ${SUM.fade.n}) · `+
 `WR <b>${A.wr}%</b> · expR <b class="${sg(A.expR)}">${pm(A.expR)}${A.expR}R</b> · `+
 `sumR <b class="${sg(A.sumR)}">${pm(A.sumR)}${A.sumR}R</b>`;
document.getElementById('pnl').innerHTML=
 `💰 ทุน <b>${SUM.equity.toLocaleString()}฿</b> (risk ${(SUM.risk_pct*100).toFixed(1)}%/ไม้, pipval~${SUM.pipval}) → `+
 `P&L <b class="${sg(SUM.baht)}">${pm(SUM.baht)}${SUM.baht.toLocaleString()}฿</b> `+
 `(<b class="${sg(SUM.ret_pct)}">${pm(SUM.ret_pct)}${SUM.ret_pct}%</b>) → ทุนสิ้นสุด <b>${SUM.end_eq.toLocaleString()}฿</b> `+
 `<span class="stat">· MOM <span class="${sg(SUM.mom.baht)}">${pm(SUM.mom.baht)}${SUM.mom.baht.toLocaleString()}฿</span> / `+
 `FADE <span class="${sg(SUM.fade.baht)}">${pm(SUM.fade.baht)}${SUM.fade.baht.toLocaleString()}฿</span></span>`;
// chart
const chart=LightweightCharts.createChart(document.getElementById('chart'),{
 layout:{background:{color:'#0e1117'},textColor:'#c9d1d9'},
 grid:{vertLines:{color:'#1c2128'},horzLines:{color:'#1c2128'}},
 timeScale:{timeVisible:true,secondsVisible:false,borderColor:'#30363d'},
 rightPriceScale:{borderColor:'#30363d'},crosshair:{mode:0}});
const series=chart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,
 wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
series.setData(CANDLES);
// markers (entry ▲▼ + exit ●)
let markers=[];
for(const t of TRADES){
 const buy=t.dir==='BUY', fade=t.type==='FADE';
 markers.push({time:t.et,position:buy?'belowBar':'aboveBar',color:buy?'#26a69a':'#ef5350',
  shape:fade?'square':(buy?'arrowUp':'arrowDown'),text:`${fade?'F':'M'}${t.n} ${t.R>=0?'+':''}${t.R}R`});
 if(t.xt)markers.push({time:t.xt,position:'inBar',color:t.R>0?'#26a69a':'#ef5350',shape:'circle'});
}
markers.sort((a,b)=>a.time-b.time);
series.setMarkers(markers);
// table
const tb=document.querySelector('#tbl tbody'); let lines=[];
function clearLines(){lines.forEach(l=>series.removePriceLine(l));lines=[];}
function selectTrade(t,row){
 clearLines();
 document.querySelectorAll('#tbl tr.sel').forEach(r=>r.classList.remove('sel'));
 if(row)row.classList.add('sel');
 lines.push(series.createPriceLine({price:t.ep,color:'#58a6ff',lineWidth:1,lineStyle:2,title:`entry #${t.n}`}));
 lines.push(series.createPriceLine({price:t.sl,color:'#ef5350',lineWidth:1,lineStyle:2,title:'SL'}));
 lines.push(series.createPriceLine({price:t.tp,color:'#26a69a',lineWidth:1,lineStyle:2,title:'TP'}));
 const c0=t.et-40*3600, c1=(t.xt||t.et)+40*3600;
 chart.timeScale().setVisibleRange({from:c0,to:c1});
}
for(const t of TRADES){
 const tr=document.createElement('tr');
 const res=t.R>0?`<span class="pos">TP +${t.R}R</span>`:(t.why==='TIME'?`<span class="neg">TIME ${t.R}R</span>`:`<span class="neg">SL ${t.R}R</span>`);
 tr.innerHTML=`<td>${t.n}</td><td><span class="badge">${t.type}</span></td><td><span class="badge">${t.regime}</span></td>`+
  `<td class="${t.dir==='BUY'?'buy':'sell'}">${t.dir}</td><td>${fmtT(t.et)}</td>`+
  `<td>${t.ep}</td><td>${t.sl}</td><td>${t.tp}</td><td>${t.xp}</td>`+
  `<td class="${t.R>=0?'pos':'neg'}">${t.R>=0?'+':''}${t.R}</td>`+
  `<td class="${t.baht>=0?'pos':'neg'}">${t.baht>=0?'+':''}${t.baht.toLocaleString()}</td><td>${res}</td>`;
 tr.onclick=()=>selectTrade(t,tr);
 tb.appendChild(tr);
}
chart.timeScale().fitContent();
window.addEventListener('resize',()=>chart.applyOptions({}));
</script></body></html>"""


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    n_bars = int(sys.argv[2]) if len(sys.argv) > 2 else 800
    candles, trades, summary = build(tf, n_bars)
    out = os.path.join(_BASE, "reports", "backtest_viz.html")
    render(candles, trades, summary, out)
    a = summary["all"]
    print(f"✔ สร้างแล้ว: {out}")
    print(f"  {summary['tf']} · {summary['bars']} แท่ง · {a['n']} ไม้ (MOM {summary['mom']['n']}/FADE {summary['fade']['n']}) · "
          f"WR {a['wr']}% · expR {a['expR']:+}R · sumR {a['sumR']:+}R")
    print(f"  💰 ทุน {summary['equity']:,}฿ (risk {summary['risk_pct']*100:.1f}%/ไม้, pipval~{summary['pipval']}) → "
          f"P&L {summary['baht']:+,}฿ ({summary['ret_pct']:+}%) → ทุนสิ้นสุด {summary['end_eq']:,}฿")
    print(f"     MOM {summary['mom']['baht']:+,}฿ / FADE {summary['fade']['baht']:+,}฿")
    print(f"  เปิดไฟล์ในเบราว์เซอร์ได้เลย (standalone, offline)")


if __name__ == "__main__":
    main()
