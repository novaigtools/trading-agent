import csv
import json
import os
from datetime import datetime, timezone
from config import (
    STARTING_BALANCE, MAX_POSITION_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    PENNY_PAIRS, PENNY_MAX_PCT, PENNY_STOP_LOSS_PCT, PENNY_TAKE_PROFIT_PCT,
    MAX_PENNY_POSITIONS, COOLDOWN_HOURS_AFTER_SL, DAILY_LOSS_LIMIT_PCT,
    CONVICTION_FULL_SCORE, REDUCED_SIZE_FACTOR,
    RISK_PER_TRADE_PCT, WEEKLY_DEPOSIT_USD, DEPOSIT_SCHEDULE_START,
)
from state_lock import state_lock
import position_rules

RISK_STATE_FILE = "risk_state.json"
TRADES_FILE = "trades.csv"

# Dynamic trending symbols for the current scan — set by run_once each run.
# Treated as penny-tier (small size, tight stops) since they are the riskiest names.
_TRENDING: set = set()


def set_trending(symbols):
    """Register this scan's live trending symbols so they get penny-tier risk."""
    global _TRENDING
    _TRENDING = set(symbols or [])


def _default_state() -> dict:
    return {
        "experiment_start": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "starting_balance": STARTING_BALANCE,
        "cash": STARTING_BALANCE,
        "open_positions": {},
    }


def _load_state() -> dict:
    if os.path.exists(RISK_STATE_FILE):
        with open(RISK_STATE_FILE) as f:
            state = json.load(f)
        if "cash" in state:
            return state
        # Migrate legacy weekly-budget schema
        migrated = _default_state()
        migrated["open_positions"] = state.get("open_positions", {})
        held = sum(p["entry_price"] * p["quantity"] for p in migrated["open_positions"].values())
        migrated["cash"] = round(STARTING_BALANCE - held, 2)
        _save_state(migrated)
        return migrated
    return _default_state()


def _save_state(state: dict):
    with open(RISK_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _is_penny(symbol: str) -> bool:
    return symbol in PENNY_PAIRS or symbol in _TRENDING


def _penny_positions_open(state: dict) -> int:
    return sum(1 for s in state.get("open_positions", {}) if _is_penny(s))


def _book_equity(state: dict) -> float:
    """Cash + entry cost of open positions (book value, no live prices needed)."""
    held = sum(p["entry_price"] * p["quantity"] for p in state["open_positions"].values())
    return state["cash"] + held


def get_position_size(price: float, symbol: str = "", confidence: int = None,
                      stop_pct: float = None) -> float:
    # A bad price (0, negative, or NaN) must never divide-by-zero and crash the whole
    # scan — a micro-cap once rounded to 0.0 and took down a run. No price, no trade.
    if not price or price <= 0 or price != price:
        print(f"  Refusing to size {symbol}: invalid price {price!r}")
        return 0.0

    state = _load_state()
    equity = _book_equity(state)

    if _is_penny(symbol):
        if _penny_positions_open(state) >= MAX_PENNY_POSITIONS:
            return 0.0  # Already at max penny exposure
        cap = equity * PENNY_MAX_PCT
    else:
        cap = equity * MAX_POSITION_PCT

    # Risk-based sizing: size so that hitting THIS trade's stop loses ~RISK_PER_TRADE_PCT
    # of equity. Tight-stop (calm) coins get bigger positions, wide-stop (wild) ones
    # smaller — the dollar risk is what's held constant, not the notional. The cap keeps
    # any one name from dominating the book.
    if stop_pct and stop_pct > 0:
        max_trade = min(cap, equity * RISK_PER_TRADE_PCT / stop_pct)
    else:
        max_trade = cap

    # Conviction-scaled sizing: the trade-history autopsy showed score-10 setups made
    # +$14.54 while score-9 barely broke even. Put more capital behind the best signals.
    if confidence is not None and confidence < CONVICTION_FULL_SCORE:
        max_trade *= REDUCED_SIZE_FACTOR

    amount_usd = min(state["cash"], max_trade)
    if amount_usd < 5:
        return 0.0
    return round(amount_usd / price, 6)


def cash_available() -> float:
    return round(_load_state()["cash"], 2)


def _last_sell_for(symbol: str):
    """Most recent SELL row for a symbol from trades.csv, or None. trades.csv is the
    shared source of truth both the scan and the 5-min monitor append to, so cooldown
    logic reads it directly rather than duplicating state across two writers."""
    if not os.path.exists(TRADES_FILE):
        return None
    last = None
    try:
        with open(TRADES_FILE) as f:
            for row in csv.DictReader(f):
                if row.get("symbol") == symbol and row.get("action") == "SELL":
                    last = row
    except (OSError, csv.Error):
        return None
    return last


def in_cooldown(symbol: str, now: datetime = None) -> bool:
    """True if this symbol was stopped/trailed/stale-exited within the cooldown window.
    Stops the revenge-trading the autopsy exposed (TRUMP 1/5, TAO 1/4)."""
    row = _last_sell_for(symbol)
    if not row:
        return False
    reason = (row.get("reason") or "")
    if not any(k in reason for k in ("STOP LOSS", "Trailing stop", "Stale exit")):
        return False   # a take-profit exit is fine to re-enter; only losses cool down
    ts = (row.get("timestamp") or "").strip()
    try:
        iso = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return False
    return position_rules.in_cooldown(iso, COOLDOWN_HOURS_AFTER_SL, now)


def circuit_breaker_tripped(current_prices: dict = None) -> tuple:
    """
    Daily loss circuit breaker. Tracks the day's opening equity; if equity has since
    fallen DAILY_LOSS_LIMIT_PCT below it, block NEW entries for the rest of the UTC day.
    Existing positions keep being managed (stops/TPs still fire). Returns (tripped, msg).
    """
    with state_lock(wait_sec=5, required=False):
        state = _load_state()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        equity = _book_equity(state)
        if current_prices:
            equity = state["cash"] + sum(
                current_prices.get(s, p["entry_price"]) * p["quantity"]
                for s, p in state["open_positions"].items()
            )
        day = state.get("day")
        if not day or day.get("date") != today:
            state["day"] = {"date": today, "open_equity": round(equity, 2)}
            _save_state(state)
            return (False, "")
        open_eq = day.get("open_equity", equity)

    if open_eq <= 0:
        return (False, "")
    drawdown = (open_eq - equity) / open_eq
    if drawdown >= DAILY_LOSS_LIMIT_PCT:
        return (True, f"Daily loss limit hit: equity ${equity:.2f} is {drawdown:.1%} below "
                      f"today's open ${open_eq:.2f} (limit {DAILY_LOSS_LIMIT_PCT:.0%}). "
                      f"No new entries until tomorrow (UTC).")
    return (False, "")


def record_trade(symbol: str, side: str, price: float, quantity: float,
                 stop_loss: float = None, take_profit: float = None, stop_pct: float = None):
    # Load-modify-save must be atomic w.r.t. sl_monitor.py, which writes the same file
    # every 5 minutes. required=False: a scan already holding fresh prices should not
    # abandon a trade just because the monitor is mid-write; it waits, then proceeds.
    with state_lock(wait_sec=10, required=False):
        state = _load_state()
        if side == "BUY":
            cost = price * quantity
            state["cash"] = round(state["cash"] - cost, 4)
            # Honour the volatility-sized stop the brain decided. This used to recompute
            # a fixed % here, silently discarding it — which is what produced stops inside
            # the coin's noise and the sub-hour churn that cost the whole book.
            sl_pct = PENNY_STOP_LOSS_PCT if _is_penny(symbol) else STOP_LOSS_PCT
            tp_pct = PENNY_TAKE_PROFIT_PCT if _is_penny(symbol) else TAKE_PROFIT_PCT
            sl = stop_loss if stop_loss else round(price * (1 - sl_pct), 8)
            tp = take_profit if take_profit else round(price * (1 + tp_pct), 8)
            # Trail at the same distance the stop was sized to, so a volatile coin isn't
            # trailed on a hair-trigger either.
            trail = stop_pct if stop_pct else (price - sl) / price if price else sl_pct
            state["open_positions"][symbol] = {
                "entry_price": price,
                "quantity": quantity,
                "stop_loss": sl,
                "take_profit": tp,
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "is_penny": _is_penny(symbol),
                "peak_price": price,   # seeds the trailing stop's high-water mark
                "trail_pct": round(max(0.01, min(0.08, trail)), 6),
            }
        elif side == "SELL" and symbol in state["open_positions"]:
            # Proceeds go back to cash — realized P&L is captured automatically
            state["cash"] = round(state["cash"] + price * quantity, 4)
            del state["open_positions"][symbol]
        _save_state(state)


def check_stop_loss_take_profit(current_prices: dict) -> list[dict]:
    state = _load_state()
    triggers = []
    for symbol, pos in list(state["open_positions"].items()):
        price = current_prices.get(symbol)
        if price is None:
            continue
        if price <= pos["stop_loss"]:
            triggers.append({"symbol": symbol, "action": "SELL", "reason": "stop_loss", "price": price})
        elif price >= pos["take_profit"]:
            triggers.append({"symbol": symbol, "action": "SELL", "reason": "take_profit", "price": price})
    return triggers


def get_open_positions() -> dict:
    return _load_state().get("open_positions", {})


def _deposits_due(now: datetime) -> int:
    """How many weekly top-ups should have landed by `now` (0 before the schedule starts)."""
    try:
        start = datetime.strptime(DEPOSIT_SCHEDULE_START, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    if now < start:
        return 0
    return (now - start).days // 7 + 1


def apply_weekly_deposits(now: datetime = None, dry_run: bool = False) -> float:
    """
    Credit Amal's weekly paper top-up. Idempotent: tracks deposits_applied in state, so it
    never double-credits (laptop + cloud, or a re-run), and catches up any weeks missed
    while the bot was offline. Returns the amount credited this call (or that WOULD be,
    in dry_run). Deposits raise total_deposited as well as cash, so P&L stays honest.
    """
    now = now or datetime.now(timezone.utc)
    with state_lock(wait_sec=10, required=False):
        state = _load_state()
        state.setdefault("total_deposited", state.get("starting_balance", STARTING_BALANCE))
        state.setdefault("deposits_applied", 0)
        state.setdefault("deposits", [])
        owed = _deposits_due(now) - state["deposits_applied"]
        if owed <= 0:
            return 0.0
        amount = round(owed * WEEKLY_DEPOSIT_USD, 2)
        if dry_run:
            return amount
        state["cash"] = round(state["cash"] + amount, 4)
        state["total_deposited"] = round(state["total_deposited"] + amount, 2)
        state["deposits_applied"] += owed
        state["deposits"].append({"date": now.strftime("%Y-%m-%d"), "amount": amount})
        # A deposit is not a gain: lift today's circuit-breaker baseline too, or the
        # breaker would read the fresh cash as profit and mask a real drawdown.
        day = state.get("day")
        if day and day.get("date") == now.strftime("%Y-%m-%d"):
            day["open_equity"] = round(day.get("open_equity", 0) + amount, 2)
        _save_state(state)
    return amount


def account_summary(current_prices: dict = None) -> dict:
    """Snapshot of the paper account. Pass live prices for mark-to-market equity."""
    state = _load_state()
    positions = state["open_positions"]
    held_book = sum(p["entry_price"] * p["quantity"] for p in positions.values())

    if current_prices:
        held_market = sum(
            current_prices.get(s, p["entry_price"]) * p["quantity"]
            for s, p in positions.items()
        )
    else:
        held_market = held_book

    equity = round(state["cash"] + held_market, 2)
    # P&L is measured against every dollar Amal has put in (initial + weekly top-ups), so a
    # deposit never shows up as profit.
    invested = state.get("total_deposited", state["starting_balance"]) or state["starting_balance"]
    return {
        "experiment_start": state["experiment_start"],
        "starting_balance": state["starting_balance"],
        "total_deposited": round(invested, 2),
        "cash": round(state["cash"], 2),
        "positions_value": round(held_market, 2),
        "equity": equity,
        "total_pnl": round(equity - invested, 2),
        "total_pnl_pct": round((equity - invested) / invested * 100, 2),
        "open_positions": len(positions),
    }
