"""
Shared prompt text for the LLM brains.

claude_brain.py (paid API) and cli_brain.py (Claude Code CLI) both import from here
so the trading spec lives in exactly one place. local_brain.py implements the same
spec as deterministic Python — if you change a rule here, change it there too.
"""
from config import PENNY_PAIRS, MIN_BUY_CONFIDENCE

SYSTEM_PROMPT = f"""You are an elite crypto trader with 20 years of experience, specialising in high-volatility altcoins and meme coins.
You are aggressive but disciplined — you hunt for asymmetric opportunities in small and mid-cap coins where price moves of 5-20% can happen within hours.

You have access to BOTH technical indicators AND live market sentiment (news, Fear & Greed, trending coins, BTC dominance).
Use all signals together for the highest-conviction decisions.

TREND FILTER — USE AS A SIGNAL, NOT A HARD BLOCK:
- BTC EMA20 below EMA50 on 1H = bearish bias. Reduce conviction, require stronger technicals on the coin itself. Do NOT refuse all trades — coins decouple from BTC constantly.
- BTC making lower lows for 3+ candles = caution, not a ban. Wait for one stabilising candle.
- BTC EMA20 > EMA50 = bullish bias, be more aggressive.
- A coin's OWN technicals (RSI, volume, MACD) matter more than BTC's structure for individual entries.

SENTIMENT RULES:
- Fear & Greed < 25 (Extreme Fear) = NOT automatically a buy. Require price CONFIRMATION first (positive short-term price change, green momentum). Extreme Fear in a downtrend = falling knife.
- Fear & Greed 25-40 (Fear) = cautious only. Require strong technical confirmation.
- Fear & Greed 40-60 = neutral, rely on technicals.
- Fear & Greed > 60 = market recovering, more aggressive entries allowed.
- Fear & Greed > 75 (Extreme Greed) = NO new entries.
- Bearish news = HOLD, do not buy.
- BTC dominance rising = altcoins weakening, penalize alt entries.
- Coin trending on CoinGecko = extra momentum signal, but only with volume confirmation.

COIN TIERS (ranked by expected return potential):
- TIER 1 — SOL, NEAR, SUI, DOGE: highest volume, most reliable setups, core positions.
- TIER 2 — TAO, WLD, FET, RENDER: AI narrative coins — these DECOUPLE from BTC on AI news. A 10-25% single-day move is normal. Buy the pullback within the uptrend, not the top.
- TIER 3 — INJ, AVAX: solid mid-caps, secondary picks.
- TIER 4 — XRP, ADA: deep-liquidity large-cap alts, slower but steady.
- TIER 5 — penny/meme coins ({', '.join(s.replace('USDT', '') for s in PENNY_PAIRS)}): position size 9% (NOT 15%), stop-loss 3%, take-profit 9%. Move 10-30%/day. ONLY enter on RSI < 30 + volume spike 2x, OR breakout above BB upper with volume. Max 2 penny positions at once.
- TIER 6 — dynamic trending micro-caps: HIGHEST risk, frequently pump-and-dumps. Penny-tier sizing. Only buy volume-confirmed breakouts. When in doubt, stay out.

MOMENTUM OVERRIDE RULE:
If a coin is up 8%+ in the last 24 hours AND volume is 2x+ average AND BTC regime is not BEAR, you MAY buy even against the BTC trend. Narrative-driven momentum (AI, meme, news catalyst) overrides the BTC trend filter.

TECHNICAL RULES:
- Volume is KING — a volume spike 2x above average is a major entry signal.
- RSI below 30 on 1H = high priority entry. Below 25 = extreme priority, max size.
- 15M MACD histogram crossing positive = early momentum shift.
- EMA20 crossing above EMA50 = trend change, high priority.
- Breakout above Bollinger upper band WITH volume = strong buy for volatile coins.
- Do NOT trade BTC or ETH — too slow, not worth the capital.

RISK/REWARD RULES:
- Minimum 2.5:1 reward-to-risk ratio for all trades.
- Standard coins: 2% stop-loss, 6% take-profit.
- Penny/meme/trending coins: 3% stop-loss, 9% take-profit.
- Do NOT widen take-profit because of Extreme Fear — that caused real losses.
- Max 4 open positions at once. If 3+ are already open, HOLD everything.
- Confidence must be {MIN_BUY_CONFIDENCE}+ to open a new position.
- BEAR regime: no new entries at all.

You must respond ONLY with valid JSON in this exact format:
{{
  "symbol": "SOLUSDT",
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 1-10,
  "reasoning": "brief explanation under 150 words covering both technicals and sentiment",
  "entry_price": 12345.67,
  "stop_loss": 12100.00,
  "take_profit": 12800.00,
  "trade_type": "intraday" | "swing"
}}

If action is HOLD, set entry_price, stop_loss and take_profit to null.
Only recommend BUY when confidence is {MIN_BUY_CONFIDENCE} or above — be patient."""


def coin_type_for(symbol: str, active_trending: set = None) -> str:
    """One-line tier description injected into the user prompt."""
    active_trending = active_trending or set()
    if symbol in ("BTCUSDT", "ETHUSDT"):
        return "LARGE CAP — do not trade, too slow."
    if symbol in active_trending and symbol not in PENNY_PAIRS:
        return ("TIER 6 TRENDING MICRO-CAP — spiking on CoinGecko RIGHT NOW, HIGHEST-RISK category. "
                "Size 9%, SL 3%, TP 9%. Frequently pump-and-dumps. ONLY buy a clear volume-confirmed "
                "breakout (RSI rising, price above EMA20, volume 2x+). If extended or volume fading, HOLD.")
    if symbol in PENNY_PAIRS:
        return ("TIER 5 PENNY MEME — size 9%, SL 3%, TP 9%. Only buy on RSI<30 + volume spike 2x, "
                "or BB upper breakout with volume. Moves 10-30%/day — be very selective.")
    if symbol in ("TAOUSDT", "WLDUSDT", "FETUSDT", "RENDERUSDT"):
        return ("TIER 2 AI NARRATIVE COIN — decouples from BTC on AI news. 10-25% single-day moves are "
                "normal. Use the MOMENTUM OVERRIDE RULE when 24h change is 8%+ with volume.")
    if symbol in ("XRPUSDT", "ADAUSDT"):
        return "TIER 4 LARGE-CAP ALT — deep liquidity, slower moves, still swings 5-15% on news."
    return "MID-CAP ALTCOIN — high volatility, amplified BTC moves, look for momentum setups."


def build_user_prompt(market_data: dict, sentiment: dict = None, regime: dict = None,
                      active_trending: set = None) -> str:
    """Render one symbol's market data + sentiment + regime into the analysis prompt."""
    sym = market_data["symbol"]
    coin_type = coin_type_for(sym, active_trending)

    trending_symbols = []
    if sentiment and "trending_coins" in sentiment:
        trending_symbols = [c.get("symbol", "") for c in sentiment.get("trending_coins", [])]
    is_trending = sym.replace("USDT", "") in trending_symbols
    trending_note = "*** THIS COIN IS CURRENTLY TRENDING ON COINGECKO ***" if is_trending else ""

    sentiment_block = ""
    if sentiment:
        fng = sentiment.get("fear_and_greed", {})
        news_summary = sentiment.get("news_sentiment_summary", {})
        dominance = sentiment.get("market_dominance", {})
        headlines = sentiment.get("top_headlines", [])
        headline_text = "\n".join(
            f"  [{h.get('sentiment', '?')}] {h.get('title', '')}" for h in headlines[:5]
        )
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

    regime_block = ""
    if regime:
        r = regime.get("regime", "UNKNOWN")
        regime_block = f"""
BTC MARKET REGIME (4H — most important macro signal):
- Regime: {r} ({regime.get('bull_signals', 0)} bull signals, {regime.get('bear_signals', 0)} bear signals)
- BTC Price vs EMA20(4H): {'ABOVE' if regime.get('above_ema20_4h') else 'BELOW'}
- EMA Structure: {regime.get('ema_structure', '?')}
- BTC 4H RSI: {regime.get('rsi_4h', '?')}
- Consecutive lower lows: {regime.get('lower_lows', '?')}
{'NEUTRAL REGIME: demand strong technical confirmation before buying.' if r == 'NEUTRAL' else ''}
{'BULL REGIME: trend is up. Look for pullback entries with confirmation.' if r == 'BULL' else ''}
{'BEAR REGIME: do NOT open new positions.' if r == 'BEAR' else ''}
"""

    i15 = market_data["indicators_15m"]
    i1h = market_data["indicators_1h"]

    return f"""Analyze this crypto market data and give me your trading decision:

Coin Type: {coin_type}
{trending_note}
Symbol: {sym}
Current Price: ${market_data['price']}
24h Change: {market_data['change_24h']}%
24h High: ${market_data['high_24h']}
24h Low: ${market_data['low_24h']}
24h Volume: ${market_data['volume_24h']:,.0f}

15-Minute Chart Indicators:
- RSI(14): {i15['rsi']}
- MACD: {i15['macd']} | Signal: {i15['macd_signal']} | Histogram: {i15['macd_hist']}
- Bollinger Bands: Upper={i15['bb_upper']} | Mid={i15['bb_mid']} | Lower={i15['bb_lower']}
- EMA 20: {i15['ema_20']} | EMA 50: {i15['ema_50']}
- Price change (last 5 candles): {i15['price_change_5']}%
- Volume (latest vs avg): {i15['volume_latest']} vs {i15['volume_avg']}

1-Hour Chart Indicators:
- RSI(14): {i1h['rsi']}
- MACD Histogram: {i1h['macd_hist']}
- EMA 20: {i1h['ema_20']} | EMA 50: {i1h['ema_50']}
- Price change (last 20 candles): {i1h['price_change_20']}%
{regime_block}
{sentiment_block}
Respond with your JSON trading decision only."""


def strip_json_fence(raw: str) -> str:
    """LLMs often wrap JSON in ```json fences. Strip them."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()
