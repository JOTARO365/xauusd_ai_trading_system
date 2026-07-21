"""Terminal display utilities using Rich."""
import sys
import io
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box
from rich.rule import Rule
from config import MONEY_MANAGEMENT

# Force UTF-8 output so Thai + box-drawing chars render correctly on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_stdout_utf8 = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
) if hasattr(sys.stdout, "buffer") else sys.stdout

console = Console(file=_stdout_utf8, highlight=False, legacy_windows=False)

GOLD  = "yellow"
GREEN = "bright_green"
RED   = "bright_red"
DIM   = "dim white"
CYAN  = "cyan"
WHITE = "white"

STEP_LABELS = [
    ("01", "Chart Watcher",    "Analyze H4/H1/M15 chart"),
    ("02", "Market Advisor",   "Regime + indicator advice"),
    ("03", "News Gatherer",    "Fetch Twitter/X news"),
    ("04", "Sentiment Analyst","Analyze sentiment"),
    ("05", "Decision Maker",   "BUY / SELL / NO_TRADE"),
    ("06", "Reporter",         "Place order + log result"),
]

# Label width for key-value lines (2-space indent + label padded to 16 chars)
_LW = 16


def _kv(label: str, value: str) -> str:
    """Single key-value line: '  Label           value'"""
    return f"  [dim]{label:<{_LW}}[/dim]{value}"


def _kv2(label1: str, val1: str, label2: str, val2: str) -> str:
    """Two key-value pairs on one line."""
    return f"  [dim]{label1:<{_LW}}[/dim]{val1:<20}  [dim]{label2:<14}[/dim]{val2}"


def print_header(cycle: int = 0):
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    title = Text()
    title.append("  XAUUSD TRADING SYSTEM", style=f"bold {GOLD}")
    title.append(f"   ·   Cycle #{cycle}   ·   {now}  ", style=DIM)
    console.print(Panel(title, border_style="yellow", padding=(0, 1)))


def print_step(step_idx: int, status: str, detail: str = ""):
    num, name, desc = STEP_LABELS[step_idx]

    icon_map  = {"running": "⟳", "done": "✓", "skip": "–", "error": "✗"}
    color_map = {"running": GOLD, "done": GREEN, "skip": DIM, "error": RED}

    icon  = icon_map.get(status, "·")
    color = color_map.get(status, WHITE)

    t = Text()
    t.append(f"  [{num}/06]  ", style="bold dim white")
    t.append(f"{name:<20}", style=f"bold {WHITE}")
    t.append(f"{desc:<30}", style=DIM)
    t.append(f" {icon}  ", style=f"bold {color}")
    if detail:
        t.append(detail, style=color)
    console.print(t)


def print_cycle_start(cycle: int):
    console.print()
    console.print(Rule(f"[bold {GOLD}]  Cycle #{cycle}  [/bold {GOLD}]", style="dim yellow"))
    console.print()


def print_cycle_end(wait_sec: int, reason: str = ""):
    levels = {60: "████████████", 120: "█████████░░░", 180: "███████░░░░░",
              300: "████░░░░░░░░", 600: "██░░░░░░░░░░"}
    bar   = levels.get(wait_sec, "████░░░░░░░░")
    label = {60: "Very hot", 120: "Hot", 180: "Active",
             300: "Normal", 600: "Quiet"}.get(wait_sec, "")
    console.print()
    console.print(
        f"  [dim]{bar}[/dim]  "
        f"[bold yellow]{wait_sec}s[/bold yellow]  "
        f"[dim]{label}[/dim]"
        + (f"  [dim]— {reason}[/dim]" if reason else "")
    )
    console.print()


def _momentum_str(mom_tf: dict) -> str:
    """แปลง momentum_tf dict เป็น string แสดงผล H4▸H1▸M15"""
    parts = []
    for tf in ("h4", "h1", "m15"):
        m = mom_tf.get(tf, {})
        d = m.get("direction", "—")
        s = m.get("strength",  "")
        arrow = "▲" if d == "UP" else "▼" if d == "DOWN" else "─"
        parts.append(f"{tf.upper()}:{arrow}{s[:3]}")
    return "  ".join(parts)


def _fib_display(fib: dict) -> str:
    """สร้าง string แสดง Fib nearest level + swing"""
    n = fib.get("nearest")
    if not n:
        return "—"
    arrow  = "▲" if fib.get("swing_dir") == "UP" else "▼"
    key_s  = " [KEY]" if n["is_key"] else ""
    zone_s = " ●" if n["in_zone"] else ""
    return (f"{n['name']}{key_s} @ {n['price']}{zone_s}  "
            f"({arrow} {fib['swing_low']}─{fib['swing_high']})")


_REGIME_COLOR = {"TREND": GREEN, "RANGE": CYAN, "RISK-OFF": RED, "NEUTRAL": DIM, "WARMUP": DIM}
_STATE_COLOR  = {"ENTER": GREEN, "ARMED": GOLD, "HOLD": CYAN, "STAND-DOWN": DIM,
                 "DISABLED": RED, "HAND-OFF": DIM, "NO-BARS": RED, "NO-SIGNAL": DIM}


def print_regime_panel(open_positions: list | None = None):
    """ALGO v2 status panel (REGIME_LIVE) — regime/algo state + S/R + sentiment guide + journal.
    อ่านจากไฟล์ (bot_status, algo_state, algo_journal.summary) — display-only, 0 token, fail-soft."""
    import os
    import json as _json
    import config as _cfg
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(p):
        try:
            with open(os.path.join(_base, p), encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return {}

    st = _read(os.path.join("logs", "bot_status.json"))
    try:
        from agents.algo_state import read_state
        astate = read_state()
    except Exception:
        astate = {}
    try:
        from agents.algo_journal import summary as _jsum
        js = _jsum()
    except Exception:
        js = {}

    lines: list[str] = []
    # ── 1. regime → algo state ──
    regime = astate.get("regime") or "—"
    state  = astate.get("state") or "—"
    rc = _REGIME_COLOR.get(regime, WHITE); sc = _STATE_COLOR.get(state, WHITE)
    detail = astate.get("detail") or ""
    lines.append(f"  [{rc}]{regime:<9}[/] → [{sc}]{state}[/]   [dim]{detail}[/dim]")
    # ── 2. mode + flags ──
    tick = "on" if getattr(_cfg, "REGIME_LIVE_TICK", False) else "off"
    loop = int(os.getenv("REGIME_LOOP_SECS") or 15)
    fl = lambda name, on: f"[{GREEN}]{name}[/]" if on else f"[dim]{name}[/dim]"
    flags = " ".join([
        fl("SR_ENTRY", getattr(_cfg, "REGIME_SR_ENTRY", False)),
        fl("SR_EXIT",  getattr(_cfg, "REGIME_SR_EXIT", False)),
        fl("SR_SIZE",  getattr(_cfg, "REGIME_SR_SIZING", False)),
        fl("PEND",     getattr(_cfg, "REGIME_PENDING", False)),
        fl("FADE",     getattr(_cfg, "REGIME_PENDING_FADE", False)),
    ])
    lines.append(f"  [dim]entry[/dim] tick {tick} 3s · [dim]loop[/dim] {loop}s   {flags}")
    # ── 3. price + nearest S/R ──
    px = (st.get("price_info") or {}).get("bid")
    srm = ((st.get("zones") or {}).get("sr_meta")) or []
    if px is not None:
        res = [z for z in srm if z.get("side") == "R" and z.get("level", 0) > px]
        sup = [z for z in srm if z.get("side") == "S" and z.get("level", 0) < px]
        nr = min(res, key=lambda z: z["level"] - px) if res else None
        ns = max(sup, key=lambda z: z["level"]) if sup else None
        rtxt = f"[{RED}]R {nr['level']:.1f}[/]([dim]{nr.get('tf','')}·{nr.get('grade','')}[/dim])" if nr else "[dim]R —[/dim]"
        stxt = f"[{GREEN}]S {ns['level']:.1f}[/]([dim]{ns.get('tf','')}·{ns.get('grade','')}[/dim])" if ns else "[dim]S —[/dim]"
        lines.append(f"  [dim]price[/dim] [bold]{px:.1f}[/bold]   {rtxt}  {stxt}")
    # ── 4. sentiment (guide only) ──
    sent = st.get("sentiment", "—"); sconf = st.get("sent_conf", 0)
    sbias = st.get("sent_bias", ""); stw = st.get("sent_tweets", 0)
    sent_c = GREEN if sent == "BULLISH" else (RED if sent == "BEARISH" else DIM)
    lines.append(f"  [dim]sentiment[/dim] [{sent_c}]{sent} {sconf}%[/] [dim]guide[/dim] {sbias} · {stw} tweets")
    # ── 5. positions ──
    if open_positions is not None:
        algo = [p for p in open_positions if str(p.get("comment") or "").startswith("ALGO")]
        legacy = [p for p in open_positions if not str(p.get("comment") or "").startswith("ALGO")]
        pnl = sum(float(p.get("profit", 0) or 0) for p in open_positions)
        pc = GREEN if pnl >= 0 else RED
        lines.append(f"  [dim]positions[/dim] ALGO {len(algo)} · legacy {len(legacy)}   [{pc}]{pnl:+.0f}฿[/]")
    # ── 6. journal counterfactual ──
    mom = js.get("momentum") or {}; fade = js.get("fade") or {}

    def _jline(tag, d):
        if not d or d.get("n_closed", 0) == 0:
            return f"[dim]{tag} n=0[/dim]"
        exp = d.get("exp_R", 0); ec = GREEN if exp > 0 else RED
        return f"{tag} n={d['n_closed']} [{ec}]exp{exp:+.2f}R[/] wr{int(d.get('win_rate',0)*100)}%"
    lines.append(f"  [dim]journal[/dim] {_jline('mom', mom)} · {_jline('fade', fade)} [dim](shadow)[/dim]")
    # ── owner-gate advisory (เตือน mid-vol / manual short — regime ที่ owner เสียต่อเนื่อง) ──
    try:
        from agents.owner_gate import owner_gate_now
        for w in (owner_gate_now().get("warnings") or []):
            lines.append(f"  [{RED}]⚠ OWNER-GATE[/] [{GOLD}]{w.get('tag','')}[/] [dim]{w.get('msg','')}[/dim]")
    except Exception:
        pass

    console.print(Panel("\n".join(lines), title=f"[bold {GOLD}]ALGO v2 · REGIME_LIVE[/]",
                        border_style=GOLD, padding=(0, 1), box=box.ROUNDED))


def print_signal_box(chart_data: dict):
    signal     = chart_data.get("signal", "NO_TRADE")
    conf       = chart_data.get("confidence", 0)
    trend      = chart_data.get("trend", "—")
    sr_z       = chart_data.get("sr_zone", "—")
    sr_s       = chart_data.get("sr_strength", "—")
    entry_type = chart_data.get("entry_type", "—")
    entry_score= chart_data.get("entry_score", 0)
    atr        = chart_data.get("indicators", {}).get("h4", {}).get("atr", 0)
    conf_count = chart_data.get("scan", {}).get("confluence_count", 0)
    momentum   = chart_data.get("momentum", "—")
    mom_tf     = chart_data.get("momentum_tf", {})
    fib_h4     = chart_data.get("fib_h4", {})
    fib_h1     = chart_data.get("fib_h1", {})

    sig_color = GREEN if signal == "BUY" else RED if signal == "SELL" else DIM
    atr_str   = f"{atr:.2f}" if atr else "—"

    if "UP" in momentum:
        mom_color = GREEN
    elif "DOWN" in momentum:
        mom_color = RED
    else:
        mom_color = DIM

    # Fib nearest level — highlight key levels
    fib_h4_n = fib_h4.get("nearest") or {}
    fib_color = GOLD if fib_h4_n.get("is_key") and fib_h4_n.get("in_zone") else DIM

    lines = [
        _kv2("Signal",      f"[bold {sig_color}]{signal}[/]",
             "Confidence",  f"[bold]{conf}%[/]"),
        _kv2("Trend",       trend,
             "Entry Type",  entry_type),
        _kv2("Momentum",    f"[bold {mom_color}]{momentum}[/]",
             "TF Detail",   f"[dim]{_momentum_str(mom_tf)}[/dim]"),
        _kv2("Fib H4",      f"[{fib_color}]{_fib_display(fib_h4)}[/]",
             "", ""),
        _kv2("Fib H1",      f"[dim]{_fib_display(fib_h1)}[/dim]",
             "", ""),
        _kv2("Setup Score", f"{entry_score}  ({conf_count} confluences)",
             "S/R Zone",    f"{sr_z} / {sr_s}"),
        _kv2("ATR (H4)",    atr_str,
             "", ""),
    ]
    console.print(Panel("\n".join(lines), title="[bold yellow]Technical Signal[/]",
                        border_style="dim yellow", padding=(0, 0)))


def print_advisor_box(advisor: dict):
    regime    = advisor.get("regime", "—")
    conf      = advisor.get("regime_confidence", 0)
    bias      = advisor.get("bias", "NEUTRAL")
    vol       = advisor.get("volatility", "—")
    tp_s      = advisor.get("tp_style", "—")
    best      = ", ".join(advisor.get("best_indicators", [])) or "—"
    top_setup = advisor.get("top_setup", "NO_DATA")
    h4        = advisor.get("intraday_h4",  "—")
    h1        = advisor.get("intraday_h1",  "—")
    m15       = advisor.get("intraday_m15", "—")
    note      = advisor.get("advisor_note", "")

    regime_color = (GREEN if "BULL" in regime else
                    RED   if "BEAR" in regime else
                    GOLD  if "TRANS" in regime else DIM)
    bias_color   = GREEN if bias == "BULLISH" else RED if bias == "BEARISH" else DIM
    vol_color    = RED if vol == "HIGH" else GREEN if vol == "LOW" else WHITE
    top_color    = GREEN if top_setup != "NO_DATA" else DIM

    lines = [
        _kv2("Regime",     f"[bold {regime_color}]{regime}[/]",
             "Confidence", f"[bold]{conf}%[/]"),
        _kv2("Bias",       f"[bold {bias_color}]{bias}[/]",
             "TP Style",   f"[bold]{tp_s}[/]"),
        _kv2("Volatility", f"[{vol_color}]{vol}[/]",
             "Structure",  f"[dim]H4={h4}  H1={h1}  M15={m15}[/dim]"),
        _kv("Best (log)",  f"[{top_color}]{top_setup[:65]}[/]"),
        _kv("Indicators",  f"[dim]{best[:65]}[/dim]"),
    ]
    if note:
        lines.append(_kv("Advice", f"[italic dim]{note[:65]}[/italic dim]"))

    console.print(Panel("\n".join(lines), title="[bold magenta]Market Advisor[/]",
                        border_style="dim magenta", padding=(0, 0)))


def print_sentiment_box(sent_data: dict):
    sentiment = sent_data.get("sentiment", "NEUTRAL")
    conf      = sent_data.get("confidence", 0)
    summary   = (sent_data.get("summary", "—") or "—")[:70]
    count     = sent_data.get("news_count", 0)

    sent_color = GREEN if "BULL" in sentiment else RED if "BEAR" in sentiment else DIM

    lines = [
        _kv2("Sentiment",   f"[bold {sent_color}]{sentiment}[/]",
             "Confidence",  f"[bold]{conf}%[/]"),
        _kv2("News count",  str(count),
             "Summary",     f"[dim]{summary}[/dim]"),
    ]
    console.print(Panel("\n".join(lines), title="[bold cyan]Market Sentiment[/]",
                        border_style="dim cyan", padding=(0, 0)))


def print_decision_box(decision: dict):
    action = decision.get("action", "SKIP")
    reason = decision.get("reason", "")

    if action == "EXECUTE":
        direction = decision.get("direction", "")
        order     = decision.get("order", {})
        ticket    = order.get("ticket", "—")
        lot       = order.get("lot", 0)
        price     = order.get("price", 0)
        sl        = order.get("sl", 0)
        tp        = order.get("tp", 0)
        dir_color = GREEN if direction == "BUY" else RED

        lines = [
            _kv2("Decision",  "[bold green]EXECUTE[/]",
                 "Direction", f"[bold {dir_color}]{direction}[/]"),
            _kv2("Ticket",    f"[bold]{ticket}[/]",
                 "Lot",       f"[bold]{lot:.2f}[/]"),
            _kv2("Entry",     f"{price:.2f}",
                 "SL / TP",   f"[red]{sl:.2f}[/]  /  [green]{tp:.2f}[/]"),
        ]
        console.print(Panel("\n".join(lines), title="[bold green]✓ ORDER PLACED[/]",
                            border_style="green", padding=(0, 0)))

    elif action == "PENDING":
        pt      = decision.get("pending_type", "")
        pp      = decision.get("pending_price", 0)
        order   = decision.get("order", {})
        ticket  = order.get("ticket", "—")
        lot     = order.get("lot", 0)
        sl      = order.get("sl", 0)
        tp      = order.get("tp", 0)
        expiry  = (order.get("expiry", "") or "")[:16].replace("T", " ")
        success = order.get("success", False)
        pt_color = GREEN if "BUY" in pt else RED

        lines = [
            _kv2("Type",    f"[bold {pt_color}]{pt}[/]",
                 "Price",   f"[bold]{pp:.2f}[/]"),
            _kv2("Ticket",  f"[bold]{ticket}[/]",
                 "Lot",     f"[bold]{lot:.2f}[/]" if lot else "—"),
            _kv2("SL / TP", f"[red]{sl:.2f}[/]  /  [green]{tp:.2f}[/]",
                 "Expiry",  f"[dim]{expiry}[/dim]"),
        ]
        title  = "[bold yellow]PENDING PLACED[/]" if success else "[bold red]PENDING FAILED[/]"
        border = "yellow" if success else "red"
        console.print(Panel("\n".join(lines), title=title, border_style=border, padding=(0, 0)))

    else:
        short = (reason or "").split("\n")[0][:80]
        console.print(Panel(
            f"  [dim]{short or 'No signal'}[/dim]",
            title="[bold dim]— SKIP[/]",
            border_style="dim", padding=(0, 0)
        ))


def print_account_summary(account: dict, open_positions: list, history: dict, protected: int = 0):
    bal    = account.get("balance", 0)
    eq     = account.get("equity", 0)
    cur    = account.get("currency", "USD")
    pnl    = sum(p.get("profit", 0) for p in open_positions)
    winrate= history["last_10_winrate"]
    streak = history["losing_streak"]
    max_dir = MONEY_MANAGEMENT["max_open_trades"] + protected
    buy_n   = sum(1 for p in open_positions if p.get("direction") == "BUY")
    sell_n  = sum(1 for p in open_positions if p.get("direction") == "SELL")
    prot_s  = f" +{protected}🔒" if protected else ""
    pos_str = f"B:{buy_n} S:{sell_n} / {max_dir}/dir{prot_s}"

    pnl_color    = GREEN if pnl >= 0 else RED
    streak_color = RED if streak > 0 else GREEN
    streak_str   = f"[{streak_color}]{streak} losing[/]" if streak > 0 else f"[{streak_color}]none[/]"

    acc_lines = [
        _kv2("Balance",   f"{bal:,.2f} {cur}",
             "Equity",    f"{eq:,.2f} {cur}"),
        _kv2("Open P&L",  f"[{pnl_color}]{pnl:+.2f}[/]",
             "Open Pos",  pos_str),
        _kv2("Win Rate",  f"[yellow]{winrate}%[/] (last 10)",
             "Streak",    streak_str),
    ]
    console.print(Panel("\n".join(acc_lines), title="[bold white]Account Summary[/]",
                        border_style="dim white", padding=(0, 0)))

    # ─── Recent trades table (ASCII headers only) ─────────────
    recent = history.get("recent_trades", [])
    if not recent:
        return

    t = Table(box=box.SIMPLE_HEAD, show_header=True, padding=(0, 1),
              header_style="dim white", show_edge=False)
    t.add_column("Time",   width=16, style="dim white",  no_wrap=True)
    t.add_column("Src",    width=4,  justify="center",   no_wrap=True)
    t.add_column("Dir",    width=5,  justify="center",   no_wrap=True)
    t.add_column("Entry",  width=18, no_wrap=True)
    t.add_column("PA",     width=12, no_wrap=True)
    t.add_column("P&L",    width=10, justify="right",    no_wrap=True)
    t.add_column("Result", width=5,  justify="center",   no_wrap=True)

    for tr in recent:
        p         = tr.get("pnl") or 0
        result    = "WIN" if p > 0 else "LOSS"
        direction = tr.get("direction", "—")
        src       = (tr.get("source", "SYS") or "SYS")[:3]
        entry     = (tr.get("entry_type") or "—")[:17]
        pa        = (tr.get("pa_action")  or "—")[:11]
        ts        = (tr.get("timestamp", "")[:16]).replace("T", " ")

        dir_style = f"bold {GREEN}" if direction == "BUY" else f"bold {RED}"
        res_style = GREEN if result == "WIN" else RED
        pnl_style = GREEN if p >= 0 else RED
        src_style = CYAN if src == "SYS" else GOLD

        t.add_row(
            ts,
            f"[{src_style}]{src}[/]",
            f"[{dir_style}]{direction}[/]",
            entry, pa,
            f"[{pnl_style}]{p:+.2f}[/]",
            f"[{res_style}]{result}[/]",
        )

    console.print(Panel(t, title="[bold white]Recent Trades[/]",
                        border_style="dim white", padding=(0, 0)))


def print_performance_report(report: str):
    console.print(Panel(report, title="[bold yellow]Performance Analysis[/]",
                        border_style="yellow", padding=(1, 2)))


def print_ready_mode_banner(zone: dict | None, status: str = "WATCHING",
                            m5_pa: dict | None = None,
                            counter_pressure: bool = False) -> None:
    """
    status: ENTER | WATCHING | EXIT
    zone  : htf_zone dict {"tf","level","zone_type","dist_pct"}
    """
    if status == "EXIT":
        console.print(Panel(
            "[dim]ราคาออกจาก HTF zone — ออกจาก Ready Mode[/dim]",
            title="[bold dim]⚡ READY MODE — EXIT[/bold dim]",
            border_style="dim", padding=(0, 1),
        ))
        return

    tf   = zone["tf"] if zone else "?"
    lv   = zone["level"] if zone else 0
    zt   = zone["zone_type"] if zone else "?"
    dist = zone["dist_pct"] if zone else 0

    action    = "BUY" if zt == "SUPPORT" else "SELL"
    direction = "↑ BUY bounce" if action == "BUY" else "↓ SELL rejection"

    lines = [
        f"[bold yellow]{tf} {zt}[/bold yellow] @ [bold white]{lv}[/bold white]  "
        f"(ห่าง [cyan]{dist}%[/cyan])",
        f"คาด: [bold {'green' if action == 'BUY' else 'red'}]{direction}[/bold {'green' if action == 'BUY' else 'red'}]",
    ]

    if counter_pressure:
        lines.append("[yellow]⚠ ไม่มีข่าวสนับสนุนทิศทางราคา → โอกาส reversal สูง[/yellow]")

    if m5_pa and m5_pa.get("available"):
        pat = m5_pa.get("candle", {}).get("patterns", ["—"])
        bias = m5_pa.get("candle", {}).get("bias", "NEUTRAL")
        rsi  = m5_pa.get("rsi", 0)
        color = "green" if bias == "BULLISH" else "red" if bias == "BEARISH" else "dim"
        lines.append(
            f"M5 PA: [{color}]{', '.join(pat[:2])}[/{color}]  "
            f"Bias:{bias}  RSI:{rsi:.0f}"
        )

    title_color = "yellow" if status == "ENTER" else "gold1"
    console.print(Panel(
        "\n".join(lines),
        title=f"[bold {title_color}]⚡ READY MODE — {status}[/bold {title_color}]",
        border_style="yellow", padding=(0, 1),
    ))


def print_error(msg: str):
    console.print(f"  [bold red]✗[/]  {msg}", style=RED)


def print_warning(msg: str):
    console.print(f"  [bold yellow]⚠[/]  {msg}", style=GOLD)


def print_info(msg: str):
    console.print(f"  [dim]·[/dim]  {msg}", style=DIM)
