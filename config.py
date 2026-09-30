from dotenv import load_dotenv
import os

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "500"))

# Weekly top-up: Amal adds $500 of paper money every week. Deposits are tracked separately
# (total_deposited) so P&L = equity - money put in, and a deposit never looks like profit.
# First top-up lands on DEPOSIT_SCHEDULE_START (a Monday), then every 7 days after. Missed
# weeks (laptop off) are caught up on the next scan, never double-applied.
WEEKLY_DEPOSIT_USD     = float(os.getenv("WEEKLY_DEPOSIT_USD", "500"))
DEPOSIT_SCHEDULE_START = os.getenv("DEPOSIT_SCHEDULE_START", "2026-10-05")
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))

# --- Decision engine ---------------------------------------------------------
# rules  = local_brain only. Zero network, zero LLM, zero cost. Always works.
# cli    = Claude Code CLI (subscription-billed), falls back to rules on any failure.
# hybrid = rules score everything; only candidates >= HYBRID_CANDIDATE_SCORE go to the
#          CLI for a second opinion, capped at MAX_LLM_CALLS_PER_SCAN. DEFAULT.
# api    = legacy paid Anthropic API. Never the default — it drained the credit balance.
BRAIN_MODE            = os.getenv("BRAIN_MODE", "hybrid").lower()
MAX_LLM_CALLS_PER_SCAN = int(os.getenv("MAX_LLM_CALLS_PER_SCAN", "3"))
HYBRID_CANDIDATE_SCORE = int(os.getenv("HYBRID_CANDIDATE_SCORE", "7"))
CLAUDE_CLI_PATH       = os.getenv("CLAUDE_CLI_PATH", "claude")  # absolute path if not on PATH
CLAUDE_CLI_TIMEOUT    = int(os.getenv("CLAUDE_CLI_TIMEOUT", "60"))

# The single source of truth for the buy bar. The prompt, the rule engine and the
# executor all read THIS — previously the prompt said 8 and trader.py enforced 7.
MIN_BUY_CONFIDENCE = int(os.getenv("MIN_BUY_CONFIDENCE", "8"))

GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")

TRADING_PAIRS = [
    # Tier 1 — High volume mid-caps (best liquidity + volatility)
    "SOLUSDT",    # ecosystem leader, reliable bounces
    "NEARUSDT",   # consistent RSI bounce plays
    "SUIUSDT",    # fast-growing, high volatility
    "DOGEUSDT",   # highest-volume meme, liquid

    # Tier 2 — AI narrative coins (strong theme, real moves)
    "TAOUSDT",    # AI/ML leader, decouples from BTC on AI news
    "WLDUSDT",    # Worldcoin (Sam Altman), AI identity narrative
    "FETUSDT",    # AI agents narrative
    "RENDERUSDT", # GPU/AI rendering, volatile

    # Tier 3 — Solid mid-caps with volume
    "INJUSDT",    # DeFi/derivatives
    "AVAXUSDT",   # reliable alt
    "LINKUSDT",   # oracle blue-chip, reliable mover
    "UNIUSDT",    # DeFi blue-chip (won +10% as a trending pick — promoted to permanent)
    "APTUSDT",    # volatile L1
    "ARBUSDT",    # L2 leader, volatile

    # Tier 4 — Established large-cap alts (XRP/ADA style — deep liquidity, slower but steady)
    "XRPUSDT",    # payments, top-5 by market cap, still swings 5-15% on news
    "ADAUSDT",    # long-cycle performer, liquid

    # Tier 4b — Hot-narrative mid-caps (added 2026-08-31 to widen shot count)
    "ENAUSDT",    # Ethena — yield narrative, high volatility
    "ONDOUSDT",   # RWA (real-world assets) narrative, hot sector
]
LONG_TERM_PAIRS = []  # No slow large-caps — all positions are swing/intraday

# Tier 5 — Penny/meme coins (capped exposure)
PENNY_PAIRS = [
    "PEPEUSDT",   # highest-volume pure meme
    "WIFUSDT",    # dogwifhat, SOL meme, 10-30% daily swings
    "FLOKIUSDT",  # classic meme coin
    "BONKUSDT",   # Solana meme, high volume
    "TRUMPUSDT",  # political meme, liquid
    "PENGUUSDT",  # Pudgy Penguins meme
]

# Tier 6 — Dynamic trending coins.
# Each scan the bot pulls CoinGecko's trending list and auto-includes any coin
# that has a liquid Binance USDT spot pair. These rotate daily and are the
# highest-risk names — they get penny-tier sizing and stops.
INCLUDE_TRENDING        = True
MAX_TRENDING_COINS      = 3          # max trending coins added per scan
MIN_TRENDING_VOLUME_USD = 2_000_000  # skip illiquid junk (< $2M daily volume)

# Tier 7 — Dynamic liquid universe. Each scan the bot pulls the top-N Binance USDT
# spot pairs by 24h volume (stablecoins/wrapped/fiat excluded) so it watches ~100
# genuinely liquid coins without hand-maintaining the list. Universe-only coins (those
# not in the curated tiers) are treated as penny-tier: small size, wide stops — cautious,
# since they are less battle-tested than the core names. Fetching is parallelized so a
# big list still scans in well under the staleness limit.
INCLUDE_LIQUID_UNIVERSE = True
# Tightened 2026-09-18: the $1M floor / 100-coin tail let in junk (a non-ASCII symbol,
# MARSCOIN, KAVA) that produced most of the era's losses. The ~50 coins clearing $5M/day
# are the genuinely liquid ones — quality over breadth.
LIQUID_UNIVERSE_SIZE    = 50         # top-volume coins to watch (was 100)
UNIVERSE_MIN_VOLUME_USD = 5_000_000  # $5M/day floor (was $1M) — cuts the junk tail
SCAN_MAX_WORKERS        = 8          # parallel market-data fetch threads (rate-limit safe)

# AGGRESSIVE sizing (2026-09-11, user opted in with eyes open): bigger bets per trade
# so more of the account works and wins hit harder. Losses are still capped by the same
# tight stops (2%/3%) and the daily circuit breaker — bigger size, seatbelts on.
# --- Full-capital, risk-based sizing (2026-09-30) ----------------------------------
# Amal wants the whole weekly budget working. Old sizing was a flat 15%/9% per trade, so a
# full 4-position book used ~60% at most (~40% after conviction scaling) and a quiet market
# left most of the money idle. Now each trade RISKS a fixed slice of equity:
#     notional = RISK_PER_TRADE_PCT * equity / stop_distance, capped below.
# A calm coin with a tight ATR stop gets a big position; a twitchy one a small one; the
# dollar loss if any stop hits stays ~1.5% of the account. Caps let 4-5 positions reach
# ~100% deployment without any single name dominating.
RISK_PER_TRADE_PCT    = 0.015  # max 1.5% of equity lost if a trade's stop is hit
MAX_POSITION_PCT      = 0.30   # cap per standard position (was a flat 15%)
PENNY_MAX_PCT         = 0.15   # cap per small-cap/penny position (was a flat 9%)
# --- Volatility-adjusted stops (2026-09-21) -----------------------------------
# Autopsy: since Sep 1 the book was -$18.99, and trades stopped out inside 60 min were
# -$18.97 of it — i.e. ALL of the loss was fast churn (11 of 13 were stop-losses), while
# everything held >1h was flat-to-positive. Cause: a fixed 2%/3% stop sits inside a
# volatile coin's normal range, so noise trips it before the setup can work.
# Fix: stop = ATR(14) x multiplier, clamped, with take-profit at a fixed R:R of that
# distance. Calm coins keep tight stops; twitchy coins get the room they need.
USE_ATR_STOPS         = os.getenv("USE_ATR_STOPS", "true").lower() == "true"
ATR_STOP_MULT         = 1.6    # stop this many ATRs below entry
MIN_STOP_PCT          = 0.02   # never tighter than 2% (caps churn)
MAX_STOP_PCT          = 0.06   # never wider than 6% (caps loss per trade)
STOP_TP_RATIO         = 3.0    # take-profit at 3x the risk — keeps the 2.5:1+ asymmetry
# If a coin is so volatile that even MAX_STOP_PCT sits inside its normal hourly range,
# no stop can be placed sensibly within our risk budget — so don't take the trade.
# GUSDT (13% hourly ATR, stopped out in 65 seconds) is the case this exists for.
SKIP_IF_UNSTOPPABLE   = True

STOP_LOSS_PCT         = 0.02   # fallback fixed stop when ATR is unavailable
TAKE_PROFIT_PCT       = 0.06   # 6% take profit (standard coins)
PENNY_STOP_LOSS_PCT   = 0.03   # 3% SL for memes — wider to avoid noise whipsaws
PENNY_TAKE_PROFIT_PCT = 0.09   # 9% TP for memes — aim for bigger explosive moves
# Concurrent-position caps. Raised 2026-09-04: with a 100-coin field there are more
# genuine setups at once, so let more capital work — but the daily circuit breaker (5%),
# trailing stops and BEAR-regime block cap the correlated-drawdown risk that a bigger
# book creates. Quality bar per position is unchanged (still 8/10).
MAX_PENNY_POSITIONS   = 3      # moderate — 6/5/4 caps drove over-trading (50 trades in 2.5 wks)
MAX_OPEN_POSITIONS    = 5      # hard cap across all tiers
HOLD_ALL_AT_POSITIONS = 5      # 5 slots x ~20-30% each lets the book reach full deployment

# "Don't chase the blow-off top" guard (research: buying after a coin has already
# exploded is where momentum bots bleed). Refuse fresh entries that are both far
# extended on the day AND already overbought — we want to buy strength early, not late.
OVEREXTENDED_24H_PCT  = 30.0   # 24h change at/above this is "already extended"
OVEREXTENDED_RSI_1H   = 78.0   # 1H RSI at/above this is "already overbought"

# --- Adaptive risk controls (added 2026-08-23 from trade-history analysis) ---
# The autopsy of experiment 2 showed: winners exit in ~14h, losers dragged ~43h;
# the bot round-tripped winners back into losses and revenge-bought coins right
# after they stopped it out. These are the standard professional fixes.

# Trailing stop: once a position is up TRAIL_ACTIVATE_PCT, ratchet the stop up so it
# trails TRAIL_DISTANCE_PCT below the highest price seen. A winner can no longer round-
# trip all the way back to the original stop.
TRAIL_ENABLED           = os.getenv("TRAIL_ENABLED", "true").lower() == "true"
TRAIL_ACTIVATE_PCT      = 0.03   # start trailing once +3% in profit
TRAIL_DISTANCE_PCT      = 0.02   # standard coins: trail 2% below peak
PENNY_TRAIL_DISTANCE_PCT = 0.03  # penny coins: 3% (they're noisier)

# Stale exit: a position older than this that is NOT in profit is closed to free capital.
MAX_HOLD_HOURS          = int(os.getenv("MAX_HOLD_HOURS", "48"))

# Cooldown: after a stop-loss on a symbol, refuse to re-enter it for this long.
COOLDOWN_HOURS_AFTER_SL = int(os.getenv("COOLDOWN_HOURS_AFTER_SL", "24"))  # 24h (was 12) — SOPH re-entered & lost repeatedly

# Daily circuit breaker: if equity falls this fraction below the day's opening equity,
# open no new positions for the rest of the UTC day (existing positions still managed).
DAILY_LOSS_LIMIT_PCT    = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.05"))  # back to 5%

# Conviction-scaled sizing: full size for top-conviction setups, reduced below that.
CONVICTION_FULL_SCORE   = 10     # score at/above this gets full tier size
REDUCED_SIZE_FACTOR     = 0.7    # scores below CONVICTION_FULL_SCORE get 70% size

# Momentum "runner" take-profit: momentum-override trades were the edge (73% win) and
# can run 10-30%. Now that a trailing stop protects the downside, give them a wider
# target so the trailing stop — not a tight 6% TP — decides when a runner ends.
MOMENTUM_TP_MULTIPLIER  = 2.0    # momentum trades get 2x the normal take-profit

NEVER_TRADE = ("BTCUSDT", "ETHUSDT")  # Too slow — used as capital, not traded

BINANCE_BASE_URL = "https://api.binance.com"
