"""
Tests for the rule engine.

These encode the trading spec as executable checks. If someone (including a future
Claude) changes a weight and breaks a rule, these fail loudly instead of the bot
quietly making bad trades with real-looking reasoning.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_brain
from config import MIN_BUY_CONFIDENCE


def make_market_data(symbol="SOLUSDT", price=100.0, change_24h=0.0,
                     rsi_1h=50.0, rsi_15m=50.0,
                     vol_latest=1000.0, vol_avg=1000.0,
                     macd_hist_15m=0.0, macd_hist_1h=0.0,
                     ema20_15m=100.0, ema50_15m=100.0,
                     ema20_1h=100.0, ema50_1h=100.0,
                     bb_upper=110.0, price_change_5=0.0, price_change_20=0.0):
    """A neutral baseline; each test perturbs only the fields it cares about."""
    return {
        "symbol": symbol,
        "price": price,
        "change_24h": change_24h,
        "high_24h": price * 1.05,
        "low_24h": price * 0.95,
        "volume_24h": 50_000_000,
        "indicators_15m": {
            "rsi": rsi_15m, "macd": 0.0, "macd_signal": 0.0, "macd_hist": macd_hist_15m,
            "bb_upper": bb_upper, "bb_mid": 100.0, "bb_lower": 90.0,
            "ema_20": ema20_15m, "ema_50": ema50_15m,
            "current_price": price,
            "volume_avg": vol_avg, "volume_latest": vol_latest,
            "price_change_5": price_change_5, "price_change_20": price_change_20,
        },
        "indicators_1h": {
            "rsi": rsi_1h, "macd": 0.0, "macd_signal": 0.0, "macd_hist": macd_hist_1h,
            "bb_upper": bb_upper, "bb_mid": 100.0, "bb_lower": 90.0,
            "ema_20": ema20_1h, "ema_50": ema50_1h,
            "current_price": price,
            "volume_avg": vol_avg, "volume_latest": vol_latest,
            "price_change_5": price_change_5, "price_change_20": price_change_20,
        },
    }


def sentiment(fng=50, news="neutral", dom=58.0, dom_yday=58.0):
    return {
        "fear_and_greed": {"value": fng, "label": "Neutral"},
        "news_sentiment_summary": {"overall": news},
        "market_dominance": {"btc_dominance": dom, "btc_dominance_yesterday": dom_yday},
        "trending_coins": [],
    }


BULL    = {"regime": "BULL",    "bull_signals": 5, "bear_signals": 1}
NEUTRAL = {"regime": "NEUTRAL", "bull_signals": 3, "bear_signals": 3}
BEAR    = {"regime": "BEAR",    "bull_signals": 1, "bear_signals": 5}


def test_oversold_plus_volume_in_neutral_is_a_buy():
    """1H RSI 26 + 2.5x volume in NEUTRAL -> BUY at >= MIN_BUY_CONFIDENCE."""
    md = make_market_data(rsi_1h=26.0, vol_latest=2500.0, vol_avg=1000.0)
    d = local_brain.score_symbol(md, sentiment(), NEUTRAL)
    assert d["action"] == "BUY"
    assert d["confidence"] >= MIN_BUY_CONFIDENCE
    assert d["market_price"] == md["price"]     # trader.py needs this key
    assert d["stop_loss"] < md["price"] < d["take_profit"]
    assert "RSI" in d["reasoning"] and "vol" in d["reasoning"]  # auditable


def test_same_setup_in_bear_regime_is_a_hold():
    """The exact setup above, but BEAR -> no new entries, full stop."""
    md = make_market_data(rsi_1h=26.0, vol_latest=2500.0, vol_avg=1000.0)
    d = local_brain.score_symbol(md, sentiment(), BEAR)
    assert d["action"] == "HOLD"
    assert "BEAR" in d["reasoning"]


def test_extreme_fear_without_price_confirmation_is_a_falling_knife():
    """F&G 20 + falling price = the exact trade that lost real money. HOLD."""
    md = make_market_data(rsi_1h=26.0, vol_latest=2500.0, vol_avg=1000.0,
                          price_change_5=-1.5, macd_hist_15m=-0.02)
    d = local_brain.score_symbol(md, sentiment(fng=20), NEUTRAL)
    assert d["action"] == "HOLD"
    assert "falling knife" in d["reasoning"].lower()


def test_extreme_fear_with_price_confirmation_may_buy():
    """Same Extreme Fear, but price is turning up -> the gate passes."""
    md = make_market_data(rsi_1h=26.0, vol_latest=2500.0, vol_avg=1000.0,
                          price_change_5=+1.2, macd_hist_15m=0.03)
    d = local_brain.score_symbol(md, sentiment(fng=20), NEUTRAL)
    assert d["action"] == "BUY"
    assert "gate passed" in d["reasoning"]


def test_extreme_greed_blocks_everything():
    """F&G 80 -> no new entries regardless of how good the technicals look."""
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0,
                          macd_hist_15m=0.5, ema20_15m=105.0, ema50_15m=100.0)
    d = local_brain.score_symbol(md, sentiment(fng=80), BULL)
    assert d["action"] == "HOLD"
    assert "Extreme Greed" in d["reasoning"]


def test_momentum_override_allows_buy_against_btc_trend():
    """+12% 24h on 2.3x volume in NEUTRAL -> the TAO/WLD narrative move. BUY."""
    md = make_market_data(
        symbol="TAOUSDT", change_24h=12.0, vol_latest=2300.0, vol_avg=1000.0,
        rsi_1h=58.0,                       # NOT oversold — momentum is the whole thesis
        ema20_15m=98.0, ema50_15m=100.0,   # BTC-ish trend still bearish
        ema20_1h=98.0, ema50_1h=100.0,
    )
    d = local_brain.score_symbol(md, sentiment(), NEUTRAL)
    assert d["action"] == "BUY"
    assert "MOMENTUM OVERRIDE" in d["reasoning"]


def test_three_open_positions_holds_everything():
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)
    open_pos = {"SUIUSDT": {}, "NEARUSDT": {}, "DOGEUSDT": {}}
    d = local_brain.score_symbol(md, sentiment(), BULL, open_positions=open_pos)
    assert d["action"] == "HOLD"
    assert "already open" in d["reasoning"]


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT"])
def test_btc_and_eth_are_never_traded(symbol):
    md = make_market_data(symbol=symbol, rsi_1h=20.0, vol_latest=9000.0, vol_avg=1000.0)
    d = local_brain.score_symbol(md, sentiment(), BULL)
    assert d["action"] == "HOLD"
    assert "never-trade" in d["reasoning"]


def test_neutral_regime_requires_two_independent_signals():
    """A single lonely signal in a directionless market is how the bot got chopped up."""
    md = make_market_data(rsi_1h=28.0)  # oversold and nothing else
    d = local_brain.score_symbol(md, sentiment(), NEUTRAL)
    assert d["action"] == "HOLD"
    assert "2+ independent entry signals" in d["reasoning"]


def test_penny_coin_gets_wider_stops_than_standard():
    """Memes whipsaw — 3% SL / 9% TP, not 2% / 6%."""
    penny = make_market_data(symbol="PEPEUSDT", price=100.0, rsi_1h=26.0,
                             vol_latest=2500.0, vol_avg=1000.0)
    std = make_market_data(symbol="SOLUSDT", price=100.0, rsi_1h=26.0,
                           vol_latest=2500.0, vol_avg=1000.0)
    dp = local_brain.score_symbol(penny, sentiment(), NEUTRAL)
    ds = local_brain.score_symbol(std, sentiment(), NEUTRAL)
    assert dp["action"] == ds["action"] == "BUY"
    assert dp["stop_loss"] < ds["stop_loss"]        # penny stop is wider (further down)
    assert dp["take_profit"] > ds["take_profit"]    # penny target is further up


def test_already_holding_symbol_is_a_hold():
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)
    d = local_brain.score_symbol(md, sentiment(), BULL,
                                 open_positions={"SOLUSDT": {"entry_price": 90}})
    assert d["action"] == "HOLD"
    assert "Already holding" in d["reasoning"]


def test_engine_never_raises_on_garbage_input():
    """A rule bug must degrade one symbol to HOLD, never take the scan down."""
    decisions = local_brain.get_decisions_for_all(
        [{"symbol": "JUNKUSDT", "price": 1.0}],  # no indicators at all
        sentiment(), NEUTRAL)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "HOLD"


def test_fetch_errors_are_skipped_not_traded():
    decisions = local_brain.get_decisions_for_all(
        [{"symbol": "BROKENUSDT", "error": "timeout"}], sentiment(), NEUTRAL)
    assert decisions == []
