"""
One-shot small PAPER test buy — verifies the bot pipeline end-to-end.
Runs through the REAL production code path (risk_manager + trader), so the
position is booked, sized, and stop-lossed exactly as an auto-scan buy would be,
then picked up by the 5-minute SL/TP monitor automatically.

Usage:  python force_trade.py [SYMBOL] [USD_AMOUNT]
        python force_trade.py WIFUSDT 10
"""
import sys
import requests
import risk_manager
import trader

DEFAULT_SYMBOL = "WIFUSDT"
DEFAULT_USD    = 10.0


def fetch_price(symbol: str) -> float:
    r = requests.get("https://api.binance.com/api/v3/ticker/price",
                     params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])


def run(symbol: str, usd: float):
    print(f"\n  Small PAPER test buy — {symbol} for ~${usd:.2f}")
    print(f"  {'-'*50}")

    before = risk_manager.account_summary()
    print(f"  Before: cash=${before['cash']:.2f} | equity=${before['equity']:.2f} | positions={before['open_positions']}")

    if symbol in risk_manager.get_open_positions():
        print(f"  {symbol} is already open — skipping to avoid a duplicate. Nothing changed.")
        return

    price = fetch_price(symbol)
    quantity = round(usd / price, 6)

    # Real production path: logs to trades.csv, books cash, sets tier-based SL/TP
    value = trader.log_trade(symbol, "BUY", price, quantity,
                             "Manual $10 test buy — verifying live pipeline", 10, "intraday")
    risk_manager.record_trade(symbol, "BUY", price, quantity)

    pos = risk_manager.get_open_positions()[symbol]
    after = risk_manager.account_summary({symbol: price})
    print(f"\n  [OK] BOUGHT {quantity} {symbol} @ ${price} = ${value:.2f}")
    print(f"       stop-loss ${pos['stop_loss']}  |  take-profit ${pos['take_profit']}")
    print(f"  After:  cash=${after['cash']:.2f} | equity=${after['equity']:.2f} | positions={after['open_positions']}")
    print(f"\n  The 5-minute SL/TP monitor will now manage this position automatically.")
    print(f"  Watch it on the dashboard: https://novaigtools.github.io/trading-agent/")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYMBOL
    amt = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_USD
    run(sym, amt)
