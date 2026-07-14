"""
The 6-hour alert throttle. A persistent outage alerts once, not every 30 minutes.

Deliberate design point: a FAILED send is not recorded, so a broken mail server does
not consume the alert budget — the next scan retries.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifier


@pytest.fixture
def fake_mail(tmp_path, monkeypatch):
    """Redirect throttle state to a temp file and record sends instead of mailing."""
    monkeypatch.setattr(notifier, "ALERT_STATE_FILE", str(tmp_path / "last_alert.json"))
    monkeypatch.chdir(tmp_path)
    sent = []

    def _fake_send(subject, body):
        sent.append(subject)
        return True

    monkeypatch.setattr(notifier, "_send", _fake_send)
    return sent


def test_second_alert_within_window_is_suppressed(fake_mail):
    assert notifier.send_alert_email("dead", "body", key="engine_dead") is True
    assert notifier.send_alert_email("dead", "body", key="engine_dead") is False
    assert len(fake_mail) == 1, "the outage must alert once, not every scan"


def test_different_keys_do_not_throttle_each_other(fake_mail):
    assert notifier.send_alert_email("dead", "b", key="engine_dead") is True
    assert notifier.send_alert_email("stalled", "b", key="health_check") is True
    assert len(fake_mail) == 2


def test_failed_send_is_not_recorded_so_it_retries(tmp_path, monkeypatch):
    """If Gmail is down, we must NOT burn the 6h budget — retry on the next scan."""
    monkeypatch.setattr(notifier, "ALERT_STATE_FILE", str(tmp_path / "last_alert.json"))
    monkeypatch.chdir(tmp_path)
    attempts = []

    def _failing_send(subject, body):
        attempts.append(subject)
        return False  # e.g. bad credentials

    monkeypatch.setattr(notifier, "_send", _failing_send)

    assert notifier.send_alert_email("dead", "b", key="engine_dead") is False
    assert notifier.send_alert_email("dead", "b", key="engine_dead") is False
    assert len(attempts) == 2, "a failed send must be retried, not throttled away"
