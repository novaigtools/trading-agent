import time
import schedule
import requests
from datetime import datetime
from colorama import Fore, Style, init
import market_analyzer
import claude_brain
import trader
import risk_manager
import news_analyzer
from config import PAPER_TRADING, SCAN_INTERVAL_MINUTES, STARTING_BALANCE

init(autoreset=True)


def fetch_price(symbol: str) -> float:
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol}, timeout=5
        )
        return float(r.json()["price"])
    except:
        return None


def print_header():
    mode = f"{Fore.YELLOW}PAPER TRADING{Style.RESET_ALL}" if PAPER_TRADING else f"{Fore.RED}LIVE TRADING{Style.RESET_ALL}"
    print("\n" + "=" * 65)
    print(f"  CRYPTO TRADING AGENT  |  {mode}")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 65)


def print_live_positions():
    positions = risk_manager.get_open_positions()
    if not positions:
        print(f"  {Fore.YELLOW}No open positions{Style.RESET_ALL}")
        return

    total_pnl = 0.0
    print(f"\n  {'SYMBOL':<12} {'ENTRY':>10} {'NOW':>10} {'CHANGE':>8} {'P&L':>9} STATUS")
    print(f"  {'-' * 60}")

    for symbol, pos in positions.items():
        current = fetch_price(symbol)
        if current is None:
            print(f"  {symbol:<12} price unavailable")
            continue
        pnl = (current - pos["entry_price"]) * pos["quantity"]
        pnl_pct = (current - pos["entry_price"]) / pos["entry_price"] * 100
        total_pnl += pnl
        color = Fore.GREEN if pnl >= 0 else Fore.RED

        # Proximity to SL/TP
        if current <= pos["stop_loss"] * 1.01:
            status = f"{Fore.RED}⚠ NEAR SL{Style.RESET_ALL}"
        elif current >= pos["take_profit"] * 0.99:
            status = f"{Fore.GREEN}🎯 NEAR TP{Style.RESET_ALL}"
        else:
            status = "holding"

        print(
            f"  {symbol:<12} "
            f"${pos['entry_price']:>9.4f} "
            f"${current:>9.4f} "
            f"{color}{pnl_pct:>+7.2f}%{Style.RESET_ALL} "
            f"{color}${pnl:>+8.4f}{Style.RESET_ALL} "
            f"{status}"
        )

    print(f"  {'-' * 60}")
    color = Fore.GREEN if total_pnl >= 0 else Fore.RED
    print(f"  {'UNREALISED P&L':<40} {color}${total_pnl:+.4f}{Style.RESET_ALL}")

    # Add realised P&L from trades.csv
    realised = get_realised_pnl()
    color2 = Fore.GREEN if realised >= 0 else Fore.RED
    print(f"  {'REALISED P&L (closed trades)':<40} {color2}${realised:+.4f}{Style.RESET_ALL}")
    total = total_pnl + realised
    color3 = Fore.GREEN if total >= 0 else Fore.RED
    print(f"  {'TOTAL P&L':<40} {color3}${total:+.4f}{Style.RESET_ALL}")


def get_realised_pnl() -> float:
    import csv, os
    if not os.path.exists("trades.csv"):
        return 0.0
    trades = {}
    pnl = 0.0
    try:
        with open("trades.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row["symbol"]
                action = row["action"]
                price = float(row["price"])
                qty = float(row["quantity"])
                if action == "BUY":
                    trades[symbol] = {"price": price, "qty": qty}
                elif action == "SELL" and symbol in trades:
                    pnl += (price - trades[symbol]["price"]) * qty
                    del trades[symbol]
    except:
        pass
    return round(pnl, 4)


def print_sentiment_bar(sentiment: dict):
    fng = sentiment.get("fear_and_greed", {})
    news = sentiment.get("news_sentiment_summary", {})
    dominance = sentiment.get("market_dominance", {})
    trending = [c.get("symbol", "") for c in sentiment.get("trending_coins", [])[:5]]

    val = fng.get("value", 50)
    label = fng.get("label", "?")
    trend = fng.get("trend", "?")
    fng_color = Fore.GREEN if val <= 30 else (Fore.RED if val >= 70 else Fore.YELLOW)

    news_overall = news.get("overall", "NEUTRAL")
    news_color = Fore.GREEN if news_overall == "BULLISH" else (Fore.RED if news_overall == "BEARISH" else Fore.YELLOW)

    print(f"\n  {Fore.CYAN}SENTIMENT:{Style.RESET_ALL} "
          f"F&G {fng_color}{val}/100 {label} ({trend}){Style.RESET_ALL} | "
          f"News {news_color}{news_overall}{Style.RESET_ALL} "
          f"({news.get('bullish_headlines',0)}🟢 {news.get('bearish_headlines',0)}🔴) | "
          f"BTC Dom {dominance.get('btc_dominance','?')}% | "
          f"Trending: {', '.join(trending)}")


def run_scan():
    print_header()

    # Account status
    summary = risk_manager.account_summary()
    pnl_color = Fore.GREEN if summary["total_pnl"] >= 0 else Fore.RED
    print(f"\n  Equity: ${summary['equity']:.2f} | Cash: ${summary['cash']:.2f} | "
          f"{pnl_color}P&L since {summary['experiment_start']}: ${summary['total_pnl']:+.2f} ({summary['total_pnl_pct']:+.2f}%){Style.RESET_ALL}")

    if summary["cash"] < 5:
        print(f"  {Fore.YELLOW}⚠ Cash fully deployed — monitoring open positions only{Style.RESET_ALL}")

    # Live positions with P&L
    print(f"\n  {Fore.CYAN}OPEN POSITIONS:{Style.RESET_ALL}")
    print_live_positions()

    # Sentiment
    print(f"\n{Fore.CYAN}[1/4] Fetching sentiment & news...{Style.RESET_ALL}")
    try:
        sentiment = news_analyzer.get_full_sentiment_report()
        print_sentiment_bar(sentiment)
    except Exception as e:
        print(f"  Sentiment unavailable: {e}")
        sentiment = {}

    # Market regime — BTC 4H trend filter
    print(f"\n{Fore.CYAN}[2/5] Checking BTC market regime (4H)...{Style.RESET_ALL}")
    regime = market_analyzer.get_btc_market_regime()
    regime_str = regime.get("regime", "UNKNOWN")
    regime_color = Fore.GREEN if regime_str == "BULL" else (Fore.RED if regime_str == "BEAR" else Fore.YELLOW)
    print(f"  Regime: {regime_color}{regime_str}{Style.RESET_ALL} | "
          f"BTC: ${regime.get('price','?'):,.0f} | "
          f"EMA structure: {regime.get('ema_structure','?')} | "
          f"4H RSI: {regime.get('rsi_4h','?')} | "
          f"Bull/Bear signals: {regime.get('bull_signals',0)}/{regime.get('bear_signals',0)}")

    # Market data
    print(f"\n{Fore.CYAN}[3/5] Fetching market data...{Style.RESET_ALL}")
    market_data_list = market_analyzer.analyze_all_pairs()
    current_prices = {d["symbol"]: d["price"] for d in market_data_list if "price" in d}

    # Stop loss / take profit (always runs regardless of regime)
    print(f"\n{Fore.CYAN}[4/5] Checking stop-loss / take-profit...{Style.RESET_ALL}")
    trader.check_and_execute_stops(current_prices)

    # Claude decisions — hard block in BEAR regime
    if summary["cash"] < 5:
        print(f"\n{Fore.CYAN}[5/5] Skipping — cash fully deployed{Style.RESET_ALL}")
        print(f"  New buys resume when a position closes and frees up cash.")
    elif regime_str == "BEAR":
        print(f"\n{Fore.RED}[5/5] MARKET REGIME: BEAR — No new trades{Style.RESET_ALL}")
        print(f"  BTC 4H trend is down. Holding cash to protect capital.")
        print(f"  Bot will resume buying when BTC 4H structure turns NEUTRAL or BULL.")
    else:
        regime_note = f"⚠ NEUTRAL market — higher confidence required" if regime_str == "NEUTRAL" else "✅ BULL market"
        print(f"\n{Fore.CYAN}[5/5] Getting Claude decisions... ({regime_note}){Style.RESET_ALL}")
        decisions = claude_brain.get_decisions_for_all(market_data_list, sentiment, regime)
        any_trade = False
        for decision in decisions:
            executed = trader.execute_decision(decision)
            if executed:
                any_trade = True
        if not any_trade:
            print(f"  {Fore.YELLOW}No trades — waiting for better setups{Style.RESET_ALL}")

    print(f"\n  Next scan in {SCAN_INTERVAL_MINUTES} minutes...\n")


def main():
    print(f"\n{Fore.GREEN}Starting Crypto Trading Agent...{Style.RESET_ALL}")
    print(f"  Mode: {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
    print(f"  Paper account: ${STARTING_BALANCE:.2f}")
    print(f"  Scan interval: every {SCAN_INTERVAL_MINUTES} minutes")
    print(f"  Sentiment feeds: Fear & Greed + News + Trending + Dominance")

    run_scan()
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scan)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
