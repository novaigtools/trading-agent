"""
Laptop liveness heartbeat — the handoff between the local bot and the cloud backstop.

The laptop's scheduled scan stamps heartbeat.json every run. The cloud scan reads it
and only takes over opening new trades when the stamp is stale (laptop asleep or off).
That way exactly one machine scans for entries at a time — no double-trading, no
fighting over risk_state.json.

Stdlib only, so the cloud (no pip install) can run the check.

CLI:
  python heartbeat.py write            # laptop stamps "I'm alive, now"
  python heartbeat.py check [minutes]  # prints 'active' or 'stale' (default 50 min)
"""
import json
import os
import sys
from datetime import datetime, timezone

HEARTBEAT_FILE = "heartbeat.json"
DEFAULT_MAX_AGE_MIN = 50   # laptop scans every 30 min; 50 tolerates one missed run


def write_heartbeat(host: str = "laptop"):
    data = {"last_local_run_utc": datetime.now(timezone.utc).isoformat(), "host": host}
    with open(HEARTBEAT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    return data


def laptop_recently_active(max_age_min: float = DEFAULT_MAX_AGE_MIN,
                           now: datetime = None) -> bool:
    """True if the laptop stamped the heartbeat within max_age_min. Missing/garbled
    heartbeat => treat as NOT active, so the cloud takes over (fail toward coverage)."""
    if not os.path.exists(HEARTBEAT_FILE):
        return False
    try:
        with open(HEARTBEAT_FILE) as f:
            stamp = json.load(f).get("last_local_run_utc")
        dt = datetime.fromisoformat(stamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    now = now or datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 60 < max_age_min


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "write":
        print(write_heartbeat())
    else:
        mins = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_AGE_MIN
        print("active" if laptop_recently_active(mins) else "stale")
