"""
health_check — the dead-man's switch.

The whole point: the bot must never again be silently broken for days. This runs hourly
from Task Scheduler, reads logs/scan.log, and emails if the bot has stopped scanning or
stopped producing decisions.

False alarms are acceptable. Silent weeks are not.
"""
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import notifier

SCAN_LOG = os.path.join("logs", "scan.log")

NO_SCAN_HOURS      = 2    # nothing ran at all
NO_DECISIONS_HOURS = 3    # scans ran but produced zero successful decision cycles
STUCK_HOURS        = 48   # long-run "something is deeply wrong"

# bot_task.ps1 prefixes every line with "[YYYY-MM-DD HH:MM:SS UTC] "
TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\]")
# run_once.py structured line: "BRAIN: mode=... symbols evaluated=N ... failures=N"
BRAIN_RE = re.compile(r"BRAIN: mode=(\S+) \| symbols evaluated=(\d+) \| LLM calls=(\d+) \| failures=(\d+)")


def _parse_ts(line: str):
    m = TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def analyze(lines: list) -> dict:
    """Walk the log and find: last scan of any kind, last HEALTHY decision cycle."""
    last_scan = None
    last_good_cycle = None
    last_brain_line = None

    for line in lines:
        ts = _parse_ts(line)
        if ts is None:
            continue
        if "run started" in line:
            last_scan = ts if last_scan is None or ts > last_scan else last_scan

        m = BRAIN_RE.search(line)
        if m:
            evaluated, failures = int(m.group(2)), int(m.group(4))
            succeeded = evaluated - failures
            last_brain_line = line.strip()
            if succeeded > 0 and (last_good_cycle is None or ts > last_good_cycle):
                last_good_cycle = ts

    return {
        "last_scan": last_scan,
        "last_good_cycle": last_good_cycle,
        "last_brain_line": last_brain_line,
    }


def main() -> int:
    now = datetime.now(timezone.utc)

    if not os.path.exists(SCAN_LOG):
        notifier.send_alert_email(
            subject="⚠️ Trading bot: no scan log found",
            body=f"health_check could not find {SCAN_LOG}. The scan task may never have run.",
            key="no_log",
        )
        print(f"  No scan log at {SCAN_LOG}")
        return 1

    with open(SCAN_LOG, encoding="utf-8", errors="replace") as f:
        info = analyze(f.readlines())

    last_scan = info["last_scan"]
    last_good = info["last_good_cycle"]

    print(f"  Now              : {now:%Y-%m-%d %H:%M} UTC")
    print(f"  Last scan started: {last_scan:%Y-%m-%d %H:%M} UTC" if last_scan else "  Last scan started: NEVER")
    print(f"  Last good cycle  : {last_good:%Y-%m-%d %H:%M} UTC" if last_good else "  Last good cycle  : NEVER")
    if info["last_brain_line"]:
        print(f"  Last brain line  : {info['last_brain_line']}")

    problems = []

    if last_scan is None or now - last_scan > timedelta(hours=NO_SCAN_HOURS):
        age = "never" if last_scan is None else f"{(now - last_scan).total_seconds() / 3600:.1f}h ago"
        problems.append(
            f"NO SCANS: the last scan started {age} (expected every 30 min). "
            f"The scheduled task may be disabled, or the laptop was asleep."
        )

    if last_good is None or now - last_good > timedelta(hours=STUCK_HOURS):
        age = "never" if last_good is None else f"{(now - last_good).total_seconds() / 3600:.1f}h ago"
        problems.append(
            f"BOT MAY BE STUCK: no successful decision cycle in {STUCK_HOURS}h (last: {age}). "
            f"This is what a dead decision engine looks like."
        )
    elif now - last_good > timedelta(hours=NO_DECISIONS_HOURS):
        age = f"{(now - last_good).total_seconds() / 3600:.1f}h ago"
        problems.append(
            f"NO DECISIONS: scans are running but the last successful decision cycle was "
            f"{age} (expected within {NO_DECISIONS_HOURS}h)."
        )

    if not problems:
        print("  HEALTHY — scans running, decisions succeeding.")
        return 0

    body = "The trading bot health check found problems:\n\n" + "\n\n".join(f"- {p}" for p in problems)
    if info["last_brain_line"]:
        body += f"\n\nLast brain status line from the log:\n  {info['last_brain_line']}"
    body += (
        "\n\nWhat to check:\n"
        "  1. schtasks /query /tn \"TradingBot-Scan\"   (is it Ready or Disabled?)\n"
        "  2. logs/scan.log — look for a DEAD or DEGRADED banner\n"
        "  3. If an LLM outage is to blame, set BRAIN_MODE=rules in .env — the local rule\n"
        "     engine needs no network and no keys, and will keep trading."
    )

    print("\n  PROBLEMS FOUND:")
    for p in problems:
        print(f"    - {p}")

    notifier.send_alert_email(
        subject="🚨 Trading bot health check FAILED",
        body=body,
        key="health_check",
    )
    return 1


if __name__ == "__main__":
    print(f"\n  Health Check — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    print(f"  {'-' * 52}")
    sys.exit(main())
