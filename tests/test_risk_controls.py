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
    old = (datetime.now(timezone.utc) - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
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
