"""
practice_book: pretend trades on setups the real bot passed on. Must sort near-misses
into the right cohort, exit by the real bot's rules, and never touch the real account.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import practice_book as pb
from tests.test_local_brain import make_market_data, sentiment

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
MS = lambda dt: int(dt.timestamp() * 1000)


@pytest.mark.parametrize("score,regime,bought,expected", [
    (9, {"regime": "BEAR"}, False, "gate:bear"),
    (8, {"regime": "NEUTRAL", "btc_change_24h": -0.3}, False, "gate:btc_down"),
    (8, {"regime": "NEUTRAL", "btc_change_24h": 0.4}, False, "gate:other"),
    (10, {"regime": "BULL"}, False, "gate:other"),
    (7, {"regime": "BEAR"}, False, "score:7"),
    (5, {"regime": "BULL"}, False, "score:5"),
    (4, {"regime": "BULL"}, False, None),          # noise, not a near-miss
    (9, {"regime": "BULL"}, True, None),           # the real bot took it
])
def test_cohorts(score, regime, bought, expected):
    assert pb.cohort_for(score, regime, bought) == expected


def pos(entry=100.0, stop=0.03, tp=0.06, opened=NOW):
    return {"entry_price": entry, "stop_loss": entry * (1 - stop), "take_profit": entry * (1 + tp),
            "peak_price": entry, "trail_pct": stop, "stop_pct": stop, "tp_pct": tp,
            "opened_at": opened.isoformat(), "checked_ms": MS(opened), "cohort": "score:7",
            "score": 7, "regime": "BEAR", "btc_24h": -1.0, "signals": "x"}


def candles(*hlc, start=NOW):
    """(high, low, close) per 15m candle; open = previous close."""
    out, prev = [], hlc[0][2]
    for i, (h, l, c) in enumerate(hlc):
        out.append((MS(start + timedelta(minutes=15 * i)), prev, h, l, c))
        prev = c
    return out


def test_stop_hit():
    px, why, _, _ = pb.walk_exit(pos(), candles((101, 99, 100), (100, 96.5, 97)))
    assert why == "STOP" and px == pytest.approx(97.0)


def test_target_hit():
    px, why, _, _ = pb.walk_exit(pos(), candles((103, 99.5, 102), (106.5, 101, 106)))
    assert why == "TARGET" and px == pytest.approx(106.0)


def test_stop_checked_before_target_in_same_candle():
    """We can't see the order inside one candle, so assume the worst."""
    _, why, _, _ = pb.walk_exit(pos(), candles((107, 96, 100)))
    assert why == "STOP"


def test_trailing_stop_locks_gains():
    # +5% (trail activates at +3%), trail 3% below the 105 peak = 101.85, then reverses
    px, why, _, _ = pb.walk_exit(pos(), candles((105, 100, 104.5), (104, 101.5, 101.6)))
    assert why == "TRAIL" and px == pytest.approx(101.85)
    assert px > 100


def test_stale_exit_after_48h_when_not_in_profit():
    flat = [(100.5, 99.5, 99.9)] * (48 * 4)
    px, why, _, _ = pb.walk_exit(pos(), candles(*flat))
    assert why == "STALE" and px == pytest.approx(99.9)


def test_still_open_advances_checkpoint():
    p = pos()
    px, why, _, newp = pb.walk_exit(p, candles((101, 99.5, 100.5), (101, 99.6, 100.2)))
    assert px is None and newp["checked_ms"] == MS(NOW + timedelta(minutes=30))


def test_bear_market_near_miss_becomes_a_gate_bear_practice_trade():
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)   # scores 9+
    st = {"open": {}, "last_closed": {}}
    new = pb.plan_entries(st, [md], sentiment(), {"regime": "BEAR"}, [], set(), NOW)
    (sym, p), = new.items()
    assert p["cohort"] == "gate:bear" and p["score"] >= 8
    assert p["stop_loss"] < p["entry_price"] < p["take_profit"]


def test_coins_the_real_bot_holds_or_bought_are_skipped():
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)
    st = {"open": {}, "last_closed": {}}
    assert pb.plan_entries(st, [md], sentiment(), {"regime": "BEAR"}, [], {md["symbol"]}, NOW) == {}


def test_cooldown_after_a_practice_exit():
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)
    st = {"open": {}, "last_closed": {md["symbol"]: (NOW - timedelta(hours=2)).isoformat()}}
    assert pb.plan_entries(st, [md], sentiment(), {"regime": "BEAR"}, [], set(), NOW) == {}


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "STATE_FILE", str(tmp_path / "ps.json"))
    monkeypatch.setattr(pb, "TRADES_FILE", str(tmp_path / "pt.csv"))
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)
    pb.run([md], sentiment(), {"regime": "BEAR"}, [], set(), dry=True, log=lambda *_: None)
    assert not os.listdir(tmp_path)


def test_real_run_persists_and_closes_into_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "STATE_FILE", str(tmp_path / "ps.json"))
    monkeypatch.setattr(pb, "TRADES_FILE", str(tmp_path / "pt.csv"))
    md = make_market_data(rsi_1h=22.0, vol_latest=5000.0, vol_avg=1000.0)
    pb.run([md], sentiment(), {"regime": "BEAR"}, [], set(), log=lambda *_: None)
    st = pb.load_state()
    (sym, p), = st["open"].items()
    # next scan: price crashed through the stop
    crash = lambda s, start: [(MS(datetime.fromisoformat(p["opened_at"])) + 1, p["entry_price"],
                               p["entry_price"], p["stop_loss"] * 0.99, p["stop_loss"] * 0.99)]
    closed = pb.check_exits(st, fetch=crash)
    assert len(closed) == 1 and closed[0]["outcome"] == "STOP" and closed[0]["pnl_usd"] < 0
    assert sym in st["last_closed"] and not st["open"]
