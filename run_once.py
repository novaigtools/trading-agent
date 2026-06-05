"""
Single-scan version of the trading bot — used by GitHub Actions.
Runs one full scan, saves state, then exits.
"""
import os
import sys
from datetime import datetime
from colorama import Fore, Style, init
import market_analyzer
import claude_brain
import trader
import risk_manager
import news_analyzer
from config import PAPER_TRADING, WEEKLY_BUDGET

init(autoreset=True)


def main():
    print(f"\n{'=' * 60}")
    print(f"  CRYPTO TRADING BOT — GitHub Actions Run")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Mode: {'PAPER' if PAPER_TRADING else 'LIVE'} | Budget: ${WEEKLY_BUDGET}")
    print(f"{'=' * 60}\n")

    # Weekly summary
    summary = risk_manager.weekly_summary()
    print(f"  Budget: ${summary['budget']} | Spent: ${summary['spent']} | Remaining: ${summary['remaining']}")
    print(f"  Open Positions: {summary['open_positions']}\n")

    # Step 1 — Sentiment
    print(f"{Fore.CYAN}[1/4] Fetching sentiment & news...{Style.RESET_ALL}")
    try:
        sentiment = news_analyzer.get_full_sentiment_report()
        fng = sentiment.get("fear_and_greed", {})
        news = sentiment.get("news_sentiment_summary", {})
        dominance = sentiment.get("market_dominance", {})
        trending = [c.get("symbol","") for c in sentiment.get("trending_coins", [])]
        print(f"  Fear & Greed: {fng.get('value','?')}/100 — {fng.get('label','?')}")
        print(f"  News: {news.get('overall','?')} | BTC Dominance: {dominance.get('btc_dominance','?')}%")
        print(f"  Trending: {', '.join(trending[:5])}")
    except Exception as e:
        print(f"  Sentiment fetch failed: {e}")
        sentiment = {}

    # Step 2 — Market data
    print(f"\n{Fore.CYAN}[2/4] Fetching market data...{Style.RESET_ALL}")
    market_data_list = market_analyzer.analyze_all_pairs()
    current_prices = {d["symbol"]: d["price"] for d in market_data_list if "price" in d}

    # Step 3 — Stop loss / take profit
    print(f"\n{Fore.CYAN}[3/4] Checking stop-loss / take-profit...{Style.RESET_ALL}")
    trader.check_and_execute_stops(current_prices)

    # Step 4 — Claude decisions
    print(f"\n{Fore.CYAN}[4/4] Getting Claude decisions...{Style.RESET_ALL}")
    decisions = claude_brain.get_decisions_for_all(market_data_list, sentiment)

    any_trade = False
    for decision in decisions:
        executed = trader.execute_decision(decision)
        if executed:
            any_trade = True

    if not any_trade:
        print(f"\n  {Fore.YELLOW}No trades this scan — waiting for better setups{Style.RESET_ALL}")

    # Final positions
    positions = risk_manager.get_open_positions()
    print(f"\n  Open Positions: {len(positions)}")
    for symbol, pos in positions.items():
        current = current_prices.get(symbol, pos["entry_price"])
        pnl = (current - pos["entry_price"]) * pos["quantity"]
        print(f"  {symbol}: entry=${pos['entry_price']} | now=${current} | P&L=${pnl:+.4f}")

    print(f"\n{'=' * 60}")
    print(f"  Scan complete. Next run in ~30 minutes.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
