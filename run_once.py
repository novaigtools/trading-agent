"""
Single-scan version of the trading bot — runs one full scan, saves state, exits.
Called every 30 min by Windows Task Scheduler.

Exit codes (bot_task.ps1 logs these loudly):
  0 = scan completed (trades or not — both are healthy outcomes)
  1 = DECISION ENGINE DEAD: zero decisions succeeded, the bot is not trading
"""
import argparse
import sys
import time
from datetime import datetime, timezone

from colorama import Fore, Style, init

import market_analyzer
import brain
import trader
import risk_manager
import news_analyzer
import notifier
from config import (
    PAPER_TRADING, STARTING_BALANCE, TRADING_PAIRS, PENNY_PAIRS,
    INCLUDE_TRENDING, MAX_TRENDING_COINS, MIN_TRENDING_VOLUME_USD,
    BRAIN_MODE, MIN_BUY_CONFIDENCE,
)

init(autoreset=True)

# If the laptop sleeps mid-scan, the process resumes hours later holding stale market
# data. Never act on prices older than these limits.
MAX_FETCH_AGE_MIN = 10   # abort scan if the data-fetch phase took longer than this
MAX_SCAN_AGE_MIN  = 20   # skip trade execution if the whole scan took longer than this

# Wall clock, not monotonic: sleep/hibernate time must count as staleness.
_SCAN_START = time.time()


def _elapsed_min() -> float:
    return (time.time() - _SCAN_START) / 60


def main() -> int:
    ap = argparse.ArgumentParser(description="One trading scan.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute and print everything; write NOTHING (no state, no CSV, no email).")
    ap.add_argument("--brain", default=None, choices=["rules", "cli", "hybrid", "api"],
                    help="Override BRAIN_MODE for this run.")
    args = ap.parse_args()

    mode = (args.brain or BRAIN_MODE).lower()
    dry = args.dry_run

    print(f"\n{'=' * 64}")
    print(f"  CRYPTO TRADING BOT — Scheduled Scan{'  [DRY RUN — NOTHING WILL BE WRITTEN]' if dry else ''}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Mode: {'PAPER' if PAPER_TRADING else 'LIVE'} | Account: ${STARTING_BALANCE} | Brain: {mode}")
    print(f"{'=' * 64}\n")

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
        trending = [c.get("symbol", "") for c in sentiment.get("trending_coins", [])]
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
    print(f"  BTC: ${regime.get('price','?')} | EMA20(4H): ${regime.get('ema20_4h','?')} | "
          f"EMA50(4H): ${regime.get('ema50_4h','?')}")
    print(f"  Structure: {regime.get('ema_structure','?')} | RSI(4H): {regime.get('rsi_4h','?')}")

    # Step 4 — Market data
    print(f"\n{Fore.CYAN}[4/6] Fetching market data...{Style.RESET_ALL}")
    market_data_list = market_analyzer.analyze_all_pairs(extra_pairs=trending_pairs)
    current_prices = {d["symbol"]: d["price"] for d in market_data_list if "price" in d}

    if _elapsed_min() > MAX_FETCH_AGE_MIN:
        print(f"\n{Fore.RED}ABORTING SCAN: data fetch took {_elapsed_min():.0f} min "
              f"(laptop slept mid-scan?). Prices are stale — no action taken.{Style.RESET_ALL}")
        return 0

    # Step 5 — Stop loss / take profit
    print(f"\n{Fore.CYAN}[5/6] Checking stop-loss / take-profit...{Style.RESET_ALL}")
    if dry:
        triggers = risk_manager.check_stop_loss_take_profit(current_prices)
        print(f"  [dry-run] would fire {len(triggers)} SL/TP exit(s): "
              f"{[t['symbol'] + ':' + t['reason'] for t in triggers] or 'none'}")
    else:
        trader.check_and_execute_stops(current_prices)

    # Step 6 — Decisions
    print(f"\n{Fore.CYAN}[6/6] Getting decisions (brain: {mode})...{Style.RESET_ALL}")
    open_positions = risk_manager.get_open_positions()

    if regime_str == "BEAR":
        print(f"  {Fore.RED}MARKET REGIME: BEAR — new entries intentionally skipped{Style.RESET_ALL}")
        result = brain.BrainResult(mode=mode)
        bear_skip = True
    else:
        bear_skip = False
        result = brain.get_decisions_for_all(
            market_data_list, sentiment, regime,
            active_trending=set(trending_pairs),
            open_positions=open_positions,
            mode=mode,
        )

    # Second staleness checkpoint: LLM calls can also straddle a laptop sleep.
    if _elapsed_min() > MAX_SCAN_AGE_MIN and result.decisions:
        print(f"\n{Fore.RED}SKIPPING TRADE EXECUTION: scan has run {_elapsed_min():.0f} min — "
              f"decisions are based on stale data.{Style.RESET_ALL}")
        result.decisions = []

    # ---- Execute -----------------------------------------------------------
    any_trade = False
    for decision in result.decisions:
        if dry:
            act, sym, conf = decision["action"], decision["symbol"], decision["confidence"]
            if act == "BUY":
                print(f"  {Fore.GREEN}[dry-run] WOULD BUY {sym} @{conf}/10 — {decision['reasoning'][:110]}{Style.RESET_ALL}")
                any_trade = True
            else:
                print(f"  {sym}: {act} ({conf}/10) — {decision['reasoning'][:100]}")
        else:
            if trader.execute_decision(decision):
                any_trade = True

    # ---- Health verdict: these four states must be impossible to confuse ----
    print(f"\n{'-' * 64}")
    print(f"  BRAIN: mode={result.mode} | symbols evaluated={result.attempted} | "
          f"LLM calls={result.llm_calls} | failures={result.failed}")
    for note in result.disagreements:
        print(f"  HYBRID DISAGREEMENT: {note}")

    exit_code = 0

    if bear_skip:
        print(f"  {Fore.YELLOW}BEAR regime — new entries intentionally skipped.{Style.RESET_ALL}")

    elif result.is_dead:
        banner = (f"*** DECISION ENGINE DEAD: 0/{result.attempted} decisions succeeded — "
                  f"BOT IS NOT TRADING ***")
        print(f"  {Fore.RED}{banner}{Style.RESET_ALL}")
        print(f"  First error: {result.first_error}")
        exit_code = 1
        if not dry:
            notifier.send_alert_email(
                subject="🚨 Trading bot: DECISION ENGINE DEAD",
                body=(f"Every decision call failed this scan — the bot is NOT trading.\n\n"
                      f"Brain mode : {result.mode}\n"
                      f"Attempted  : {result.attempted}\n"
                      f"Failed     : {result.failed}\n"
                      f"First error: {result.first_error}\n\n"
                      f"The bot will keep retrying every 30 minutes. If the cause is an LLM "
                      f"outage, set BRAIN_MODE=rules in .env to trade on the local rule engine "
                      f"until it is resolved."),
                key="engine_dead",
            )

    elif result.is_degraded:
        print(f"  {Fore.YELLOW}*** DECISION ENGINE DEGRADED: {result.failed}/{result.attempted} "
              f"decision calls failed — first error: {result.first_error} ***{Style.RESET_ALL}")
        print(f"  (Fell back to the rule engine for the failed symbols — still trading.)")

    elif not any_trade:
        print(f"  No setups met the bar ({result.attempted} symbols evaluated, 0 failures, "
              f"need {MIN_BUY_CONFIDENCE}+ confidence).")

    # ---- Positions + account snapshot --------------------------------------
    positions = risk_manager.get_open_positions()
    print(f"\n  Open Positions: {len(positions)}")
    for symbol, pos in positions.items():
        current = current_prices.get(symbol, pos["entry_price"])
        pnl = (current - pos["entry_price"]) * pos["quantity"]
        print(f"  {symbol}: entry=${pos['entry_price']} | now=${current} | P&L=${pnl:+.4f}")

    summary = risk_manager.account_summary(current_prices)
    print(f"\n  ACCOUNT: equity=${summary['equity']} | cash=${summary['cash']} | "
          f"total P&L=${summary['total_pnl']:+.2f} ({summary['total_pnl_pct']:+.2f}%)")

    print(f"\n{'=' * 64}")
    print(f"  Scan complete. Regime: {regime_str}. Exit: {exit_code}."
          f"{'  [DRY RUN — nothing was written]' if dry else ''}")
    print(f"{'=' * 64}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
