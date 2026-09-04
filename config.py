from dotenv import load_dotenv
import os

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "500"))
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
LIQUID_UNIVERSE_SIZE    = 100        # how many top-volume coins to watch
UNIVERSE_MIN_VOLUME_USD = 1_000_000  # floor so the tail is still liquid (~$1M/day)
SCAN_MAX_WORKERS        = 8          # parallel market-data fetch threads (rate-limit safe)

MAX_POSITION_PCT      = 0.15   # 15% of account equity per standard position
PENNY_MAX_PCT         = 0.09   # 9% per penny position — 2 positions = 18% max meme exposure
STOP_LOSS_PCT         = 0.02   # 2% stop loss (standard coins)
TAKE_PROFIT_PCT       = 0.06   # 6% take profit (standard coins)
PENNY_STOP_LOSS_PCT   = 0.03   # 3% SL for memes — wider to avoid noise whipsaws
PENNY_TAKE_PROFIT_PCT = 0.09   # 9% TP for memes — aim for bigger explosive moves
# Concurrent-position caps. Raised 2026-09-04: with a 100-coin field there are more
# genuine setups at once, so let more capital work — but the daily circuit breaker (5%),
# trailing stops and BEAR-regime block cap the correlated-drawdown risk that a bigger
# book creates. Quality bar per position is unchanged (still 8/10).
MAX_PENNY_POSITIONS   = 4      # riskier universe/meme names — was 2
MAX_OPEN_POSITIONS    = 6      # hard cap across all tiers — was 4
HOLD_ALL_AT_POSITIONS = 5      # stop opening new positions at 5 open — was 3

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
COOLDOWN_HOURS_AFTER_SL = int(os.getenv("COOLDOWN_HOURS_AFTER_SL", "12"))

# Daily circuit breaker: if equity falls this fraction below the day's opening equity,
# open no new positions for the rest of the UTC day (existing positions still managed).
DAILY_LOSS_LIMIT_PCT    = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.05"))

# Conviction-scaled sizing: full size for top-conviction setups, reduced below that.
CONVICTION_FULL_SCORE   = 10     # score at/above this gets full tier size
REDUCED_SIZE_FACTOR     = 0.7    # scores below CONVICTION_FULL_SCORE get 70% size

# Momentum "runner" take-profit: momentum-override trades were the edge (73% win) and
# can run 10-30%. Now that a trailing stop protects the downside, give them a wider
# target so the trailing stop — not a tight 6% TP — decides when a runner ends.
MOMENTUM_TP_MULTIPLIER  = 2.0    # momentum trades get 2x the normal take-profit

NEVER_TRADE = ("BTCUSDT", "ETHUSDT")  # Too slow — used as capital, not traded

BINANCE_BASE_URL = "https://api.binance.com"
