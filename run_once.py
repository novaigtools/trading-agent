"""
Single-scan version of the trading bot — runs one full scan, saves state, exits.
Called every 30 min by Windows Task Scheduler (and manually via GitHub Actions).
"""
import os
import sys
import time
from datetime import datetime
from colorama import Fore, Style, init
import market_analyzer
import claude_brain
import trader
import risk_manager
import news_analyzer
from config import (
    PAPER_TRADING, STARTING_BALANCE, TRADING_PAIRS, PENNY_PAIRS,
    INCLUDE_TRENDING, MAX_TRENDING_COINS, MIN_TRENDING_VOLUME_USD,
)

init(autoreset=True)

# If the laptop sleeps mid-scan, the process resumes hours later holding
# stale market data. Never act on data older than these limits.
MAX_FETCH_AGE_MIN = 10   # abort scan if data fetch phase took longer than this
MAX_SCAN_AGE_MIN  = 20   # skip trade execution if whole scan took longer than this

# Wall clock, not monotonic: sleep/hibernate time must count as staleness.
_SCAN_START = time.time()


def _elapsed_min() -> float:
    return (time.time() - _SCAN_START) / 60


def main():
    print(f"\n{'=' * 60}")
    print(f"  CRYPTO TRADING BOT — Scheduled Scan")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Mode: {'PAPER' if PAPER_TRADING else 'LIVE'} | Account: ${STARTING_BALANCE}")
    print(f"{'=' * 60}\n")

    # Account summary
    summary = risk_manager.account_summary()
    print(f"  Equity: ${summary['equity']} | Cash: ${summary['cash']} | "
          f"P&L since {summary['experiment_start']}: ${summary['total_pnl']:+.2f} ({summary['total_pnl_pct']:+.2f}%)")
    print(f"  Open Positions: {summary['open_positions']}\n")

    # Step 1 — Sentiment
    print(f"{Fore.CYAN}[1/6] Fetching sentiment & news...{Style.RESET_ALL}")
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

    # Step 2 — Live trending coins (Binance-tradeable only)
    trending_pairs = []
    if INCLUDE_TRENDING:
        print(f"\n{Fore.CYAN}[2/6] Scanning live trending coins...{Style.RESET_ALL}")
        try:
            raw_trending = news_analyzer.get_tradeable_trending(
                MAX_TRENDING_COINS, MIN_TRENDING_VOLUME_USD)
            # Coins already in our static tiers keep their own tier — trending
            # tier is only for genuinely new names not otherwise tracked.
            known = set(TRADING_PAIRS + PENNY_PAIRS)
            trending_pairs = [p for p in raw_trending if p not in known]
            print(f"  Trending & tradeable this scan: "
                  f"{', '.join(trending_pairs) if trending_pairs else 'none new passed the liquidity filter'}")
        except Exception as e:
            print(f"  Trending scan failed: {e}")
    risk_manager.set_trending(trending_pairs)

    # Step 3 — Market regime
    print(f"\n{Fore.CYAN}[3/6] Checking BTC market regime...{Style.RESET_ALL}")
    regime = market_analyzer.get_btc_market_regime()
    regime_str = regime.get("regime", "UNKNOWN")
    regime_color = Fore.GREEN if regime_str == "BULL" else (Fore.RED if regime_str == "BEAR" else Fore.YELLOW)
    print(f"  Regime: {regime_color}{regime_str}{Style.RESET_ALL} "
          f"({regime.get('bull_signals',0)} bull / {regime.get('bear_signals',0)} bear signals)")
    print(f"  BTC: ${regime.get('price','?')} | EMA20(4H): ${regime.get('ema20_4h','?')} | EMA50(4H): ${regime.get('ema50_4h','?')}")
    print(f"  Structure: {regime.get('ema_structure','?')} | RSI(4H): {regime.get('rsi_4h','?')}")

    # Step 4 — Market data (static tiers + this scan's trending picks)
    print(f"\n{Fore.CYAN}[4/6] Fetching market data...{Style.RESET_ALL}")
    market_data_list = market_analyzer.analyze_all_pairs(extra_pairs=trending_pairs)
    current_prices = {d["symbol"]: d["price"] for d in market_data_list if "price" in d}

    # Staleness guard: if the laptop slept during the fetch phase, the prices
    # above are hours old — acting on them would trade at phantom prices.
    if _elapsed_min() > MAX_FETCH_AGE_MIN:
        print(f"\n{Fore.RED}ABORTING SCAN: data fetch took {_elapsed_min():.0f} min "
              f"(laptop slept mid-scan?). Prices are stale — no action taken. "
              f"Next scheduled scan will start fresh.{Style.RESET_ALL}")
        return

    # Step 5 — Stop loss / take profit
    print(f"\n{Fore.CYAN}[5/6] Checking stop-loss / take-profit...{Style.RESET_ALL}")
    trader.check_and_execute_stops(current_prices)

    # Step 6 — Claude decisions (hard block on BEAR)
    print(f"\n{Fore.CYAN}[6/6] Getting Claude decisions...{Style.RESET_ALL}")
    if regime_str == "BEAR":
        print(f"  {Fore.RED}MARKET REGIME: BEAR — skipping new trades to protect capital{Style.RESET_ALL}")
        decisions = []
    else:
        decisions = claude_brain.get_decisions_for_all(
            market_data_list, sentiment, regime, active_trending=set(trending_pairs))

    # Second staleness checkpoint: Claude consultations can also straddle a sleep.
    if _elapsed_min() > MAX_SCAN_AGE_MIN and decisions:
        print(f"\n{Fore.RED}SKIPPING TRADE EXECUTION: scan has been running "
              f"{_elapsed_min():.0f} min — decisions are based on stale data. "
              f"Next scheduled scan will start fresh.{Style.RESET_ALL}")
        decisions = []

    any_trade = False
    for decision in decisions:
        executed = trader.execute_decision(decision)
        if executed:
            any_trade = True

    if not any_trade:
        print(f"\n  {Fore.YELLOW}No trades this scan — waiting for better setups{Style.RESET_ALL}")

    # Final positions + account snapshot (mark-to-market)
    positions = risk_manager.get_open_positions()
    print(f"\n  Open Positions: {len(positions)}")
    for symbol, pos in positions.items():
        current = current_prices.get(symbol, pos["entry_price"])
        pnl = (current - pos["entry_price"]) * pos["quantity"]
        print(f"  {symbol}: entry=${pos['entry_price']} | now=${current} | P&L=${pnl:+.4f}")

    summary = risk_manager.account_summary(current_prices)
    print(f"\n  ACCOUNT: equity=${summary['equity']} | cash=${summary['cash']} | "
          f"total P&L=${summary['total_pnl']:+.2f} ({summary['total_pnl_pct']:+.2f}%)")

    print(f"\n{'=' * 60}")
    print(f"  Scan complete. Regime: {regime_str}. Next run in ~30 minutes.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
