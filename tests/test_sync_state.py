"""
sync_state: decides whose bot state is the truth before each run.

These build real throwaway git repos (a bare "GitHub", a "laptop" clone and a "cloud"
clone) and replay the scenarios, because a real git conflict is what broke: on Oct 2-3
2026 the cloud rewrote only circuit-breaker bookkeeping while the laptop slept, the
laptop's `pull --rebase` then halted on every run, and the two machines traded separate
books (the laptop sold AAVE; the cloud kept "holding" it).
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_state


def run(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write_state(repo, cash, positions, day="2026-10-01", trades=()):
    st = {"experiment_start": "2026-07-15", "starting_balance": 500.0, "cash": cash,
          "open_positions": {s: {"entry_price": 1.0, "quantity": 1.0} for s in positions},
          "day": {"date": day, "open_equity": 555.0}}
    with open(os.path.join(repo, "risk_state.json"), "w", newline="\n") as f:
        json.dump(st, f, indent=2)
    with open(os.path.join(repo, "trades.csv"), "w", newline="\n") as f:
        f.write("timestamp,symbol,action,price,quantity,value_usd,reason,confidence,trade_type,mode\n")
        for t in trades:
            f.write(t + "\n")


def commit(repo, msg):
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", msg)


def state(repo):
    return json.load(open(os.path.join(repo, "risk_state.json")))


BASE_TRADES = ["2026-10-01 10:00:00,AAVEUSDT,BUY,170,0.3,51,RULES,9,intraday,PAPER"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """origin (bare) <- laptop, cloud. Shared base: holding AAVE."""
    origin, laptop, cloud = (str(tmp_path / n) for n in ("origin.git", "laptop", "cloud"))
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", origin], check=True)
    for clone in (laptop, cloud):
        subprocess.run(["git", "clone", "-q", origin, clone], check=True, capture_output=True)
        run(clone, "config", "user.email", "t@t"); run(clone, "config", "user.name", "t")
    with open(os.path.join(laptop, ".gitattributes"), "w") as f:
        f.write("risk_state.json -merge\nheartbeat.json -merge\ntrades.csv merge=union\n")
    with open(os.path.join(laptop, "bot.py"), "w") as f:
        f.write("# code\n")
    write_state(laptop, 497.21, ["AAVEUSDT"], trades=BASE_TRADES)
    commit(laptop, "base"); run(laptop, "push", "-q", "origin", "HEAD:main")
    run(laptop, "branch", "-q", "--set-upstream-to=origin/main")
    run(cloud, "pull", "-q", "origin", "main")
    monkeypatch.setattr(sync_state, "REPO", laptop)
    return origin, laptop, cloud


def cloud_bookkeeping(cloud):
    """What every cloud scan does while the laptop sleeps: rewrite the `day` field only."""
    write_state(cloud, 497.21, ["AAVEUSDT"], day="2026-10-02", trades=BASE_TRADES)
    commit(cloud, "Cloud scan state update"); run(cloud, "push", "-q", "origin", "HEAD:main")


def laptop_sells_aave(laptop):
    write_state(laptop, 559.23, [], day="2026-10-02", trades=BASE_TRADES + [
        "2026-10-02 09:37:00,AAVEUSDT,SELL,182.75,0.3,54.8,Automated TAKE PROFIT triggered,10,intraday,PAPER"])
    commit(laptop, "Bot state update (monitor)")


def is_fast_forward_of_origin(laptop):
    return run(laptop, "merge-base", "HEAD", "origin/main") == run(laptop, "rev-parse", "origin/main")


# ---- decision table ----

@pytest.mark.parametrize("ahead,behind,traded,expected", [
    (0, 0, False, "keep_local"),
    (3, 0, False, "keep_local"),
    (0, 2, True, "fast_forward"),
    (5, 2, False, "keep_local_on_origin"),   # the Oct 2-3 case
    (5, 2, True, "adopt_origin"),
])
def test_decide(ahead, behind, traded, expected):
    assert sync_state.decide(ahead, behind, traded) == expected


# ---- real-git scenarios ----

def test_the_oct_2_split_brain_is_resolved_in_the_laptops_favour(world):
    """Cloud only rewrote bookkeeping; laptop sold AAVE. Laptop must win, and the result
    must be a clean fast-forward of origin so the next push cannot conflict."""
    origin, laptop, cloud = world
    cloud_bookkeeping(cloud)
    laptop_sells_aave(laptop)
    assert sync_state.sync(log=lambda *_: None) == 0
    st = state(laptop)
    assert st["cash"] == 559.23 and st["open_positions"] == {}   # AAVE sale kept
    assert is_fast_forward_of_origin(laptop)
    run(laptop, "push", "-q", "origin", "HEAD:main")              # would have failed before
    assert not os.path.isdir(os.path.join(laptop, ".git", "rebase-merge"))


def test_when_the_cloud_traded_github_wins_and_laptop_rows_are_dropped(world):
    """Both sides traded: GitHub is the meeting point, so adopt it rather than risk
    double-selling the same position."""
    origin, laptop, cloud = world
    write_state(cloud, 553.0, [], day="2026-10-02", trades=BASE_TRADES + [
        "2026-10-02 08:00:00,AAVEUSDT,SELL,183,0.3,54.9,Automated TAKE PROFIT triggered,10,intraday,PAPER"])
    commit(cloud, "SL/TP triggered"); run(cloud, "push", "-q", "origin", "HEAD:main")
    laptop_sells_aave(laptop)
    logs = []
    assert sync_state.sync(log=logs.append) == 0
    assert state(laptop)["cash"] == 553.0
    assert run(laptop, "rev-parse", "HEAD") == run(laptop, "rev-parse", "origin/main")
    assert any("dropped 1 laptop trade" in l for l in logs)


def test_laptop_only_ahead_is_left_alone(world):
    origin, laptop, cloud = world
    laptop_sells_aave(laptop)
    head = run(laptop, "rev-parse", "HEAD")
    assert sync_state.sync(log=lambda *_: None) == 0
    assert run(laptop, "rev-parse", "HEAD") == head


def test_laptop_behind_fast_forwards(world):
    origin, laptop, cloud = world
    cloud_bookkeeping(cloud)
    assert sync_state.sync(log=lambda *_: None) == 0
    assert state(laptop)["day"]["date"] == "2026-10-02"


def test_loose_uncommitted_state_is_banked_not_lost(world):
    """The monitor often leaves state edits uncommitted (e.g. a sale just before sleep)."""
    origin, laptop, cloud = world
    cloud_bookkeeping(cloud)
    write_state(laptop, 559.23, [], day="2026-10-02", trades=BASE_TRADES)   # not committed
    assert sync_state.sync(log=lambda *_: None) == 0
    assert state(laptop)["cash"] == 559.23
    assert is_fast_forward_of_origin(laptop)


def test_refuses_to_reset_over_unpushed_code(world):
    origin, laptop, cloud = world
    cloud_bookkeeping(cloud)
    with open(os.path.join(laptop, "bot.py"), "a") as f:
        f.write("# important work\n")
    commit(laptop, "code change")
    head = run(laptop, "rev-parse", "HEAD")
    assert sync_state.sync(log=lambda *_: None) == 2
    assert run(laptop, "rev-parse", "HEAD") == head


def test_refuses_with_uncommitted_code(world):
    origin, laptop, cloud = world
    with open(os.path.join(laptop, "bot.py"), "a") as f:
        f.write("# wip\n")
    assert sync_state.sync(log=lambda *_: None) == 2
    assert "wip" in open(os.path.join(laptop, "bot.py")).read()
