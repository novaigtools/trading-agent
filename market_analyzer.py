import concurrent.futures
import requests
import pandas as pd
import ta
from config import BINANCE_BASE_URL, TRADING_PAIRS, PENNY_PAIRS, NEVER_TRADE

try:
    from config import SCAN_MAX_WORKERS
except ImportError:
    SCAN_MAX_WORKERS = 8

# Excluded from the liquid universe: stablecoins, wrapped/staked tokens, and fiat —
# they either don't move (stables) or double-count majors (wrapped). Substring match.
_UNIVERSE_EXCLUDE = (
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "USTC", "EUR", "GBP", "AEUR", "USD1",
    "WBTC", "WBETH", "WETH", "BTCUSDT", "ETHUSDT", "USDEUSDT", "BUSD", "RLUSD",
    "XUSD", "USDG", "PYUSD", "BFUSD",
)


def get_liquid_universe(top_n: int = 100, min_volume_usd: float = 5_000_000) -> list[str]:
    """
    Top USDT spot pairs by 24h quote volume, excluding stablecoins/wrapped/fiat and the
    never-trade majors. One API call returns every ticker, so this is cheap. Returns a
    volume-sorted list of symbols like ['SOLUSDT', 'DOGEUSDT', ...].
    """
    try:
        r = requests.get(f"{BINANCE_BASE_URL}/api/v3/ticker/24hr", timeout=20)
        r.raise_for_status()
        tickers = r.json()
    except Exception as e:
        print(f"  Liquid-universe fetch failed: {e}")
        return []

    rows = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        if sym in NEVER_TRADE or any(x in sym for x in _UNIVERSE_EXCLUDE):
            continue
        if "UP" in sym or "DOWN" in sym or "BULL" in sym or "BEAR" in sym:
            continue  # leveraged tokens
        try:
            vol = float(t.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if vol >= min_volume_usd:
            rows.append((sym, vol))

    rows.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in rows[:top_n]]


def fetch_ohlcv(symbol: str, interval: str = "15m", limit: int = 100) -> pd.DataFrame:
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_ticker(symbol: str) -> dict:
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/24hr"
    response = requests.get(url, params={"symbol": symbol}, timeout=10)
    response.raise_for_status()
    return response.json()


def _round_price(x: float) -> float:
    """
    Round a price-like value keeping ~6 significant figures, so cheap coins survive.
    A flat round(x, 4) collapses sub-$0.0001 coins (PEPE ~0.0000028, micro-caps) to
    0.0 — which fed garbage indicators to the rule engine and once divided-by-zero in
    position sizing. Significant-figure rounding preserves precision at any magnitude.
    """
    x = float(x)
    if x == 0 or not (x == x):  # zero or NaN
        return 0.0
    import math
    digits = 6 - int(math.floor(math.log10(abs(x)))) - 1
    return round(x, max(digits, 4))


def compute_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    volume = df["volume"]

    rsi = ta.momentum.RSIIndicator(close=close, window=14).rsi()
    macd_obj = ta.trend.MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    bb_obj = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    ema_20 = ta.trend.EMAIndicator(close=close, window=20).ema_indicator()
    ema_50 = ta.trend.EMAIndicator(close=close, window=50).ema_indicator()

    return {
        "rsi": round(float(rsi.iloc[-1]), 2),
        "macd": round(float(macd_obj.macd().iloc[-1]), 4),
        "macd_signal": round(float(macd_obj.macd_signal().iloc[-1]), 4),
        "macd_hist": round(float(macd_obj.macd_diff().iloc[-1]), 4),
        "bb_upper": _round_price(bb_obj.bollinger_hband().iloc[-1]),
        "bb_mid": _round_price(bb_obj.bollinger_mavg().iloc[-1]),
        "bb_lower": _round_price(bb_obj.bollinger_lband().iloc[-1]),
        "ema_20": _round_price(ema_20.iloc[-1]),
        "ema_50": _round_price(ema_50.iloc[-1]),
        "current_price": _round_price(close.iloc[-1]),
        "volume_avg": round(float(volume.tail(20).mean()), 2),
        "volume_latest": round(float(volume.iloc[-1]), 2),
        "price_change_5": round(float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100), 2),
        "price_change_20": round(float((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20] * 100), 2),
    }


def analyze_pair(symbol: str) -> dict:
    try:
        df_15m = fetch_ohlcv(symbol, "15m", 100)
        df_1h = fetch_ohlcv(symbol, "1h", 50)
        ticker = fetch_ticker(symbol)
        indicators_15m = compute_indicators(df_15m)
        indicators_1h = compute_indicators(df_1h)

        return {
            "symbol": symbol,
            "price": indicators_15m["current_price"],
            "change_24h": round(float(ticker["priceChangePercent"]), 2),
            "volume_24h": round(float(ticker["quoteVolume"]), 0),
            "high_24h": round(float(ticker["highPrice"]), 4),
            "low_24h": round(float(ticker["lowPrice"]), 4),
            "indicators_15m": indicators_15m,
            "indicators_1h": indicators_1h,
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def get_btc_market_regime() -> dict:
    """
    Analyse BTC on 4H to determine the macro market regime.
    Returns: regime ('BULL'|'BEAR'|'NEUTRAL'), strength, and key levels.
    Claude should NOT open new longs in BEAR regime.
    """
    try:
        df_4h  = fetch_ohlcv("BTCUSDT", "4h",  100)
        df_1d  = fetch_ohlcv("BTCUSDT", "1d",   30)
        ind_4h = compute_indicators(df_4h)
        ind_1d = compute_indicators(df_1d)

        price     = ind_4h["current_price"]
        ema20_4h  = ind_4h["ema_20"]
        ema50_4h  = ind_4h["ema_50"]
        ema20_1d  = ind_1d["ema_20"]
        rsi_4h    = ind_4h["rsi"]
        macd_4h   = ind_4h["macd_hist"]

        # Count consecutive lower lows on 4H (last 6 candles)
        closes_4h = df_4h["close"].tail(6).tolist()
        lower_lows = sum(1 for i in range(1, len(closes_4h)) if closes_4h[i] < closes_4h[i-1])

        bull_signals = 0
        bear_signals = 0

        if price > ema20_4h:  bull_signals += 1
        else:                  bear_signals += 1

        if ema20_4h > ema50_4h: bull_signals += 1
        else:                    bear_signals += 1

        if price > ema20_1d:  bull_signals += 1
        else:                  bear_signals += 1

        if macd_4h > 0:  bull_signals += 1
        else:             bear_signals += 1

        if rsi_4h > 50:  bull_signals += 1
        else:             bear_signals += 1

        if lower_lows >= 4:  bear_signals += 2   # strong downtrend penalty
        elif lower_lows <= 1: bull_signals += 1

        if bull_signals >= 5:    regime = "BULL"
        elif bear_signals >= 5:  regime = "BEAR"
        else:                    regime = "NEUTRAL"

        return {
            "regime":      regime,
            "bull_signals": bull_signals,
            "bear_signals": bear_signals,
            "price":       price,
            "ema20_4h":    round(ema20_4h, 2),
            "ema50_4h":    round(ema50_4h, 2),
            "ema20_1d":    round(ema20_1d, 2),
            "rsi_4h":      rsi_4h,
            "macd_hist_4h": macd_4h,
            "lower_lows":  lower_lows,
            "above_ema20_4h": price > ema20_4h,
            "ema_structure": "EMA20>EMA50 (bullish)" if ema20_4h > ema50_4h else "EMA20<EMA50 (bearish)",
        }
    except Exception as e:
        return {"regime": "UNKNOWN", "error": str(e)}


def analyze_all_pairs(extra_pairs: list = None) -> list[dict]:
    all_pairs = TRADING_PAIRS + PENNY_PAIRS + list(extra_pairs or [])
    # De-dup while preserving order (a trending/universe coin may already be listed)
    seen = set()
    all_pairs = [p for p in all_pairs if not (p in seen or seen.add(p))]

    # Fetch in parallel — each coin is 3 network calls, so a 100-coin list scans in
    # seconds instead of minutes and stays well inside the staleness guard.
    print(f"  Analyzing {len(all_pairs)} pairs (parallel, {SCAN_MAX_WORKERS} workers)...")
    results = [None] * len(all_pairs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_MAX_WORKERS) as pool:
        future_to_idx = {pool.submit(analyze_pair, p): i for i, p in enumerate(all_pairs)}
        for fut in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {"symbol": all_pairs[idx], "error": str(e)}
    return results
