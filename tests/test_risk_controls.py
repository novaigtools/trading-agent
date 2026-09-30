"""
Integration tests for the entry-side risk controls in risk_manager:
cooldown-from-trades.csv, the daily circuit breaker, and conviction-scaled sizing.
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import risk_manager as rm


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rm, "RISK_STATE_FILE", str(tmp_path / "risk_state.json"))
    monkeypatch.setattr(rm, "TRADES_FILE", str(tmp_path / "trades.csv"))
    rm._save_state({"experiment_start": "2026-08-01", "starting_balance": 500.0,
                    "cash": 500.0, "open_positions": {}})
    return tmp_path


def _write_trades(path, rows):
    with open(path, "w") as f:
        f.write("timestamp,symbol,action,price,quantity,value_usd,reason,confidence,trade_type,mode\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")


def test_cooldown_blocks_after_recent_stop_loss(sandbox):
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    _write_trades(sandbox / "trades.csv", [
        [recent, "TRUMPUSDT", "SELL", 1.5, 20, 30, "Automated STOP LOSS triggered", 10, "intraday", "PAPER"],
    ])
    assert rm.in_cooldown("TRUMPUSDT") is True


def test_no_cooldown_after_a_take_profit(sandbox):
    """A winning exit is not a reason to avoid a coin — only losses cool down."""
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    _write_trades(sandbox / "trades.csv", [
        [recent, "SUIUSDT", "SELL", 0.9, 80, 72, "Automated TAKE PROFIT triggered", 10, "intraday", "PAPER"],
    ])
    assert rm.in_cooldown("SUIUSDT") is False


def test_cooldown_expires(sandbox):
    # Cooldown is 24h (raised from 12h after SOPH re-entered and lost repeatedly).
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
    _write_trades(sandbox / "trades.csv", [
        [old, "TAOUSDT", "SELL", 200, 0.3, 60, "Automated STOP LOSS triggered", 10, "intraday", "PAPER"],
    ])
    assert rm.in_cooldown("TAOUSDT") is False


def test_circuit_breaker_sets_day_baseline_first_call(sandbox):
    tripped, _ = rm.circuit_breaker_tripped()
    assert tripped is False
    state = rm._load_state()
    assert "day" in state and state["day"]["open_equity"] == 500.0


def test_circuit_breaker_trips_after_big_daily_drawdown(sandbox):
    rm.circuit_breaker_tripped()                     # sets today's open equity = 500
    st = rm._load_state()
    st["cash"] = 470.0                               # -6% on the day (limit is 5%)
    rm._save_state(st)
    tripped, msg = rm.circuit_breaker_tripped()
    assert tripped is True
    assert "Daily loss limit" in msg


def test_circuit_breaker_stays_open_on_small_dip(sandbox):
    rm.circuit_breaker_tripped()
    st = rm._load_state()
    st["cash"] = 490.0                               # -2%, within tolerance
    rm._save_state(st)
    tripped, _ = rm.circuit_breaker_tripped()
    assert tripped is False


def test_conviction_sizing_reduces_below_full_score(sandbox):
    full = rm.get_position_size(100.0, "SOLUSDT", confidence=10)
    reduced = rm.get_position_size(100.0, "SOLUSDT", confidence=8)
    assert reduced < full
    assert reduced == pytest.approx(full * 0.7, rel=1e-3)


def test_sizing_without_confidence_is_full(sandbox):
    full = rm.get_position_size(100.0, "SOLUSDT", confidence=10)
    default = rm.get_position_size(100.0, "SOLUSDT")
    assert default == pytest.approx(full, rel=1e-3)


def test_record_trade_honours_the_brains_stop(sandbox):
    """risk_manager used to recompute a fixed stop here, silently discarding the
    volatility-sized one — the root cause of the sub-hour churn."""
    rm.record_trade("SOLUSDT", "BUY", 100.0, 1.0,
                    stop_loss=95.0, take_profit=115.0, stop_pct=0.05)
    pos = rm._load_state()["open_positions"]["SOLUSDT"]
    assert pos["stop_loss"] == 95.0
    assert pos["take_profit"] == 115.0
    assert pos["trail_pct"] == 0.05


def test_record_trade_falls_back_when_no_stop_given(sandbox):
    rm.record_trade("SOLUSDT", "BUY", 100.0, 1.0)
    pos = rm._load_state()["open_positions"]["SOLUSDT"]
    assert pos["stop_loss"] < 100.0 and pos["take_profit"] > 100.0


# ---- full-capital, risk-based sizing (2026-09-30) ----

def test_tight_stop_gets_a_bigger_position_than_a_wide_stop(sandbox):
    """Risk-based sizing holds the dollar risk constant: a calm coin with a tight stop
    gets more notional than a twitchy coin with a wide stop."""
    calm = rm.get_position_size(100.0, "SOLUSDT", 10, stop_pct=0.02)
    wild = rm.get_position_size(100.0, "SOLUSDT", 10, stop_pct=0.06)
    assert calm > wild


def test_risk_per_trade_is_bounded(sandbox):
    """With a 6% stop, notional = 1.5%/6% = 25% of equity, so hitting the stop costs
    ~1.5% of the account."""
    from config import RISK_PER_TRADE_PCT
    qty = rm.get_position_size(100.0, "SOLUSDT", 10, stop_pct=0.06)
    notional = qty * 100.0
    assert notional * 0.06 == pytest.approx(500.0 * RISK_PER_TRADE_PCT, rel=1e-3)


def test_position_cap_still_applies(sandbox):
    """A very tight stop must not balloon one position past the per-name cap."""
    from config import MAX_POSITION_PCT
    qty = rm.get_position_size(100.0, "SOLUSDT", 10, stop_pct=0.005)
    assert qty * 100.0 == pytest.approx(500.0 * MAX_POSITION_PCT, rel=1e-3)


def test_book_can_reach_near_full_deployment(sandbox):
    """The whole point: 4-5 normal positions should put most of the money to work.
    Old flat 15% sizing capped a full book at ~60%."""
    per = rm.get_position_size(100.0, "SOLUSDT", 10, stop_pct=0.05) * 100.0
    assert per * 4 >= 500.0 * 0.55 and per * 5 >= 500.0 * 0.7


# ---- weekly deposits ----

def _at(d):
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def test_no_deposit_before_schedule_starts(sandbox, monkeypatch):
    monkeypatch.setattr(rm, "DEPOSIT_SCHEDULE_START", "2026-10-05")
    assert rm.apply_weekly_deposits(_at("2026-10-01")) == 0.0
    assert rm._load_state()["cash"] == 500.0


def test_deposit_lands_and_is_not_counted_as_profit(sandbox, monkeypatch):
    monkeypatch.setattr(rm, "DEPOSIT_SCHEDULE_START", "2026-10-05")
    assert rm.apply_weekly_deposits(_at("2026-10-05")) == 500.0
    st = rm._load_state()
    assert st["cash"] == 1000.0 and st["total_deposited"] == 1000.0
    s = rm.account_summary()
    assert s["total_pnl"] == 0.0          # $500 in, $500 more in, nothing earned yet


def test_deposit_is_idempotent_and_catches_up(sandbox, monkeypatch):
    """Never double-credits the same week (laptop + cloud, re-runs); a laptop that was off
    for two weeks gets both top-ups on its next scan."""
    monkeypatch.setattr(rm, "DEPOSIT_SCHEDULE_START", "2026-10-05")
    rm.apply_weekly_deposits(_at("2026-10-05"))
    assert rm.apply_weekly_deposits(_at("2026-10-06")) == 0.0      # same week again
    assert rm.apply_weekly_deposits(_at("2026-10-20")) == 1000.0   # 10-12 and 10-19 missed
    assert rm._load_state()["total_deposited"] == 2000.0


def test_dry_run_deposit_writes_nothing(sandbox, monkeypatch):
    monkeypatch.setattr(rm, "DEPOSIT_SCHEDULE_START", "2026-10-05")
    assert rm.apply_weekly_deposits(_at("2026-10-05"), dry_run=True) == 500.0
    assert rm._load_state()["cash"] == 500.0


def test_deposit_does_not_mask_a_drawdown_in_the_circuit_breaker(sandbox, monkeypatch):
    """A same-day deposit must lift the breaker's baseline too, or fresh cash would read
    as a recovery and hide a real loss."""
    monkeypatch.setattr(rm, "DEPOSIT_SCHEDULE_START", "2026-10-05")
    st = rm._load_state(); st["day"] = {"date": "2026-10-05", "open_equity": 500.0}; rm._save_state(st)
    rm.apply_weekly_deposits(_at("2026-10-05"))
    assert rm._load_state()["day"]["open_equity"] == 1000.0
