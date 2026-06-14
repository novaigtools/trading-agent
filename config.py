from dotenv import load_dotenv
import os

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
WEEKLY_BUDGET = float(os.getenv("WEEKLY_BUDGET", "100"))
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))

GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")

TRADING_PAIRS = [
    # Tier 1 — High volume mid-caps (best liquidity + volatility)
    "SOLUSDT",    # $198M daily vol — ecosystem leader, reliable bounces
    "NEARUSDT",   # $158M daily vol — consistent RSI bounce plays
    "SUIUSDT",    # $97M daily vol  — fast-growing, high volatility
    "DOGEUSDT",   # $69M daily vol  — highest-volume meme, liquid

    # Tier 2 — AI narrative coins (strong theme, real moves)
    "TAOUSDT",    # $103M daily vol — AI/ML leader, decouples from BTC on AI news
    "WLDUSDT",    # $150M daily vol — Worldcoin (Sam Altman), AI identity narrative
    "FETUSDT",    # $25M daily vol  — AI agents narrative
    "RENDERUSDT", # $19M daily vol  — GPU/AI rendering, volatile

    # Tier 3 — Solid mid-caps with volume
    "INJUSDT",    # $25M daily vol  — DeFi/derivatives
    "AVAXUSDT",   # $21M daily vol  — reliable alt
]
LONG_TERM_PAIRS = []  # No slow large-caps — all positions are swing/intraday

# Tier 5 — Penny/meme coins (18% of weekly budget split across max 2 positions)
PENNY_PAIRS = [
    "PEPEUSDT",   # $20M daily vol  — highest-volume pure meme
    "WIFUSDT",    # $1.3M daily vol  — dogwifhat, SOL meme, 10-30% daily swings
    "FLOKIUSDT",  # $1.2M daily vol  — classic meme coin
]

MAX_POSITION_PCT      = 0.15   # 15% of budget = $75 per standard position
PENNY_MAX_PCT         = 0.09   # 9% per penny position — 2 positions = 18% of budget
STOP_LOSS_PCT         = 0.02   # 2% stop loss (standard coins)
TAKE_PROFIT_PCT       = 0.06   # 6% take profit (standard coins)
PENNY_STOP_LOSS_PCT   = 0.03   # 3% SL for memes — wider to avoid noise whipsaws
PENNY_TAKE_PROFIT_PCT = 0.09   # 9% TP for memes — aim for bigger explosive moves
MAX_PENNY_POSITIONS   = 2      # Max 2 penny positions open at once = 18% exposure

BINANCE_BASE_URL = "https://api.binance.com"
