import json
import anthropic
from config import CLAUDE_API_KEY

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


SYSTEM_PROMPT = """You are an elite crypto trader with 20 years of experience, specialising in high-volatility altcoins and meme coins.
You are aggressive but disciplined — you hunt for asymmetric opportunities in small and mid-cap coins where price moves of 5-20% can happen within hours.

You have access to BOTH technical indicators AND live market sentiment (news, Fear & Greed, trending coins, BTC dominance).
Use all signals together for the highest-conviction decisions.

TREND FILTER — CHECK THIS FIRST BEFORE ANY BUY:
- NEVER buy if BTC 1H EMA20 is below EMA50 AND price is below EMA20. That is a downtrend. Wait.
- NEVER buy if BTC has made lower lows for 3+ consecutive 1H candles. Wait for stabilisation.
- ONLY buy when BTC shows at least ONE of: EMA20 > EMA50, or price reclaiming EMA20, or bullish MACD crossover
- If BTC trend is down, HOLD cash. Missing a trade is better than a stop-loss.

SENTIMENT RULES:
- Fear & Greed < 25 (Extreme Fear) = NOT automatically a buy. Wait for price CONFIRMATION first (BTC stabilising, green candle, volume increasing). Extreme Fear in a downtrend = falling knife.
- Fear & Greed 25-40 (Fear) = cautious only. Require strong technical confirmation + BTC stable/rising.
- Fear & Greed 40-60 = neutral, rely on technicals
- Fear & Greed > 60 = market recovering, more aggressive entries allowed
- Fear & Greed > 75 (Extreme Greed) = tighten stops, no new entries
- Bearish news = HOLD, do not buy
- BTC dominance rising = altcoins weakening, reduce entries or skip alts entirely
- BTC dominance falling = altcoin season, be aggressive on alts
- Coin trending on CoinGecko = extra momentum signal, but only if trend filter passes

COIN TIERS (ranked by expected return potential):
- TIER 1 — SOL, NEAR, SUI, DOGE: highest volume, most reliable setups, core positions
- TIER 2 — TAO, FET, RENDER: AI narrative coins, 5-15% moves common, prioritise on dips
- TIER 3 — INJ, AVAX: solid mid-caps, secondary picks when tier 1/2 not set up
- TIER 4 — PEPE: meme play, only enter on extreme oversold + volume spike

TECHNICAL RULES (altcoins):
- DOGE and PEPE move in explosive bursts — catch early momentum, volume spike 2x avg = strong signal
- SOL, NEAR, SUI amplify BTC moves 2-5x — best risk/reward in the universe
- TAO, FET, RENDER follow AI narrative — buy any significant dip when AI news is positive
- Volume is KING — a volume spike 2x above average on any coin is a major entry signal
- RSI below 30 on 1H = high priority entry for ALL coins in our list
- RSI below 25 on 1H = EXTREME priority, maximum allowed position size
- Breakouts above Bollinger Band upper = strong buy signal for volatile coins
- EMA 20 crossing above EMA 50 = trend change, high priority BUY
- Do NOT trade BTC or ETH — too slow, not worth the capital

RISK/REWARD RULES:
- Minimum 2.5:1 reward-to-risk ratio for all trades
- For meme coins (DOGE, PEPE): 1.5% stop-loss, 5% take-profit
- For AI coins (TAO, FET, RENDER): 2% stop-loss, 6% take-profit
- For mid-caps (SOL, NEAR, SUI, INJ, AVAX): 2% stop-loss, 6% take-profit
- DO NOT widen TP just because of Extreme Fear — that caused losses. Only widen TP if BTC trend is UP.
- Max 4 open positions at once — less exposure, more patience
- Confidence must be 8+ to open a new position. 7 is not enough in current market conditions.
- If you already have 2+ losing positions open, return HOLD on all new setups until market shows direction.

You must respond ONLY with valid JSON in this exact format:
{
  "symbol": "BTCUSDT",
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 1-10,
  "reasoning": "brief explanation under 150 words covering both technicals and sentiment",
  "entry_price": 12345.67,
  "stop_loss": 12100.00,
  "take_profit": 12800.00,
  "trade_type": "intraday" | "swing"
}

If action is HOLD, set entry_price, stop_loss, take_profit to null.
Only recommend BUY when confidence is 8 or above. 7 is not enough — be patient."""


def get_trading_decision(market_data: dict, sentiment: dict = None, regime: dict = None) -> dict:
    sym = market_data['symbol']
    if sym in ("BTCUSDT", "ETHUSDT"):
        coin_type = "LARGE CAP — treat as swing trade, be conservative"
    elif sym in ("DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "FLOKIUSDT"):
        coin_type = "MEME COIN — high volatility, hunt momentum and volume breakouts aggressively"
    else:
        coin_type = "MID-CAP ALTCOIN — high volatility, amplified BTC moves, look for momentum setups"

    # Check if this coin is trending
    trending_symbols = []
    if sentiment and "trending_coins" in sentiment:
        trending_symbols = [c.get("symbol", "") for c in sentiment.get("trending_coins", [])]
    is_trending = sym.replace("USDT", "") in trending_symbols
    trending_note = f"⭐ THIS COIN IS CURRENTLY TRENDING ON COINGECKO" if is_trending else ""

    # Build sentiment block
    sentiment_block = ""
    if sentiment:
        fng = sentiment.get("fear_and_greed", {})
        news_summary = sentiment.get("news_sentiment_summary", {})
        dominance = sentiment.get("market_dominance", {})
        headlines = sentiment.get("top_headlines", [])

        headline_text = "\n".join([
            f"  [{h.get('sentiment','?')}] {h.get('title','')}"
            for h in headlines[:5]
        ])

        sentiment_block = f"""
MARKET SENTIMENT:
- Fear & Greed Index: {fng.get('value', '?')}/100 — {fng.get('label', '?')} (yesterday: {fng.get('yesterday', '?')} — {fng.get('trend', '?')})
- News Sentiment: {news_summary.get('overall', '?')} ({news_summary.get('bullish_headlines', 0)} bullish, {news_summary.get('bearish_headlines', 0)} bearish, {news_summary.get('neutral_headlines', 0)} neutral)
- BTC Dominance: {dominance.get('btc_dominance', '?')}% | ETH: {dominance.get('eth_dominance', '?')}%
- Total Market Cap 24h Change: {dominance.get('market_cap_change_24h', '?')}%
- Trending Coins: {', '.join(trending_symbols) if trending_symbols else 'N/A'}

TOP HEADLINES:
{headline_text}
"""

    # Build regime block
    regime_block = ""
    if regime:
        r = regime.get("regime", "UNKNOWN")
        regime_block = f"""
BTC MARKET REGIME (4H — most important signal):
- Regime: {r} ({regime.get('bull_signals',0)} bull signals, {regime.get('bear_signals',0)} bear signals)
- BTC Price vs EMA20(4H): {'ABOVE ✅' if regime.get('above_ema20_4h') else 'BELOW ❌'}
- EMA Structure: {regime.get('ema_structure','?')}
- BTC 4H RSI: {regime.get('rsi_4h','?')}
- Consecutive lower lows: {regime.get('lower_lows','?')}
{'⚠ NEUTRAL REGIME: Require 8+ confidence and strong technical confirmation before buying.' if r == 'NEUTRAL' else ''}
{'✅ BULL REGIME: Trend is up. Look for pullback entries with confirmation.' if r == 'BULL' else ''}
"""

    prompt = f"""Analyze this crypto market data and give me your trading decision:

Coin Type: {coin_type}
{trending_note}
Symbol: {market_data['symbol']}
Current Price: ${market_data['price']}
24h Change: {market_data['change_24h']}%
24h High: ${market_data['high_24h']}
24h Low: ${market_data['low_24h']}
24h Volume: ${market_data['volume_24h']:,.0f}

15-Minute Chart Indicators:
- RSI(14): {market_data['indicators_15m']['rsi']}
- MACD: {market_data['indicators_15m']['macd']} | Signal: {market_data['indicators_15m']['macd_signal']} | Histogram: {market_data['indicators_15m']['macd_hist']}
- Bollinger Bands: Upper={market_data['indicators_15m']['bb_upper']} | Mid={market_data['indicators_15m']['bb_mid']} | Lower={market_data['indicators_15m']['bb_lower']}
- EMA 20: {market_data['indicators_15m']['ema_20']} | EMA 50: {market_data['indicators_15m']['ema_50']}
- Price change (last 5 candles): {market_data['indicators_15m']['price_change_5']}%
- Volume (latest vs avg): {market_data['indicators_15m']['volume_latest']} vs {market_data['indicators_15m']['volume_avg']}

1-Hour Chart Indicators:
- RSI(14): {market_data['indicators_1h']['rsi']}
- MACD Histogram: {market_data['indicators_1h']['macd_hist']}
- EMA 20: {market_data['indicators_1h']['ema_20']} | EMA 50: {market_data['indicators_1h']['ema_50']}
- Price change (last 20 candles): {market_data['indicators_1h']['price_change_20']}%
{regime_block}
{sentiment_block}
Respond with your JSON trading decision only."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def get_decisions_for_all(market_data_list: list[dict], sentiment: dict = None, regime: dict = None) -> list[dict]:
    decisions = []
    for market_data in market_data_list:
        if "error" in market_data:
            print(f"  Skipping {market_data['symbol']} — fetch error: {market_data['error']}")
            continue
        print(f"  Consulting Claude for {market_data['symbol']}...")
        try:
            decision = get_trading_decision(market_data, sentiment, regime)
            decision["market_price"] = market_data["price"]
            decisions.append(decision)
        except Exception as e:
            print(f"  Claude decision failed for {market_data['symbol']}: {e}")
    return decisions
