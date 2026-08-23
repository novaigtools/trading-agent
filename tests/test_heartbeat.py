"""The laptop/cloud handoff: heartbeat freshness decides who scans."""
import os, sys
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import heartbeat as hb


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hb, "HEARTBEAT_FILE", str(tmp_path / "heartbeat.json"))
    return tmp_path


def test_fresh_heartbeat_reads_active(sandbox):
    hb.write_heartbeat()
    assert hb.laptop_recently_active(50) is True


def test_stale_heartbeat_reads_inactive(sandbox):
    import json
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    json.dump({"last_local_run_utc": old, "host": "laptop"},
              open(str(sandbox / "heartbeat.json"), "w"))
    assert hb.laptop_recently_active(50) is False


def test_missing_heartbeat_fails_toward_cloud_coverage(sandbox):
    # No file at all -> NOT active -> cloud takes over. Fail toward coverage.
    assert hb.laptop_recently_active(50) is False


def test_garbled_heartbeat_fails_toward_cloud_coverage(sandbox):
    open(str(sandbox / "heartbeat.json"), "w").write("{not json")
    assert hb.laptop_recently_active(50) is False
