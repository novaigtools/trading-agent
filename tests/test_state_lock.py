"""
The lock that stops the 30-min scan and the 5-min monitor from clobbering each other.

Without it: the monitor SELLs a position, then a scan that loaded state *before* the
sell saves *after* it — the position resurrects and the cash vanishes. Paper money
today, real money later.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_lock
from state_lock import state_lock as lock_ctx, LockBusy


@pytest.fixture(autouse=True)
def isolated_lock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(state_lock, "LOCK_FILE", str(tmp_path / "logs" / "state.lock"))
    yield
    state_lock.release()


def test_second_holder_is_refused_while_first_holds():
    with lock_ctx(required=True):
        with pytest.raises(LockBusy):
            with lock_ctx(wait_sec=0, required=True):
                pytest.fail("two processes must never hold the state lock at once")


def test_lock_is_released_on_exit():
    with lock_ctx(required=True):
        pass
    with lock_ctx(required=True) as l:   # must be re-acquirable
        assert l.held


def test_lock_is_released_even_if_the_body_raises():
    with pytest.raises(ValueError):
        with lock_ctx(required=True):
            raise ValueError("boom")
    with lock_ctx(required=True) as l:
        assert l.held, "a crash mid-trade must not deadlock the bot forever"


def test_non_required_holder_proceeds_anyway():
    """A scan holding fresh prices must not abandon a trade because the monitor is busy."""
    with lock_ctx(required=True):
        with lock_ctx(wait_sec=0, required=False) as second:
            assert second.held is False   # didn't get it...
        # ...but no exception was raised: the scan proceeds best-effort.


def test_stale_lock_is_broken(monkeypatch):
    """A crashed process must not deadlock the bot forever."""
    state_lock.acquire()
    monkeypatch.setattr(state_lock, "_is_stale", lambda path: True)
    assert state_lock.acquire(wait_sec=0) is True, "a >10min stale lock must be broken"
