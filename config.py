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

    # Tier 4 — Established large-cap alts (XRP/ADA style — deep liquidity, slower but steady)
    "XRPUSDT",    # payments, top-5 by market cap, still swings 5-15% on news
    "ADAUSDT",    # long-cycle performer, liquid
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

MAX_POSITION_PCT      = 0.15   # 15% of account equity per standard position
PENNY_MAX_PCT         = 0.09   # 9% per penny position — 2 positions = 18% max meme exposure
STOP_LOSS_PCT         = 0.02   # 2% stop loss (standard coins)
TAKE_PROFIT_PCT       = 0.06   # 6% take profit (standard coins)
PENNY_STOP_LOSS_PCT   = 0.03   # 3% SL for memes — wider to avoid noise whipsaws
PENNY_TAKE_PROFIT_PCT = 0.09   # 9% TP for memes — aim for bigger explosive moves
MAX_PENNY_POSITIONS   = 2      # Max 2 penny positions open at once
MAX_OPEN_POSITIONS    = 4      # Hard cap across all tiers
HOLD_ALL_AT_POSITIONS = 3      # At 3+ open positions, HOLD everything until one closes

NEVER_TRADE = ("BTCUSDT", "ETHUSDT")  # Too slow — used as capital, not traded

BINANCE_BASE_URL = "https://api.binance.com"
