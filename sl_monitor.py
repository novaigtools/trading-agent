"""
Lightweight Stop-Loss / Take-Profit monitor.
Uses ONLY Python built-ins (no pip install needed) — runs in ~5 seconds.
Designed to run every 5 minutes on GitHub Actions within the free tier.
"""
import json
import csv
import os
import urllib.request
import urllib.parse
from datetime import datetime

RISK_FILE  = "risk_state.json"
TRADES_FILE = "trades.csv"


def fetch_price(symbol: str) -> float:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    with urllib.request.urlopen(url, timeout=5) as r:
        return float(json.loads(r.read())["price"])


def load_state() -> dict:
    if not os.path.exists(RISK_FILE):
        return {"week_start": "", "spent_this_week": 0, "open_positions": {}}
    with open(RISK_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    with open(RISK_FILE, "w") as f:
        json.dump(state, f, indent=2)


def log_trade(symbol, price, quantity, reason):
    value = round(price * quantity, 2)
    ts    = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row   = f"{ts},{symbol},SELL,{price},{quantity},{value},{reason},10,intraday,PAPER"
    write_header = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a") as f:
        if write_header:
            f.write("timestamp,symbol,action,price,quantity,value_usd,reason,confidence,trade_type,mode\n")
        f.write(row + "\n")
    print(f"  [{reason}] {symbol} SELL @ ${price}  |  value: ${value}")


def run():
    state     = load_state()
    positions = state.get("open_positions", {})

    if not positions:
        print("  No open positions — nothing to monitor.")
        return

    triggered = []
    for symbol, pos in list(positions.items()):
        try:
            price = fetch_price(symbol)
            entry = pos["entry_price"]
            sl    = pos["stop_loss"]
            tp    = pos["take_profit"]
            pct   = (price - entry) / entry * 100
            pnl   = (price - entry) * pos["quantity"]
            print(f"  {symbol:<12} entry=${entry}  now=${price}  {pct:+.2f}%  P&L=${pnl:+.2f}  SL={sl}  TP={tp}")

            if price <= sl:
                reason = "Automated STOP LOSS triggered"
                log_trade(symbol, price, pos["quantity"], reason)
                # Recycle capital
                original_cost = pos["entry_price"] * pos["quantity"]
                state["spent_this_week"] = max(0, state["spent_this_week"] - original_cost)
                del state["open_positions"][symbol]
                triggered.append(f"SL {symbol} @ ${price}  P&L=${pnl:+.2f}")

            elif price >= tp:
                reason = "Automated TAKE PROFIT triggered"
                log_trade(symbol, price, pos["quantity"], reason)
                original_cost = pos["entry_price"] * pos["quantity"]
                state["spent_this_week"] = max(0, state["spent_this_week"] - original_cost)
                del state["open_positions"][symbol]
                triggered.append(f"TP {symbol} @ ${price}  P&L=${pnl:+.2f}")

        except Exception as e:
            print(f"  Could not check {symbol}: {e}")

    if triggered:
        save_state(state)
        print(f"\n  EXECUTED: {len(triggered)} trade(s):")
        for t in triggered:
            print(f"    {t}")
    else:
        print(f"\n  All {len(positions)} position(s) within range — no action needed.")


if __name__ == "__main__":
    print(f"\n  SL/TP Monitor  —  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {'─'*50}")
    run()
