import csv
import os
from datetime import datetime
from colorama import Fore, Style, init
import risk_manager
import notifier
from config import PAPER_TRADING

init(autoreset=True)

TRADE_LOG = "trades.csv"


def _ensure_log():
    if not os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "symbol", "action", "price", "quantity",
                "value_usd", "reason", "confidence", "trade_type", "mode"
            ])


def log_trade(symbol: str, action: str, price: float, quantity: float,
              reason: str, confidence: int, trade_type: str):
    _ensure_log()
    mode = "PAPER" if PAPER_TRADING else "LIVE"
    value = round(price * quantity, 2)
    row = [
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        symbol, action, price, quantity, value,
        reason, confidence, trade_type, mode
    ]
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow(row)
    return value


def execute_decision(decision: dict) -> bool:
    symbol = decision.get("symbol")
    action = decision.get("action")
    confidence = decision.get("confidence", 0)
    trade_type = decision.get("trade_type", "intraday")
    price = decision.get("market_price") or decision.get("entry_price")
    reasoning = decision.get("reasoning", "")

    if action == "HOLD" or confidence < 7:
        print(f"  {Fore.YELLOW}{symbol}: HOLD (confidence {confidence}/10){Style.RESET_ALL}")
        return False

    if action == "BUY":
        open_positions = risk_manager.get_open_positions()
        if symbol in open_positions:
            print(f"  {Fore.YELLOW}{symbol}: Already holding — skipping BUY{Style.RESET_ALL}")
            return False

        quantity = risk_manager.get_position_size(price, symbol)
        if quantity == 0:
            print(f"  {Fore.RED}{symbol}: Insufficient weekly budget remaining{Style.RESET_ALL}")
            return False

        value = log_trade(symbol, "BUY", price, quantity, reasoning, confidence, trade_type)
        risk_manager.record_trade(symbol, "BUY", price, quantity)

        mode_tag = "[PAPER]" if PAPER_TRADING else "[LIVE]"
        print(f"  {Fore.GREEN}{mode_tag} BUY {symbol} | {quantity} @ ${price:,.4f} = ${value:.2f} | Confidence: {confidence}/10{Style.RESET_ALL}")
        print(f"  Reason: {reasoning}")
        notifier.send_trade_email(symbol, "BUY", price, quantity, value, None, confidence, reasoning)
        return True

    if action == "SELL":
        open_positions = risk_manager.get_open_positions()
        if symbol not in open_positions:
            print(f"  {Fore.YELLOW}{symbol}: No open position to sell{Style.RESET_ALL}")
            return False

        pos = open_positions[symbol]
        quantity = pos["quantity"]
        value = log_trade(symbol, "SELL", price, quantity, reasoning, confidence, trade_type)
        risk_manager.record_trade(symbol, "SELL", price, quantity)

        entry = pos["entry_price"]
        pnl = round((price - entry) * quantity, 4)
        pnl_pct = round((price - entry) / entry * 100, 2)
        color = Fore.GREEN if pnl >= 0 else Fore.RED
        mode_tag = "[PAPER]" if PAPER_TRADING else "[LIVE]"
        print(f"  {color}{mode_tag} SELL {symbol} | {quantity} @ ${price:,.4f} = ${value:.2f} | P&L: ${pnl} ({pnl_pct}%){Style.RESET_ALL}")
        notifier.send_trade_email(symbol, "SELL", price, quantity, value, pnl, confidence, reasoning)
        return True

    return False


def check_and_execute_stops(current_prices: dict):
    triggers = risk_manager.check_stop_loss_take_profit(current_prices)
    for trigger in triggers:
        label = "STOP LOSS" if trigger["reason"] == "stop_loss" else "TAKE PROFIT"
        decision = {
            "symbol": trigger["symbol"],
            "action": "SELL",
            "confidence": 10,
            "reasoning": f"Automated {label} triggered",
            "trade_type": "intraday",
            "market_price": trigger["price"],
        }
        print(f"  {Fore.CYAN}Auto-{label} triggered for {trigger['symbol']}{Style.RESET_ALL}")
        execute_decision(decision)
