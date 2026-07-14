"""
A minimal advisory lock around risk_state.json.

run_once.py (slow, ~1-2 min) and sl_monitor.py (every 5 min) both read-modify-write the
same JSON file. Without a lock, a monitor SELL can be silently overwritten by a scan
that loaded state before the sell and saved after it — the position resurrects and the
cash vanishes.

Stdlib only, on purpose: sl_monitor.py runs on GitHub Actions with no pip install.
"""
import os
import time

LOCK_FILE = os.path.join("logs", "state.lock")
STALE_AFTER_SEC = 600  # a crashed process must not deadlock the bot forever


class LockBusy(Exception):
    """Another process holds the lock."""


def _is_stale(path: str) -> bool:
    try:
        return (time.time() - os.path.getmtime(path)) > STALE_AFTER_SEC
    except OSError:
        return False


def acquire(wait_sec: float = 0) -> bool:
    """
    Try to take the lock, optionally polling for up to wait_sec.
    Returns True on success, False if someone else holds it.
    """
    os.makedirs("logs", exist_ok=True)
    deadline = time.time() + wait_sec
    while True:
        try:
            # O_EXCL is the atomic bit: two processes cannot both win this race.
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if _is_stale(LOCK_FILE):
                print("  [lock] stale lock found (>10 min) — breaking it.")
                release()
                continue
            if time.time() >= deadline:
                return False
            time.sleep(0.25)


def release():
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass


class state_lock:
    """
    Context manager.
      required=True  -> raise LockBusy if we can't get it (caller skips its cycle)
      required=False -> proceed anyway after the wait, with a warning (scan must not
                        be starved by a monitor that runs every 5 minutes)
    """

    def __init__(self, wait_sec: float = 0, required: bool = True):
        self.wait_sec = wait_sec
        self.required = required
        self.held = False

    def __enter__(self):
        self.held = acquire(self.wait_sec)
        if not self.held:
            if self.required:
                raise LockBusy("risk_state.json is locked by another process")
            print("  [lock] busy after waiting — proceeding anyway (best effort).")
        return self

    def __exit__(self, *exc):
        if self.held:
            release()
        return False
