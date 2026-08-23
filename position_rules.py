"""
Pure position-management logic, shared by the 30-min scan (trader.py) and the 5-min
monitor (sl_monitor.py). Stdlib-only (datetime), no config import — callers pass the
knobs in — so sl_monitor stays dependency-free and GitHub-runnable.

Every function is pure: dict + numbers in, decision out. Easy to unit test, impossible
to have "worked in the scan but not the monitor" drift.
"""
from datetime import datetime, timezone


def _peak(pos: dict) -> float:
    """Highest price seen for this position. Back-compat: old positions had no peak."""
    return float(pos.get("peak_price", pos["entry_price"]))


def update_trailing_stop(pos: dict, price: float, activate_pct: float,
                         trail_pct: float) -> dict:
    """
    Ratchet the stop upward as price makes new highs. Returns a possibly-updated copy
    of pos with refreshed peak_price / stop_loss / trailing flag. Never lowers a stop.

    Once the position has traded up by activate_pct from entry, the stop follows at
    trail_pct below the peak — so a runner that reverses is exited near its high
    instead of all the way back at the original stop.
    """
    entry = float(pos["entry_price"])
    peak = max(_peak(pos), price)
    new = dict(pos)
    new["peak_price"] = peak

    # Only start trailing once we're comfortably in profit.
    if peak >= entry * (1 + activate_pct):
        trailed = peak * (1 - trail_pct)
        # Never move the stop down, and never above the current price.
        candidate = min(max(float(pos["stop_loss"]), trailed), price)
        if candidate > float(pos["stop_loss"]):
            new["stop_loss"] = round(candidate, 8)
            new["trailing"] = True
    return new


def position_age_hours(pos: dict, now: datetime = None) -> float:
    now = now or datetime.now(timezone.utc)
    opened = pos.get("opened_at")
    if not opened:
        return 0.0
    try:
        dt = datetime.fromisoformat(opened)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    return (now - dt).total_seconds() / 3600


def should_stale_exit(pos: dict, price: float, max_hold_hours: float,
                      now: datetime = None) -> bool:
    """
    Close a position that has overstayed its welcome AND isn't in profit. Winners are
    left alone (the trailing stop manages those) — this only culls dead money that's
    tying up capital a fresh setup could use.
    """
    if position_age_hours(pos, now) < max_hold_hours:
        return False
    return price <= float(pos["entry_price"])


def in_cooldown(last_sl_iso: str, cooldown_hours: float, now: datetime = None) -> bool:
    """True if a stop-loss fired on this symbol within the cooldown window."""
    if not last_sl_iso:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(last_sl_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (now - dt).total_seconds() / 3600 < cooldown_hours
