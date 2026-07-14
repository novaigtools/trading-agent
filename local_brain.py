"""
local_brain — deterministic rule engine. No network, no API keys, no LLM, no cost.

This is a direct port of the trading spec in prompts.SYSTEM_PROMPT into additive
scoring. Every decision is explainable: the reasoning string itemizes exactly which
signals fired and what each contributed, so trades.csv stays auditable forever.

Scoring: signals add points, penalties subtract, gates veto outright.
Score is clamped to 0-10 and compared against MIN_BUY_CONFIDENCE.
"""
from config import (
    PENNY_PAIRS, NEVER_TRADE, MIN_BUY_CONFIDENCE, HOLD_ALL_AT_POSITIONS,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, PENNY_STOP_LOSS_PCT, PENNY_TAKE_PROFIT_PCT,
)

# --- Signal weights ----------------------------------------------------------
# Calibrated so that the two canonical setups in the spec land exactly on the buy bar
# (MIN_BUY_CONFIDENCE = 8) and NO single signal can trigger a trade on its own —
# every entry needs genuine confluence.
#   oversold bounce : RSI<30 (4) + volume 2x (4)          = 8  -> BUY
#   narrative move  : momentum (4) + volume 2x (4)        = 8  -> BUY
#   lone signal     : max 5                               = 5  -> HOLD
W_RSI_EXTREME      = 5   # 1H RSI < 25 — "EXTREME priority, maximum allowed position size"
W_RSI_OVERSOLD     = 4   # 1H RSI < 30 — "high priority entry for ALL coins"
W_VOLUME_SPIKE     = 4   # volume >= 2x average — "Volume is KING"
W_MACD_FLIP        = 2   # 15M MACD histogram positive — early momentum shift
W_EMA_CROSS        = 2   # EMA20 > EMA50 on 15M — trend change
W_BB_BREAKOUT      = 2   # close above BB upper WITH volume confirmation
W_MOMENTUM_OVERRIDE = 4  # 24h >= +8% and volume >= 2x — narrative move (TAO/WLD style)
W_REGIME_BULL      = 1   # BTC regime tailwind

# --- Penalties ---------------------------------------------------------------
P_EMA_BEARISH_BOTH = -2  # EMA20 < EMA50 on BOTH timeframes
P_BTC_DOMINANCE_UP = -1  # BTC dominance rising = alts weakening
P_NEWS_BEARISH     = -1  # bearish news backdrop

VOLUME_SPIKE_X   = 2.0
MOMENTUM_24H_PCT = 8.0


def _fmt(x) -> str:
    try:
        return f"{float(x):g}"
    except (TypeError, ValueError):
        return str(x)


def _hold(symbol: str, price, reason: str, confidence: int = 0) -> dict:
    return {
        "symbol": symbol,
        "action": "HOLD",
        "confidence": confidence,
        "reasoning": f"RULES: {reason}",
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "trade_type": "intraday",
        "market_price": price,
    }


def score_symbol(market_data: dict, sentiment: dict = None, regime: dict = None,
                 active_trending: set = None, open_positions: dict = None) -> dict:
    """
    Score one symbol and return a decision dict matching the shared contract.
    Pure function — no I/O, no globals, safe to unit test.
    """
    sentiment       = sentiment or {}
    regime          = regime or {}
    active_trending = active_trending or set()
    open_positions  = open_positions or {}

    symbol = market_data["symbol"]
    price  = market_data.get("price")

    # ---- Hard gates (vetoes) ------------------------------------------------
    if symbol in NEVER_TRADE:
        return _hold(symbol, price, f"{symbol} is on the never-trade list (too slow).")

    regime_str = regime.get("regime", "UNKNOWN")
    if regime_str == "BEAR":
        return _hold(symbol, price, "BEAR regime — no new entries (capital protection).")

    if len(open_positions) >= HOLD_ALL_AT_POSITIONS:
        return _hold(symbol, price,
                     f"{len(open_positions)} positions already open (>= {HOLD_ALL_AT_POSITIONS}) — "
                     f"holding everything until one closes.")

    if symbol in open_positions:
        return _hold(symbol, price, "Already holding this symbol.")

    i15 = market_data.get("indicators_15m", {})
    i1h = market_data.get("indicators_1h", {})
    if not i15 or not i1h:
        return _hold(symbol, price, "Missing indicator data.")

    fng_raw = (sentiment.get("fear_and_greed") or {}).get("value")
    try:
        fng = int(fng_raw) if fng_raw is not None else None
    except (TypeError, ValueError):
        fng = None

    price_change_5 = i15.get("price_change_5", 0) or 0
    macd_hist_15   = i15.get("macd_hist", 0) or 0

    # Extreme Greed — no new entries, full stop.
    if fng is not None and fng > 75:
        return _hold(symbol, price, f"Fear & Greed {fng} > 75 (Extreme Greed) — no new entries.")

    # Extreme Fear falling-knife guard: needs price confirmation before ANY buy.
    fear_gate_note = ""
    if fng is not None and fng < 25:
        confirmed = price_change_5 > 0 or macd_hist_15 > 0
        if not confirmed:
            return _hold(symbol, price,
                         f"Fear & Greed {fng} (Extreme Fear) with no price confirmation "
                         f"(15M change {_fmt(price_change_5)}%, MACD hist {_fmt(macd_hist_15)}) — "
                         f"falling knife, staying out.")
        fear_gate_note = f"ExtFear {fng} confirmed by green 15M (gate passed)"

    # ---- Additive signals ---------------------------------------------------
    score   = 0
    fired   = []   # human-readable itemization for the reasoning string
    n_entry = 0    # count of INDEPENDENT entry signals (for the NEUTRAL 2-signal rule)

    rsi_1h     = i1h.get("rsi")
    vol_latest = i15.get("volume_latest", 0) or 0
    vol_avg    = i15.get("volume_avg", 0) or 0
    vol_ratio  = (vol_latest / vol_avg) if vol_avg else 0
    change_24h = market_data.get("change_24h", 0) or 0

    if rsi_1h is not None and rsi_1h < 25:
        score += W_RSI_EXTREME
        n_entry += 1
        fired.append(f"1H RSI {_fmt(rsi_1h)} <25 EXTREME (+{W_RSI_EXTREME})")
    elif rsi_1h is not None and rsi_1h < 30:
        score += W_RSI_OVERSOLD
        n_entry += 1
        fired.append(f"1H RSI {_fmt(rsi_1h)} <30 oversold (+{W_RSI_OVERSOLD})")

    if vol_ratio >= VOLUME_SPIKE_X:
        score += W_VOLUME_SPIKE
        n_entry += 1
        fired.append(f"vol {vol_ratio:.1f}x avg (+{W_VOLUME_SPIKE})")

    # MACD histogram positive on 15M = momentum shifting up.
    if macd_hist_15 > 0:
        score += W_MACD_FLIP
        n_entry += 1
        fired.append(f"15M MACD hist +{_fmt(macd_hist_15)} (+{W_MACD_FLIP})")

    ema20_15 = i15.get("ema_20")
    ema50_15 = i15.get("ema_50")
    if ema20_15 and ema50_15 and ema20_15 > ema50_15:
        score += W_EMA_CROSS
        n_entry += 1
        fired.append(f"15M EMA20>EMA50 trend up (+{W_EMA_CROSS})")

    # Bollinger breakout only counts WITH volume — otherwise it's a fakeout.
    bb_upper = i15.get("bb_upper")
    if bb_upper and price and price > bb_upper and vol_ratio >= VOLUME_SPIKE_X:
        score += W_BB_BREAKOUT
        n_entry += 1
        fired.append(f"BB upper breakout w/ volume (+{W_BB_BREAKOUT})")

    # Momentum override — narrative moves that decouple from BTC entirely.
    momentum_override = (
        change_24h >= MOMENTUM_24H_PCT
        and vol_ratio >= VOLUME_SPIKE_X
        and regime_str != "BEAR"
    )
    if momentum_override:
        score += W_MOMENTUM_OVERRIDE
        n_entry += 1
        fired.append(f"MOMENTUM OVERRIDE: 24h +{_fmt(change_24h)}% on {vol_ratio:.1f}x vol "
                     f"(+{W_MOMENTUM_OVERRIDE})")

    if regime_str == "BULL":
        score += W_REGIME_BULL
        fired.append(f"BTC regime BULL (+{W_REGIME_BULL})")

    # ---- Penalties ----------------------------------------------------------
    ema20_1h = i1h.get("ema_20")
    ema50_1h = i1h.get("ema_50")
    bearish_15 = ema20_15 and ema50_15 and ema20_15 < ema50_15
    bearish_1h = ema20_1h and ema50_1h and ema20_1h < ema50_1h
    if bearish_15 and bearish_1h and not momentum_override:
        score += P_EMA_BEARISH_BOTH
        fired.append(f"EMA20<EMA50 on both TFs ({P_EMA_BEARISH_BOTH})")

    dominance = sentiment.get("market_dominance") or {}
    dom_now, dom_yday = dominance.get("btc_dominance"), dominance.get("btc_dominance_yesterday")
    if dom_now and dom_yday and dom_now > dom_yday:
        score += P_BTC_DOMINANCE_UP
        fired.append(f"BTC dominance rising {_fmt(dom_yday)}->{_fmt(dom_now)}% ({P_BTC_DOMINANCE_UP})")

    news = sentiment.get("news_sentiment_summary") or {}
    if str(news.get("overall", "")).lower() == "bearish":
        score += P_NEWS_BEARISH
        fired.append(f"bearish news backdrop ({P_NEWS_BEARISH})")

    score = max(0, min(10, score))

    if fear_gate_note:
        fired.append(fear_gate_note)

    # ---- Decision -----------------------------------------------------------
    # NEUTRAL regime demands at least TWO independent entry signals — one lonely
    # signal in a directionless market is how the old bot got chopped up.
    if regime_str == "NEUTRAL" and n_entry < 2:
        return _hold(symbol, price,
                     f"NEUTRAL regime needs 2+ independent entry signals, got {n_entry}. "
                     f"Signals: {'; '.join(fired) if fired else 'none'}. Score {score}/10.",
                     confidence=score)

    detail = "; ".join(fired) if fired else "no signals fired"

    if score >= MIN_BUY_CONFIDENCE:
        is_penny = symbol in PENNY_PAIRS or symbol in active_trending
        sl_pct = PENNY_STOP_LOSS_PCT if is_penny else STOP_LOSS_PCT
        tp_pct = PENNY_TAKE_PROFIT_PCT if is_penny else TAKE_PROFIT_PCT
        tier   = "penny/trending" if is_penny else "standard"
        return {
            "symbol": symbol,
            "action": "BUY",
            "confidence": score,
            "reasoning": f"RULES: {detail}. Score {score}/10 (>= {MIN_BUY_CONFIDENCE}). "
                         f"Tier {tier}: SL {sl_pct:.0%}, TP {tp_pct:.0%}.",
            "entry_price": price,
            "stop_loss": round(price * (1 - sl_pct), 8),
            "take_profit": round(price * (1 + tp_pct), 8),
            "trade_type": "intraday",
            "market_price": price,
        }

    return _hold(symbol, price,
                 f"{detail}. Score {score}/10 (< {MIN_BUY_CONFIDENCE} required).",
                 confidence=score)


def get_decisions_for_all(market_data_list: list, sentiment: dict = None, regime: dict = None,
                          active_trending: set = None, open_positions: dict = None) -> list:
    """Score every symbol. Never raises — a bad symbol becomes a HOLD, not an outage."""
    decisions = []
    for md in market_data_list:
        if "error" in md:
            print(f"  Skipping {md['symbol']} — fetch error: {md['error']}")
            continue
        try:
            decisions.append(
                score_symbol(md, sentiment, regime, active_trending, open_positions)
            )
        except Exception as e:  # a rule bug must never take the whole scan down
            print(f"  Rule engine error on {md.get('symbol', '?')}: {e}")
            decisions.append(_hold(md.get("symbol", "?"), md.get("price"),
                                   f"rule engine error: {e}"))
    return decisions
