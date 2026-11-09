"""
practice_book.py - the "practice account": pretend trades on setups the real bot passes on.

Why this exists
---------------
The real account only buys 8/10 setups in a non-falling market, so it can go 10+ days
without a single trade - and you can't tune rules from one trade a fortnight. Loosening
the real account to get more data would muddy the one clean result we care about
("is this strategy profitable?"). So every scan, this module also takes PRETEND trades on
what the real bot rejected, sorted into cohorts:

    gate:bear      scored 8+ but blocked because the BTC regime was BEAR
    gate:btc_down  scored 8+ but blocked because BTC was down over 24h (NEUTRAL regime)
    gate:other     scored 8+ but not bought (positions full, cooldown, sizing...)
    score:7 / score:6 / score:5   below the buy bar

Each practice trade uses the real bot's exact exit rules (ATR stop, 2R target, trailing
stop, 48h stale exit), checked candle-by-candle on 15m data, with a fixed $100 stake so
cohorts compare like for like. After a few weeks the cohorts answer: is the 8/10 bar too
strict? Does the BEAR / BTC-down filter save money or cost it?

It NEVER touches risk_state.json or trades.csv, and any error here is caught by the
caller - practice must never break real trading.
"""
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import requests

import local_brain
import position_rules
from config import (BINANCE_BASE_URL, PENNY_PAIRS, MIN_BUY_CONFIDENCE, TRAIL_ACTIVATE_PCT,
                    MAX_HOLD_HOURS, COOLDOWN_HOURS_AFTER_SL)

REPO = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(REPO, "practice_state.json")
TRADES_FILE = os.path.join(REPO, "practice_trades.csv")
STAKE_USD = 100.0
MIN_SCORE = 5          # below this is noise, not a near-miss
MAX_OPEN = 60          # keeps each scan's exit check cheap
FIELDS = ["opened_utc", "closed_utc", "symbol", "cohort", "score", "regime", "btc_24h",
          "entry", "exit", "stop_pct", "tp_pct", "pnl_pct", "pnl_usd", "outcome",
          "hours_held", "signals"]


# ---- storage ---------------------------------------------------------------------

def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    st.setdefault("started_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    st.setdefault("open", {})
    st.setdefault("last_closed", {})
    return st


def save_state(st: dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE_FILE)


def append_trades(rows: list):
    if not rows:
        return
    new = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


# ---- entries ---------------------------------------------------------------------

def cohort_for(score: int, regime: dict, real_bought: bool) -> str | None:
    """Which question this near-miss helps answer. None = not a practice trade."""
    if real_bought or score < MIN_SCORE:
        return None
    if score >= MIN_BUY_CONFIDENCE:
        reg = regime.get("regime")
        btc = regime.get("btc_change_24h")
        if reg == "BEAR":
            return "gate:bear"
        if reg == "NEUTRAL" and btc is not None and btc <= 0:
            return "gate:btc_down"
        return "gate:other"
    return f"score:{score}"


def _ungated_regime(regime: dict) -> dict:
    """Score every coin as if the regime gates were off, so we learn what they cost.
    BEAR becomes NEUTRAL (which still demands 2 independent signals); the BTC-down
    gate is removed by dropping btc_change_24h."""
    r = {k: v for k, v in regime.items() if k != "btc_change_24h"}
    if r.get("regime") == "BEAR":
        r["regime"] = "NEUTRAL"
    return r


def plan_entries(st, market_data_list, sentiment, regime, extra_pairs, real_bought, now):
    """Pure-ish: returns new practice positions to open (does not mutate st)."""
    ungated = _ungated_regime(regime)
    trending = set(extra_pairs or [])
    out = {}
    for md in market_data_list:
        sym = md.get("symbol")
        if not sym or "error" in md or not md.get("price"):
            continue
        if sym in st["open"] or sym in out:
            continue
        last = st["last_closed"].get(sym)
        if position_rules.in_cooldown(last, COOLDOWN_HOURS_AFTER_SL, now):
            continue
        d = local_brain.score_symbol(md, sentiment, ungated, trending, {})
        score = int(d.get("confidence") or 0)
        cohort = cohort_for(score, regime, sym in real_bought)
        if not cohort:
            continue
        price = float(md["price"])
        i1h, i15 = md.get("indicators_1h", {}), md.get("indicators_15m", {})
        atr = i1h.get("atr_pct") or i15.get("atr_pct") or 0
        momentum = "MOMENTUM OVERRIDE" in d.get("reasoning", "")
        is_penny = sym in PENNY_PAIRS or sym in trending
        stop_pct, tp_pct, _ = local_brain.stop_and_target(price, atr, is_penny, momentum)
        signals = d.get("reasoning", "").replace("RULES: ", "").split(". Score")[0]
        out[sym] = {
            "entry_price": price, "stop_loss": price * (1 - stop_pct),
            "take_profit": price * (1 + tp_pct), "peak_price": price,
            "trail_pct": max(0.01, min(0.08, stop_pct)), "stop_pct": round(stop_pct, 4),
            "tp_pct": round(tp_pct, 4), "opened_at": now.isoformat(timespec="seconds"),
            "checked_ms": int(now.timestamp() * 1000), "cohort": cohort, "score": score,
            "regime": regime.get("regime", "?"), "btc_24h": regime.get("btc_change_24h"),
            "signals": signals[:240],
        }
    room = max(0, MAX_OPEN - len(st["open"]))
    best = sorted(out.items(), key=lambda kv: -kv[1]["score"])[:room]
    return dict(best)


# ---- exits -----------------------------------------------------------------------

def _candles_since(symbol, start_ms):
    r = requests.get(f"{BINANCE_BASE_URL}/api/v3/klines",
                     params={"symbol": symbol, "interval": "15m", "startTime": start_ms,
                             "limit": 1000}, timeout=15)
    r.raise_for_status()
    # [open_time, open, high, low, close, ...]; drop the still-forming candle
    rows = r.json()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]))
            for k in rows if int(k[0]) + 15 * 60_000 <= now_ms]


def walk_exit(pos: dict, candles: list):
    """Replay 15m candles against the real exit rules. Returns (exit_price, outcome,
    exit_time_ms, updated_pos). exit_price None = still open. Within one candle the stop
    is checked before the target (conservative: we can't see the intra-candle order)."""
    pos = dict(pos)
    opened_ms = int(datetime.fromisoformat(pos["opened_at"]).timestamp() * 1000)
    for t, o, h, l, c in candles:
        if t < opened_ms:
            continue
        if l <= pos["stop_loss"]:
            px = min(o, pos["stop_loss"])
            return px, ("TRAIL" if pos.get("trailing") else "STOP"), t + 15 * 60_000, pos
        if h >= pos["take_profit"]:
            return max(o, pos["take_profit"]), "TARGET", t + 15 * 60_000, pos
        pos = position_rules.update_trailing_stop(pos, h, TRAIL_ACTIVATE_PCT, pos["trail_pct"])
        if (t + 15 * 60_000 - opened_ms) / 3_600_000 >= MAX_HOLD_HOURS and c <= pos["entry_price"]:
            return c, "STALE", t + 15 * 60_000, pos
        pos["checked_ms"] = t + 15 * 60_000
    return None, None, None, pos


def _close_row(sym, pos, px, outcome, t_ms):
    pnl_pct = (px / pos["entry_price"] - 1) * 100
    closed = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
    opened = datetime.fromisoformat(pos["opened_at"])
    return {
        "opened_utc": pos["opened_at"][:16].replace("T", " "),
        "closed_utc": closed.isoformat(timespec="minutes")[:16].replace("T", " "),
        "symbol": sym, "cohort": pos["cohort"], "score": pos["score"],
        "regime": pos["regime"], "btc_24h": pos.get("btc_24h"),
        "entry": f"{pos['entry_price']:.8g}", "exit": f"{px:.8g}",
        "stop_pct": pos["stop_pct"], "tp_pct": pos["tp_pct"],
        "pnl_pct": round(pnl_pct, 3), "pnl_usd": round(STAKE_USD * pnl_pct / 100, 2),
        "outcome": outcome, "hours_held": round((closed - opened).total_seconds() / 3600, 1),
        "signals": pos.get("signals", ""),
    }


def check_exits(st, fetch=_candles_since):
    closed = []
    items = list(st["open"].items())

    def one(kv):
        sym, pos = kv
        try:
            return sym, walk_exit(pos, fetch(sym, pos["checked_ms"] - 15 * 60_000))
        except Exception as e:
            return sym, e
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, items))
    for sym, res in results:
        if isinstance(res, Exception):
            continue   # try again next scan; candles are replayed from checked_ms
        px, outcome, t_ms, pos = res
        if px is None:
            st["open"][sym] = pos
        else:
            closed.append(_close_row(sym, pos, px, outcome, t_ms))
            del st["open"][sym]
            st["last_closed"][sym] = datetime.fromtimestamp(t_ms / 1000, timezone.utc).isoformat()
    return closed


# ---- entry point -----------------------------------------------------------------

def run(market_data_list, sentiment, regime, extra_pairs, real_bought, dry=False, log=print):
    now = datetime.now(timezone.utc)
    st = load_state()
    closed = check_exits(st)
    new = plan_entries(st, market_data_list, sentiment or {}, regime or {}, extra_pairs,
                       set(real_bought or ()), now)
    st["open"].update(new)
    # Forget cooldowns older than a week so the file doesn't grow forever.
    cutoff = now - timedelta(days=7)
    st["last_closed"] = {s: t for s, t in st["last_closed"].items()
                         if datetime.fromisoformat(t) > cutoff}
    wins = sum(1 for r in closed if r["pnl_pct"] > 0)
    opened = ", ".join(s[:-4] + ":" + p["cohort"] for s, p in list(new.items())[:6])
    more = "..." if len(new) > 6 else ""
    pnl = sum(r["pnl_usd"] for r in closed)
    log(f"  PRACTICE: closed {len(closed)} ({wins} wins, {pnl:+.2f} on $100 stakes) | "
        f"opened {len(new)} [{opened}{more}] | open now {len(st['open'])}")
    if not dry:
        append_trades(closed)
        save_state(st)
    return closed, new
