"""
One-shot forced $5 paper trade — used to verify the bot pipeline works end-to-end.
Uses only Python built-ins (no pip install needed).
"""
import json, csv, os, urllib.request
from datetime import datetime

RISK_FILE   = "risk_state.json"
TRADES_FILE = "trades.csv"
SYMBOL      = "WIFUSDT"   # Penny coin — good for a small test
TARGET_USD  = 5.0         # $5 test trade

def fetch_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return float(json.loads(r.read())["price"])

def load_state():
    if os.path.exists(RISK_FILE):
        with open(RISK_FILE) as f:
            return json.load(f)
    return {"week_start": "", "spent_this_week": 0.0, "open_positions": {}}

def save_state(state):
    with open(RISK_FILE, "w") as f:
        json.dump(state, f, indent=2)

def log_trade(symbol, price, quantity):
    value   = round(price * quantity, 4)
    ts      = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row     = [ts, symbol, "BUY", price, quantity, value,
               "FORCE TEST TRADE — verifying bot pipeline", 10, "intraday", "PAPER"]
    write_header = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["timestamp","symbol","action","price","quantity",
                        "value_usd","reason","confidence","trade_type","mode"])
        w.writerow(row)
    print(f"  Logged to trades.csv OK")
    return value

def run():
    print(f"\n  Force Trade Test — {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {'-'*50}")

    price    = fetch_price(SYMBOL)
    quantity = round(TARGET_USD / price, 6)
    sl       = round(price * 0.97, 6)   # 3% stop loss
    tp       = round(price * 1.09, 6)   # 9% take profit

    print(f"  Symbol:   {SYMBOL}")
    print(f"  Price:    ${price}")
    print(f"  Quantity: {quantity}")
    print(f"  Cost:     ${round(price * quantity, 4)}")
    print(f"  SL:       ${sl}  |  TP: ${tp}")

    state = load_state()
    state["spent_this_week"] = round(state.get("spent_this_week", 0) + (price * quantity), 4)
    state["open_positions"][SYMBOL] = {
        "entry_price": price,
        "quantity":    quantity,
        "stop_loss":   sl,
        "take_profit": tp,
        "opened_at":   datetime.utcnow().isoformat(),
        "is_penny":    True,
    }
    save_state(state)
    print(f"  Updated risk_state.json OK")

    value = log_trade(SYMBOL, price, quantity)

    print(f"\n  [OK] PAPER BUY {SYMBOL} — {quantity} @ ${price} = ${value}")
    print(f"  Check dashboard: https://novaigtools.github.io/trading-agent/")

if __name__ == "__main__":
    run()
