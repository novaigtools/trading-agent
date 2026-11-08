"""
market_research.py - market-wide trend analyst. Runs every 4 hours on GitHub Actions.

Why this exists
---------------
The bot only scores the coins on its watchlist, one scan at a time. It has no view of the
whole market: which coins are holding up while BTC falls, how many coins are trending up
(breadth), or which coins outside the watchlist deserve a place on it. This script scans
EVERY liquid Binance USDT coin and writes that picture to docs/research.json, which the
dashboard's Research page renders.

It is research only: it never trades and never touches risk_state.json / trades.csv.
Stdlib only (like sl_monitor.py) so it runs on GitHub without pip install. Free, keyless
public market data.

Cadence: every 4h. That matches the 4H candles the BTC regime is built on - faster
mostly re-reports noise, slower misses turns in a market that moves 10% in a day.
"""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")
REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "docs", "research.json")
HISTORY = os.path.join(REPO, "docs", "research_history.json")
HISTORY_MAX = 540            # ~90 days of 4-hourly snapshots
MIN_VOLUME_USD = 2_000_000   # 24h quote volume floor for "liquid"
MAX_COINS = 200

# Stablecoins / fiat / wrapped / gold: they don't trend, so they'd pollute breadth.
NOT_A_COIN = re.compile(
    r"^(USDC|FDUSD|TUSD|DAI|USDP|USTC|EUR|GBP|AEUR|USD1|RLUSD|RWUSD|XUSD|USDG|PYUSD|BFUSD|"
    r"USDE|U|BUSD|WBTC|WBETH|WETH|PAXG|XAUT)USDT$")
LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)USDT$")
TICKER_OK = re.compile(r"^[A-Z0-9]+USDT$")


def _get(path):
    last = None
    for host in HOSTS:   # api.binance.com can be geo-blocked on cloud runners
        try:
            with urllib.request.urlopen(host + path, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
    raise last


# ---- indicators (stdlib) ---------------------------------------------------------

def ema(xs, n):
    k, out = 2 / (n + 1), []
    for x in xs:
        out.append(x if not out else out[-1] + k * (x - out[-1]))
    return out


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    gains = [max(b - a, 0) for a, b in zip(xs, xs[1:])]
    losses = [max(a - b, 0) for a, b in zip(xs, xs[1:])]
    g, l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for gi, li in zip(gains[n:], losses[n:]):
        g, l = (g * (n - 1) + gi) / n, (l * (n - 1) + li) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def pct(a, b):
    return (a / b - 1) * 100 if b else None


# ---- per-coin analysis -----------------------------------------------------------

def classify(c):
    """Plain-language trend label. Order matters: first match wins."""
    above20, above50 = c["vs_ema20d"] > 0, c["vs_ema50d"] > 0
    if above20 and above50 and c["ema20_gt_50_4h"] and c["ret_7d"] > 0:
        return "Strong uptrend"
    if c["ret_7d"] > 0 and c["rs_7d"] > 3:
        return "Rising vs market"
    if c["rs_7d"] > 0 and c["ret_7d"] > -3:
        return "Holding up"
    if not above20 and c["ema20_gt_50_4h"] and c["ret_1d"] > 0:
        return "Trying to turn up"
    if c["from_30d_high"] < -35 and c["ret_7d"] < -10:
        return "Falling hard"
    return "Downtrend"


def analyse(sym, ticker, btc):
    d = _get(f"/api/v3/klines?symbol={sym}&interval=1d&limit=60")
    h = _get(f"/api/v3/klines?symbol={sym}&interval=4h&limit=60")
    if len(d) < 31 or len(h) < 50:
        return None   # too new to judge a trend
    cd = [float(k[4]) for k in d]
    hd = [float(k[2]) for k in d]
    c4 = [float(k[4]) for k in h]
    px = float(ticker["lastPrice"])
    e20d, e50d = ema(cd, 20)[-1], ema(cd, 50 if len(cd) >= 50 else len(cd))[-1]
    e20h, e50h = ema(c4, 20)[-1], ema(c4, 50)[-1]
    c = {
        "symbol": sym,
        "price": px,
        "volume_24h_musd": round(float(ticker["quoteVolume"]) / 1e6, 1),
        "ret_1d": round(float(ticker["priceChangePercent"]), 2),
        "ret_3d": round(pct(px, cd[-4]), 2),
        "ret_7d": round(pct(px, cd[-8]), 2),
        "ret_30d": round(pct(px, cd[-31]), 2),
        "vs_ema20d": round(pct(px, e20d), 2),
        "vs_ema50d": round(pct(px, e50d), 2),
        "ema20_gt_50_4h": e20h > e50h,
        "rsi_1d": round(rsi(cd) or 0, 1),
        "rsi_4h": round(rsi(c4) or 0, 1),
        "from_30d_high": round(pct(px, max(hd[-30:])), 2),
    }
    if btc:
        c["rs_7d"] = round(c["ret_7d"] - btc["ret_7d"], 2)
        c["rs_30d"] = round(c["ret_30d"] - btc["ret_30d"], 2)
    else:
        c["rs_7d"] = c["rs_30d"] = 0.0
    c["trend"] = classify(c)
    return c


def _fear_greed():
    try:
        with urllib.request.urlopen("https://api.alternative.me/fng/?limit=1", timeout=15) as r:
            v = json.loads(r.read())["data"][0]
        return {"value": int(v["value"]), "label": v["value_classification"]}
    except Exception:
        return None


def _watchlist():
    """The bot's own coin lists, read from config.py without importing it (config pulls
    in dotenv, which isn't installed on the bare research runner)."""
    try:
        src = open(os.path.join(REPO, "config.py"), encoding="utf-8").read()
        out = {}
        for name in ("TRADING_PAIRS", "PENNY_PAIRS"):
            m = re.search(name + r"\s*=\s*\[(.*?)\]", src, re.S)
            out[name] = re.findall(r'"([A-Z0-9]+USDT)"', m.group(1)) if m else []
        return out
    except Exception:
        return {"TRADING_PAIRS": [], "PENNY_PAIRS": []}


def run():
    t0 = time.time()
    tickers = _get("/api/v3/ticker/24hr")
    by_sym = {t["symbol"]: t for t in tickers}
    liquid = sorted(
        (t for t in tickers
         if TICKER_OK.match(t["symbol"]) and not NOT_A_COIN.match(t["symbol"])
         and not LEVERAGED.search(t["symbol"])
         and float(t.get("quoteVolume", 0)) >= MIN_VOLUME_USD and float(t.get("lastPrice", 0)) > 0),
        key=lambda t: -float(t["quoteVolume"]))[:MAX_COINS]

    btc = analyse("BTCUSDT", by_sym["BTCUSDT"], None)
    syms = [t["symbol"] for t in liquid if t["symbol"] != "BTCUSDT"]

    def safe(s):
        try:
            return analyse(s, by_sym[s], btc)
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        coins = [c for c in ex.map(safe, syms) if c]

    wl = _watchlist()
    watch = set(wl["TRADING_PAIRS"]) | set(wl["PENNY_PAIRS"])
    for c in coins:
        c["on_watchlist"] = c["symbol"] in watch

    n = len(coins) or 1
    med = lambda k: sorted(c[k] for c in coins)[len(coins) // 2] if coins else 0
    counts = {}
    for c in coins:
        counts[c["trend"]] = counts.get(c["trend"], 0) + 1
    breadth20 = sum(c["vs_ema20d"] > 0 for c in coins) / n * 100
    breadth50 = sum(c["vs_ema50d"] > 0 for c in coins) / n * 100
    up7 = sum(c["ret_7d"] > 0 for c in coins) / n * 100

    if breadth20 >= 60 and btc["vs_ema20d"] > 0:
        mood = "Healthy: most coins are above their 20-day average"
    elif breadth20 >= 40:
        mood = "Mixed: no clear direction, be selective"
    elif breadth20 >= 20:
        mood = "Weak: most coins are in downtrends"
    else:
        mood = "Washed out: almost everything is falling (bounces are common from here)"

    # Strongest = rising against the market, liquid, not already a blow-off.
    leaders = sorted((c for c in coins if c["rs_7d"] > 0 and c["ret_7d"] > 0 and c["rsi_1d"] < 80),
                     key=lambda c: -c["rs_7d"])[:15]
    # Candidates the bot doesn't watch yet: established (30d+ history), real volume,
    # in a genuine uptrend, not a one-day spike.
    candidates = [c for c in coins
                  if not c["on_watchlist"] and c["volume_24h_musd"] >= 5
                  and c["trend"] in ("Strong uptrend", "Rising vs market")
                  and c["ret_1d"] < 25 and c["rsi_1d"] < 75][:10]
    weakest = sorted(coins, key=lambda c: c["rs_7d"])[:10]

    now = datetime.now(timezone.utc)
    report = {
        "generated_utc": now.isoformat(timespec="seconds"),
        "coins_analysed": len(coins),
        "runtime_s": round(time.time() - t0, 1),
        "market": {
            "mood": mood,
            "btc": {k: btc[k] for k in ("price", "ret_1d", "ret_7d", "ret_30d", "vs_ema20d",
                                         "vs_ema50d", "rsi_1d", "trend")} if btc else None,
            "fear_greed": _fear_greed(),
            "breadth_above_ema20d_pct": round(breadth20, 1),
            "breadth_above_ema50d_pct": round(breadth50, 1),
            "up_7d_pct": round(up7, 1),
            "median_ret_7d": round(med("ret_7d"), 2),
            "median_ret_30d": round(med("ret_30d"), 2),
            "trend_counts": counts,
        },
        "leaders": leaders,
        "watchlist_candidates": candidates,
        "weakest": weakest,
        "watchlist": sorted((c for c in coins if c["on_watchlist"]), key=lambda c: -c["rs_7d"]),
        "coins": sorted(coins, key=lambda c: -c["rs_7d"]),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1)

    # Rolling history so the page can show whether the market is improving or worsening.
    try:
        hist = json.load(open(HISTORY, encoding="utf-8"))
    except Exception:
        hist = []
    hist.append({"t": report["generated_utc"], "breadth20": report["market"]["breadth_above_ema20d_pct"],
                 "up7": report["market"]["up_7d_pct"], "btc": btc["price"] if btc else None,
                 "med7": report["market"]["median_ret_7d"]})
    with open(HISTORY, "w", encoding="utf-8", newline="\n") as f:
        json.dump(hist[-HISTORY_MAX:], f)
    return report


if __name__ == "__main__":
    r = run()
    m = r["market"]
    print(f"Analysed {r['coins_analysed']} coins in {r['runtime_s']}s - {m['mood']}")
    print(f"Breadth: {m['breadth_above_ema20d_pct']}% above 20d avg | {m['up_7d_pct']}% up on the week")
    print("Leaders:", ", ".join(f"{c['symbol'][:-4]} {c['ret_7d']:+.0f}%" for c in r["leaders"][:8]))
    sys.exit(0 if r["coins_analysed"] else 1)
