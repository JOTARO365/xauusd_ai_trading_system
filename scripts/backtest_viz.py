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
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAX_HOLD = 48
LIB = os.path.join(_BASE, "dashboard", "static", "lightweight-charts.standalone.production.js")


def _load(tf):
    d = np.array(json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json"))), dtype=float)
    return d[:, 0], d[:, 1], d[:, 2], d[:, 3], d[:, 4]     # ts, open, high, low, close


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
            "n": len(trades) + 1, "regime": regime, "dir": d,
            "et": int(ts[i]), "ep": round(entry, 2),
            "xt": int(ts[xi]) if xi <= end else None, "xp": round(exit_price, 2),
            "sl": round(sl_price, 2), "tp": round(tp_price, 2),
            "slp": int(slp), "tpp": int(tpp), "R": round(r_g, 2), "why": why,
        })

    candles = [{"time": int(ts[i]), "open": round(float(o[i]), 2), "high": round(float(h[i]), 2),
                "low": round(float(l[i]), 2), "close": round(float(c[i]), 2)} for i in range(start, end + 1)]

    # summary
    Rs = np.array([t["R"] for t in trades]) if trades else np.array([])
    wins = Rs[Rs > 0]
    summary = {
        "tf": tf.upper(), "bars": len(candles), "n": len(trades),
        "wr": round(len(wins) / len(Rs) * 100, 1) if len(Rs) else 0,
        "expR": round(float(Rs.mean()), 3) if len(Rs) else 0,
        "sumR": round(float(Rs.sum()), 1) if len(Rs) else 0,
        "avgW": round(float(wins.mean()), 2) if len(wins) else 0,
        "avgL": round(float(Rs[Rs <= 0].mean()), 2) if len(Rs) and (Rs <= 0).any() else 0,
        "from": int(ts[start]), "to": int(ts[end]),
    }
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
 <h1>📊 Backtest — XAUUSD momentum breakout (TREND)</h1>
 <span class="stat" id="s"></span>
</header>
<div id="chart"></div>
<div id="wrap">
 <div class="hint">▲ = เข้า BUY · ▼ = เข้า SELL · ● เขียว/แดง = exit ได้กำไร/ขาดทุน · คลิกแถวในตาราง → วางเส้น SL/TP + เลื่อนกราฟไปไม้นั้น</div>
 <div class="tbl-wrap"><table id="tbl"><thead><tr>
  <th>#</th><th>Regime</th><th>Dir</th><th>เวลาเข้า</th><th>Entry</th><th>SL</th><th>TP</th><th>Exit</th><th>R</th><th>ผล</th>
 </tr></thead><tbody></tbody></table></div>
</div>
<script>/*@@LIB@@*/</script>
<script>
const CANDLES=@@CANDLES@@, TRADES=@@TRADES@@, SUM=@@SUMMARY@@;
const fmtT=t=>{const d=new Date(t*1000);return d.toLocaleString('th-TH',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})};
// header
const sc=SUM.sumR>=0?'pos':'neg', ec=SUM.expR>=0?'pos':'neg';
document.getElementById('s').innerHTML=
 `<b>${SUM.tf}</b> · ${SUM.bars} แท่ง · ไม้: <b>${SUM.n}</b> · WR <b>${SUM.wr}%</b> · `+
 `expR <b class="${ec}">${SUM.expR>=0?'+':''}${SUM.expR}R</b> · sumR <b class="${sc}">${SUM.sumR>=0?'+':''}${SUM.sumR}R</b> · `+
 `avgW <span class="pos">+${SUM.avgW}</span> / avgL <span class="neg">${SUM.avgL}</span>`;
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
 const buy=t.dir==='BUY';
 markers.push({time:t.et,position:buy?'belowBar':'aboveBar',color:buy?'#26a69a':'#ef5350',
  shape:buy?'arrowUp':'arrowDown',text:`#${t.n} ${t.R>=0?'+':''}${t.R}R`});
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
 tr.innerHTML=`<td>${t.n}</td><td><span class="badge">${t.regime}</span></td>`+
  `<td class="${t.dir==='BUY'?'buy':'sell'}">${t.dir}</td><td>${fmtT(t.et)}</td>`+
  `<td>${t.ep}</td><td>${t.sl}</td><td>${t.tp}</td><td>${t.xp}</td>`+
  `<td class="${t.R>=0?'pos':'neg'}">${t.R>=0?'+':''}${t.R}</td><td>${res}</td>`;
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
    print(f"✔ สร้างแล้ว: {out}")
    print(f"  {summary['tf']} · {summary['bars']} แท่ง · {summary['n']} ไม้ · WR {summary['wr']}% · "
          f"expR {summary['expR']:+}R · sumR {summary['sumR']:+}R")
    print(f"  เปิดไฟล์ในเบราว์เซอร์ได้เลย (standalone, offline)")


if __name__ == "__main__":
    main()
