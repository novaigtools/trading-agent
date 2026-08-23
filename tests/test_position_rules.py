"""
Tests for the adaptive risk controls added from the trade-history autopsy:
trailing stops, stale exits, and cooldowns.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import position_rules as pr


def _pos(entry=100.0, stop=98.0, tp=106.0, peak=None, opened=None):
    p = {"entry_price": entry, "stop_loss": stop, "take_profit": tp,
         "quantity": 1.0, "opened_at": opened or datetime.now(timezone.utc).isoformat()}
    if peak is not None:
        p["peak_price"] = peak
    return p


# ---- Trailing stop ---------------------------------------------------------

def test_trailing_does_not_engage_below_activation():
    """Under +3%, the stop stays put — we don't choke a trade that's barely green."""
    pos = _pos(entry=100.0, stop=98.0)
    out = pr.update_trailing_stop(pos, price=102.0, activate_pct=0.03, trail_pct=0.02)
    assert out["stop_loss"] == 98.0
    assert not out.get("trailing")


def test_trailing_engages_and_locks_gains():
    """At +5%, stop trails 2% below the peak — now ABOVE entry, locking a profit."""
    pos = _pos(entry=100.0, stop=98.0)
    out = pr.update_trailing_stop(pos, price=105.0, activate_pct=0.03, trail_pct=0.02)
    assert out["trailing"] is True
    assert round(out["stop_loss"], 4) == 102.9    # 105 * 0.98, above entry
    assert out["stop_loss"] > pos["entry_price"]  # a winner can't become a loser now


def test_trailing_never_lowers_the_stop():
    """Price pulls back — the ratcheted stop must not drop with it."""
    pos = _pos(entry=100.0, stop=102.9, peak=105.0)
    pos["trailing"] = True
    out = pr.update_trailing_stop(pos, price=103.0, activate_pct=0.03, trail_pct=0.02)
    assert out["stop_loss"] == 102.9   # unchanged, not lowered to 103*0.98


def test_trailing_tracks_new_highs():
    pos = _pos(entry=100.0, stop=98.0, peak=105.0)
    out = pr.update_trailing_stop(pos, price=110.0, activate_pct=0.03, trail_pct=0.02)
    assert out["peak_price"] == 110.0
    assert out["stop_loss"] == 110.0 * 0.98


# ---- Stale exit ------------------------------------------------------------

def test_stale_exit_fires_on_old_flat_position():
    old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    pos = _pos(entry=100.0, opened=old)
    assert pr.should_stale_exit(pos, price=99.0, max_hold_hours=48) is True


def test_stale_exit_spares_a_winner():
    """An old position that's in profit is left for the trailing stop, not culled."""
    old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    pos = _pos(entry=100.0, opened=old)
    assert pr.should_stale_exit(pos, price=104.0, max_hold_hours=48) is False


def test_stale_exit_spares_a_young_position():
    young = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    pos = _pos(entry=100.0, opened=young)
    assert pr.should_stale_exit(pos, price=95.0, max_hold_hours=48) is False


# ---- Cooldown --------------------------------------------------------------

def test_cooldown_active_right_after_a_stop():
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert pr.in_cooldown(recent, cooldown_hours=12) is True


def test_cooldown_expired():
    old = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    assert pr.in_cooldown(old, cooldown_hours=12) is False


def test_cooldown_ignores_missing_timestamp():
    assert pr.in_cooldown("", cooldown_hours=12) is False
