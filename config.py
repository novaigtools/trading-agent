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
    "TAOUSDT",    # $37M daily vol  — AI/ML leader, 5-15% swings common
    "FETUSDT",    # $25M daily vol  — AI agents narrative
    "RENDERUSDT", # $19M daily vol  — GPU/AI rendering, volatile

    # Tier 3 — Solid mid-caps with volume
    "INJUSDT",    # $25M daily vol  — DeFi/derivatives
    "AVAXUSDT",   # $21M daily vol  — reliable alt

    # Tier 4 — Best meme play
    "PEPEUSDT",   # $20M daily vol  — highest-volume pure meme
]
LONG_TERM_PAIRS = []  # No slow large-caps — all positions are swing/intraday

MAX_POSITION_PCT = 0.15   # 15% of budget = $75 per position max
STOP_LOSS_PCT    = 0.02   # 2% stop loss
TAKE_PROFIT_PCT  = 0.06   # raised from 4% → 6% to let winners run longer

BINANCE_BASE_URL = "https://api.binance.com"
