import os
import csv
import json
import time
import requests
import plotext as plt
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.columns import Columns
from rich.rule import Rule
from rich.align import Align
from rich import box

RISK_FILE = "risk_state.json"
TRADES_FILE = "trades.csv"
BINANCE = "https://api.binance.com"
REFRESH = 30

console = Console()


# ── Data ─────────────────────────────────────────────────────────

def load_state():
    if not os.path.exists(RISK_FILE):
        return {"week_start": "-", "spent_this_week": 0, "open_positions": {}}
    with open(RISK_FILE) as f:
        return json.load(f)

def fetch_price(symbol):
    try:
        r = requests.get(f"{BINANCE}/api/v3/ticker/price", params={"symbol": symbol}, timeout=5)
        return float(r.json()["price"])
    except:
        return None

def fetch_klines(symbol, interval="1h", limit=24):
    try:
        r = requests.get(f"{BINANCE}/api/v3/klines",
                         params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=8)
        return [float(c[4]) for c in r.json()]
    except:
        return []

def fetch_fng():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except:
        return {"value": 50, "label": "Neutral"}

def fetch_news():
    try:
        r = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest", timeout=8)
        articles = r.json().get("Data", [])[:8]
        bull_kw = ["surge","rally","bull","breakout","gain","rise","pump","moon","adoption","record","soar"]
        bear_kw = ["crash","dump","bear","drop","fall","hack","ban","fear","panic","decline","warning","plunge"]
        bull = bear = neutral = 0
        headlines = []
        for a in articles:
            t = a["title"].lower()
            b = sum(1 for w in bull_kw if w in t)
            br = sum(1 for w in bear_kw if w in t)
            if b > br:   bull += 1;    icon = "🟢"
            elif br > b: bear += 1;    icon = "🔴"
            else:         neutral += 1; icon = "⚪"
            headlines.append(f"{icon} {a['title'][:62]}")
        overall = "BULLISH" if bull > bear else ("BEARISH" if bear > bull else "NEUTRAL")
        return {"overall": overall, "bull": bull, "bear": bear, "neutral": neutral, "headlines": headlines[:5]}
    except Exception as e:
        return {"overall": "N/A", "bull": 0, "bear": 0, "neutral": 0, "headlines": [f"⚠ News unavailable: {e}"]}

def load_trades():
    trades = []
    if not os.path.exists(TRADES_FILE):
        return trades
    with open(TRADES_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
    return trades

def calc_realised(trades):
    book = {}; pnl = 0.0
    for t in trades:
        sym, action = t["symbol"], t["action"]
        price, qty = float(t["price"]), float(t["quantity"])
        if action == "BUY":
            book[sym] = {"price": price, "qty": qty}
        elif action == "SELL" and sym in book:
            pnl += (price - book[sym]["price"]) * qty
            del book[sym]
    return round(pnl, 4)


# ── Sparkline ────────────────────────────────────────────────────

def sparkline(prices, width=38, height=7):
    if len(prices) < 2:
        return "[dim]No chart data[/dim]"
    plt.clf()
    plt.plot_size(width, height)
    plt.theme("dark")
    color = "green" if prices[-1] >= prices[0] else "red"
    plt.plot(prices, color=color, marker="braille")
    plt.xfrequency(0)
    plt.yfrequency(2)
    return plt.build()


# ── Sections ─────────────────────────────────────────────────────

def section_header(now):
    console.print(Rule(
        f"[bold cyan]🤖 CRYPTO TRADING AGENT[/]  [dim]──[/]  [bold white]LIVE DASHBOARD[/]  [dim]──[/]  [bold white]{now} UTC[/]",
        style="cyan"
    ))

def section_overview(state, positions, prices, trades):
    budget = 100.0
    spent = state.get("spent_this_week", 0)
    remaining = budget - spent
    realised = calc_realised(trades)
    unrealised = sum(
        (prices.get(s, p["entry_price"]) - p["entry_price"]) * p["quantity"]
        for s, p in positions.items() if prices.get(s)
    )
    total = realised + unrealised

    def col(v):
        return "bold green" if v >= 0 else "bold red"

    grid = Table.grid(expand=True, padding=(0, 4))
    for _ in range(4): grid.add_column(justify="center", ratio=1)

    grid.add_row(
        Text("TOTAL P&L", style="dim"),
        Text("REALISED", style="dim"),
        Text("UNREALISED", style="dim"),
        Text("BUDGET LEFT", style="dim"),
    )
    grid.add_row(
        Text(f"${total:+.4f}", style=col(total)),
        Text(f"${realised:+.4f}", style=col(realised)),
        Text(f"${unrealised:+.4f}", style=col(unrealised)),
        Text(f"${remaining:.2f}", style="bold green" if remaining > 10 else "bold red"),
    )
    console.print(Panel(grid, title="[bold white]Portfolio Overview[/]",
                        border_style="bright_blue", padding=(1, 2)))

def section_positions(positions, prices):
    if not positions:
        console.print(Panel("[yellow]No open positions[/]",
                            title="[bold white]Open Positions[/]", border_style="bright_blue"))
        return

    t = Table(box=box.SIMPLE_HEAVY, expand=True, header_style="bold cyan", show_edge=True)
    t.add_column("Coin",    width=8)
    t.add_column("Entry",   justify="right", width=12)
    t.add_column("Now",     justify="right", width=12)
    t.add_column("Change",  justify="right", width=8)
    t.add_column("P&L",     justify="right", width=11)
    t.add_column("SL ──── Position ──── TP", min_width=36)
    t.add_column("Status",  justify="center", width=10)

    for sym, pos in positions.items():
        cur = prices.get(sym)
        if cur is None:
            t.add_row(sym, "?", "?", "?", "?", "unavailable", "⚠")
            continue

        entry = pos["entry_price"]
        sl    = pos["stop_loss"]
        tp    = pos["take_profit"]
        qty   = pos["quantity"]
        pnl   = (cur - entry) * qty
        pct   = (cur - entry) / entry * 100
        c     = "green" if pnl >= 0 else "red"

        # Progress bar SL → cur → TP
        bar_w   = 26
        rng     = tp - sl if tp != sl else 1
        prog    = max(0.0, min(1.0, (cur - sl) / rng))
        filled  = int(prog * bar_w)
        bar     = Text()
        bar.append(f"${sl:.4f} ", style="red")
        bar.append("█" * filled,          style=c)
        bar.append("░" * (bar_w - filled), style="dim")
        bar.append(f" ${tp:.4f}", style="green")

        if cur <= sl * 1.008:   status = Text("⚠ NEAR SL", style="bold red")
        elif cur >= tp * 0.992: status = Text("🎯 NEAR TP", style="bold green")
        else:                   status = Text("● holding", style="dim")

        t.add_row(
            Text(sym.replace("USDT",""), style="bold white"),
            Text(f"${entry:.4f}", style="dim"),
            Text(f"${cur:.4f}",   style="bold white"),
            Text(f"{pct:+.2f}%",  style=c),
            Text(f"${pnl:+.4f}",  style=f"bold {c}"),
            bar, status,
        )

    console.print(Panel(t, title="[bold white]Open Positions[/]", border_style="bright_blue"))

def section_charts_and_sentiment(positions, prices, fng, news):
    # ── Charts ────────────────────────────────
    chart_panels = []
    for sym, pos in list(positions.items())[:2]:
        data = fetch_klines(sym)
        cur  = prices.get(sym, pos["entry_price"])
        pct  = (cur - data[0]) / data[0] * 100 if data else 0
        c    = "green" if pct >= 0 else "red"
        name = sym.replace("USDT","")
        chart_panels.append(Panel(
            f"[bold white]{name}[/]  [bold {c}]{pct:+.2f}% (24h)[/]\n{sparkline(data)}",
            border_style=c, padding=(0,1)
        ))

    for sym, pos in list(positions.items())[2:4]:
        data = fetch_klines(sym)
        cur  = prices.get(sym, pos["entry_price"])
        pct  = (cur - data[0]) / data[0] * 100 if data else 0
        c    = "green" if pct >= 0 else "red"
        name = sym.replace("USDT","")
        chart_panels.append(Panel(
            f"[bold white]{name}[/]  [bold {c}]{pct:+.2f}% (24h)[/]\n{sparkline(data)}",
            border_style=c, padding=(0,1)
        ))

    # ── Sentiment ─────────────────────────────
    val   = fng.get("value", 50)
    label = fng.get("label", "Neutral")
    if val <= 25:   fng_c = "bold green";  em = "😱 Extreme Fear"
    elif val <= 45: fng_c = "bold yellow"; em = "😨 Fear"
    elif val <= 55: fng_c = "white";       em = "😐 Neutral"
    elif val <= 75: fng_c = "bold yellow"; em = "😏 Greed"
    else:           fng_c = "bold red";    em = "🤑 Extreme Greed"

    bar_w  = 28
    filled = int(val / 100 * bar_w)
    bar_c  = "green" if val < 40 else ("red" if val > 60 else "yellow")

    sent = Text()
    sent.append(f"{em}\n", style=f"bold {fng_c}")
    sent.append("█" * filled,            style=bar_c)
    sent.append("░" * (bar_w - filled),  style="dim")
    sent.append(f"  {val}/100\n\n", style=fng_c)

    news_c = "green" if news["overall"]=="BULLISH" else ("red" if news["overall"]=="BEARISH" else "yellow")
    sent.append(f"📰 News: ", style="bold white")
    sent.append(f"{news['overall']}", style=f"bold {news_c}")
    sent.append(f"   🟢{news['bull']} 🔴{news['bear']} ⚪{news['neutral']}\n\n", style="white")
    for h in news["headlines"][:4]:
        sent.append(f"{h[:64]}\n", style="dim")

    sent_panel = Panel(sent, title="[bold white]Market Sentiment[/]",
                       border_style="bright_blue", padding=(1,2))

    grid = Table.grid(expand=True)
    grid.add_column(ratio=3)
    grid.add_column(ratio=2)

    if chart_panels:
        charts_panel = Panel(
            Columns(chart_panels, equal=True, expand=True),
            title="[bold white]Price Charts (24H)[/]",
            border_style="bright_blue"
        )
        grid.add_row(charts_panel, sent_panel)
    else:
        grid.add_row(Panel("[yellow]No chart data[/]", border_style="bright_blue"), sent_panel)

    console.print(grid)

def section_history(trades):
    t = Table(box=box.SIMPLE, expand=True, header_style="bold cyan", show_edge=True)
    t.add_column("Time",       width=17)
    t.add_column("Coin",       width=8)
    t.add_column("Action",     width=9, justify="center")
    t.add_column("Price",      width=12, justify="right")
    t.add_column("Value",      width=9,  justify="right")
    t.add_column("P&L",        width=11, justify="right")
    t.add_column("Confidence", width=11, justify="center")
    t.add_column("Reason",     min_width=20)

    book = {}
    rows = []
    for tr in trades:
        sym, action = tr["symbol"], tr["action"]
        price, qty  = float(tr["price"]), float(tr["quantity"])
        val         = float(tr["value_usd"])
        conf        = tr.get("confidence", "-")
        ts          = tr["timestamp"][:16]
        reason      = tr.get("reason", "")[:40]
        if action == "BUY":
            book[sym] = price
            rows.append((ts, sym, action, price, val, None, conf, reason))
        elif action == "SELL":
            ep  = book.get(sym, price)
            pnl = (price - ep) * qty
            rows.append((ts, sym, action, price, val, pnl, conf, reason))
            book.pop(sym, None)

    for ts, sym, action, price, val, pnl, conf, reason in reversed(rows[-10:]):
        ac = "bold green" if action=="BUY" else "bold red"
        ic = "🟢 BUY" if action=="BUY" else "🔴 SELL"
        pt = (f"${pnl:+.4f}" if pnl is not None else "-")
        pc = "green" if (pnl or 0)>=0 else "red"
        t.add_row(
            ts,
            Text(sym.replace("USDT",""), style="bold white"),
            Text(ic, style=ac),
            f"${price:.4f}",
            f"${val:.2f}",
            Text(pt, style=f"bold {pc}"),
            f"{conf}/10",
            Text(reason, style="dim"),
        )

    console.print(Panel(t, title="[bold white]Trade History (last 10)[/]", border_style="bright_blue"))

def section_footer():
    console.print(Align.center(
        Text(f"⟳ Refreshes every {REFRESH}s  •  Ctrl+C to exit  •  PAPER TRADING MODE",
             style="dim")))
    console.print()


# ── Main ─────────────────────────────────────────────────────────

def draw():
    state     = load_state()
    positions = state.get("open_positions", {})
    prices    = {s: fetch_price(s) for s in positions}
    trades    = load_trades()
    fng       = fetch_fng()
    news      = fetch_news()
    now       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    os.system("cls" if os.name=="nt" else "clear")

    section_header(now)
    section_overview(state, positions, prices, trades)
    section_positions(positions, prices)
    section_charts_and_sentiment(positions, prices, fng, news)
    section_history(trades)
    section_footer()


def main():
    console.print("\n[cyan]Starting dashboard...[/]\n")
    while True:
        try:
            draw()
        except Exception as e:
            console.print(f"[red]Dashboard error: {e}[/]")
        time.sleep(REFRESH)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold cyan]Dashboard closed.[/]\n")
