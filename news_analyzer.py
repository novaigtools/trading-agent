import requests
from datetime import datetime


def get_fear_and_greed() -> dict:
    """Fetch the Crypto Fear & Greed Index from alternative.me (free, no key needed)"""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=3", timeout=10)
        data = r.json()["data"]
        current = data[0]
        yesterday = data[1]
        return {
            "value": int(current["value"]),
            "label": current["value_classification"],
            "yesterday": int(yesterday["value"]),
            "yesterday_label": yesterday["value_classification"],
            "trend": "improving" if int(current["value"]) > int(yesterday["value"]) else "worsening",
        }
    except Exception as e:
        return {"error": str(e)}


def get_crypto_news(limit: int = 10) -> list[dict]:
    """Fetch latest crypto news from CryptoCompare (free, no key needed)"""
    try:
        r = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest",
            timeout=10
        )
        articles = r.json().get("Data", [])[:limit]
        return [
            {
                "title": a["title"],
                "source": a["source"],
                "published": datetime.utcfromtimestamp(a["published_on"]).strftime("%H:%M UTC"),
                "tags": a.get("categories", ""),
                "sentiment": _score_headline(a["title"]),
            }
            for a in articles
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_trending_coins() -> list[dict]:
    """Fetch trending coins from CoinGecko (free, no key needed)"""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/search/trending",
            timeout=10
        )
        coins = r.json().get("coins", [])[:7]
        return [
            {
                "name": c["item"]["name"],
                "symbol": c["item"]["symbol"].upper(),
                "market_cap_rank": c["item"].get("market_cap_rank", "?"),
                "price_btc": c["item"].get("price_btc", 0),
            }
            for c in coins
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_btc_dominance() -> dict:
    """Fetch BTC dominance from CoinGecko (free)"""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10
        )
        data = r.json()["data"]
        return {
            "btc_dominance": round(data["market_cap_percentage"]["btc"], 2),
            "eth_dominance": round(data["market_cap_percentage"]["eth"], 2),
            "total_market_cap_usd": round(data["total_market_cap"]["usd"], 0),
            "market_cap_change_24h": round(data["market_cap_change_percentage_24h_usd"], 2),
        }
    except Exception as e:
        return {"error": str(e)}


def _score_headline(title: str) -> str:
    """Simple keyword-based sentiment scoring"""
    title_lower = title.lower()
    bullish_words = ["surge", "rally", "bull", "breakout", "all-time high", "ath",
                     "gain", "rise", "pump", "moon", "adoption", "launch", "partnership",
                     "record", "growth", "upgrade", "buy", "accumulate", "positive"]
    bearish_words = ["crash", "dump", "bear", "drop", "fall", "sell", "hack", "ban",
                     "regulation", "lawsuit", "fear", "panic", "decline", "loss",
                     "warning", "risk", "scam", "fraud", "collapse", "plunge"]

    bull_score = sum(1 for w in bullish_words if w in title_lower)
    bear_score = sum(1 for w in bearish_words if w in title_lower)

    if bull_score > bear_score:
        return "BULLISH"
    elif bear_score > bull_score:
        return "BEARISH"
    return "NEUTRAL"


def get_full_sentiment_report() -> dict:
    """Aggregate all sentiment data into one report for Claude"""
    print("  Fetching Fear & Greed Index...")
    fng = get_fear_and_greed()

    print("  Fetching latest crypto news...")
    news = get_crypto_news(10)

    print("  Fetching trending coins...")
    trending = get_trending_coins()

    print("  Fetching market dominance...")
    dominance = get_btc_dominance()

    # Count news sentiment
    bull_count = sum(1 for n in news if n.get("sentiment") == "BULLISH")
    bear_count = sum(1 for n in news if n.get("sentiment") == "BEARISH")
    neutral_count = sum(1 for n in news if n.get("sentiment") == "NEUTRAL")

    overall_news_sentiment = "BULLISH" if bull_count > bear_count else ("BEARISH" if bear_count > bull_count else "NEUTRAL")

    return {
        "fear_and_greed": fng,
        "news_sentiment_summary": {
            "overall": overall_news_sentiment,
            "bullish_headlines": bull_count,
            "bearish_headlines": bear_count,
            "neutral_headlines": neutral_count,
        },
        "top_headlines": news[:5],
        "trending_coins": trending,
        "market_dominance": dominance,
    }
