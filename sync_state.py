"""
sync_state.py - reconcile the laptop's bot state with GitHub BEFORE each run.

Why this exists
---------------
The laptop and the cloud backstop both write risk_state.json / trades.csv. When the
laptop sleeps, its heartbeat goes stale and the cloud takes over - and every cloud scan
rewrites at least the circuit-breaker `day` field. When the laptop wakes holding its own
unpushed state, `git pull --rebase` conflicts on that same JSON and halts. .gitattributes
(-merge) stops the files being corrupted, but the halt repeats every run, so the laptop
never pushes again, its heartbeat stays stale, and BOTH machines trade separate books.
That is exactly what happened Oct 2-3 2026: the laptop sold AAVE at its take-profit while
the cloud, never told, kept "holding" it. It recurs on every overnight handoff.

The rule
--------
Decide whose state is the truth before trading, then make the branch a clean
fast-forward of origin so the run's push cannot conflict:

    origin hasn't moved            -> local is truth, nothing to do
    laptop has nothing new         -> fast-forward to origin
    both moved, cloud made trades  -> origin is truth (the cloud was the active writer);
                                      drop the laptop's divergent state commits
    both moved, cloud only did     -> laptop is truth (its trade log is a superset);
    bookkeeping                       rebuild on origin, keep the laptop's state files

Code is never discarded: if anything other than the state files differs or is
uncommitted, sync refuses (exit 2) and the run trades nothing rather than guess.

Exit codes: 0 = synced/proceed (also when offline), 2 = refused, do not trade.
"""
import os
import subprocess
import sys

STATE_FILES = ("risk_state.json", "trades.csv", "heartbeat.json")
REMOTE = "origin/main"
REPO = os.path.dirname(os.path.abspath(__file__))


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    # rstrip only: `status --porcelain` lines start with a significant space (" M file");
    # a full strip() would eat it on the first line and mangle the path.
    return r.stdout.rstrip()


def decide(ahead: int, behind: int, cloud_traded: bool) -> str:
    """Pure decision table (unit-tested)."""
    if behind == 0:
        return "keep_local"
    if ahead == 0:
        return "fast_forward"
    return "adopt_origin" if cloud_traded else "keep_local_on_origin"


def _present():
    """State files that exist on disk. `git add` hard-fails on a missing pathspec, and
    heartbeat.json can legitimately be absent (fresh checkout)."""
    return [f for f in STATE_FILES if os.path.exists(os.path.join(REPO, f))]


def _non_state(paths):
    return [p for p in paths if p and p not in STATE_FILES and not p.startswith("logs/")]


def sync(log=print) -> int:
    # Can't reach GitHub = can't coordinate. Carry on with local state; the cloud will
    # cover via the stale heartbeat, and the next online run reconciles.
    if subprocess.run(["git", "fetch", "-q", "origin"], cwd=REPO,
                      capture_output=True, text=True).returncode != 0:
        log("sync: offline (fetch failed) - running on local state")
        return 0

    # Never reset over work we can't recreate.
    dirty = _non_state(line[3:] for line in git("status", "--porcelain").splitlines())
    if dirty:
        log(f"sync: REFUSED - uncommitted code changes: {dirty}. Not trading this run.")
        return 2

    # Bank any loose state from the previous run so it's part of the comparison.
    if git("status", "--porcelain", "--", *STATE_FILES):
        git("add", "--", *_present())
        git("commit", "-q", "-m", "Local state snapshot before sync")

    ahead = int(git("rev-list", "--count", f"{REMOTE}..HEAD"))
    behind = int(git("rev-list", "--count", f"HEAD..{REMOTE}"))
    base = git("merge-base", "HEAD", REMOTE)

    local_code = _non_state(git("diff", "--name-only", base, "HEAD").splitlines())
    if ahead and local_code:
        log(f"sync: REFUSED - unpushed code commits touch {local_code}. Push them first. Not trading.")
        return 2

    # Did the cloud add any trade rows since we split? Then it was the acting writer.
    added = [l for l in git("diff", base, REMOTE, "--", "trades.csv").splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    cloud_traded = bool(added)

    action = decide(ahead, behind, cloud_traded)
    log(f"sync: ahead={ahead} behind={behind} cloud_traded={cloud_traded} -> {action}")

    if action == "keep_local":
        return 0
    if action == "fast_forward":
        git("merge", "-q", "--ff-only", REMOTE)
        return 0
    if action == "adopt_origin":
        dropped = [l for l in git("diff", base, "HEAD", "--", "trades.csv").splitlines()
                   if l.startswith("+") and not l.startswith("+++")]
        git("reset", "-q", "--hard", REMOTE)
        log(f"sync: *** cloud traded while we were diverged - adopted GitHub's state; "
            f"dropped {len(dropped)} laptop trade row(s) to avoid double-trading ***")
        for l in dropped:
            log(f"sync:   dropped: {l[1:][:90]}")
        return 0

    # keep_local_on_origin: the cloud only touched bookkeeping, so the laptop's state is the
    # complete truth. Re-base it onto origin as a single commit -> the push fast-forwards.
    saved = {f: open(os.path.join(REPO, f), "rb").read()
             for f in STATE_FILES if os.path.exists(os.path.join(REPO, f))}
    git("reset", "-q", "--hard", REMOTE)
    for f, data in saved.items():
        with open(os.path.join(REPO, f), "wb") as fh:
            fh.write(data)
    if git("status", "--porcelain", "--", *STATE_FILES):
        git("add", "--", *_present())
        git("commit", "-q", "-m",
            "Reconcile: laptop state supersedes cloud bookkeeping (cloud made no trades)")
    log("sync: kept laptop state on top of GitHub (cloud had only rewritten bookkeeping)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(sync())
    except Exception as e:  # a sync bug must not crash the scheduler; refuse to trade instead
        print(f"sync: ERROR {e} - not trading this run")
        sys.exit(2)
