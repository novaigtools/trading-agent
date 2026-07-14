"""
Tests for the failure reporting that the old code lacked.

The 6-day outage happened because "every LLM call failed" and "the market was quiet"
produced byte-identical output. These tests make that regression impossible.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brain
from tests.test_local_brain import make_market_data, sentiment, NEUTRAL


def test_rules_mode_never_reports_failures():
    md = [make_market_data(symbol=s) for s in ("SOLUSDT", "SUIUSDT", "NEARUSDT")]
    res = brain.get_decisions_for_all(md, sentiment(), NEUTRAL, mode="rules")
    assert res.attempted == 3
    assert res.failed == 0
    assert res.llm_calls == 0        # the whole point: zero LLM, zero cost
    assert not res.is_dead
    assert not res.is_degraded
    assert len(res.decisions) == 3


def test_dead_engine_is_detectable():
    res = brain.BrainResult(attempted=10, failed=10, first_error="credit balance too low")
    assert res.is_dead                # THIS is what went undetected for 6 days
    assert not res.is_degraded
    assert res.succeeded == 0


def test_degraded_engine_is_distinct_from_dead():
    res = brain.BrainResult(attempted=10, failed=3, first_error="timeout")
    assert res.is_degraded
    assert not res.is_dead
    assert res.succeeded == 7


def test_quiet_market_is_not_mistaken_for_a_dead_engine():
    """The exact ambiguity that hid the outage: no trades, but the engine is healthy."""
    md = [make_market_data(symbol=s) for s in ("SOLUSDT", "SUIUSDT")]  # flat, no signals
    res = brain.get_decisions_for_all(md, sentiment(), NEUTRAL, mode="rules")
    assert all(d["action"] == "HOLD" for d in res.decisions)  # no trades...
    assert not res.is_dead                                    # ...but NOT dead
    assert res.succeeded == 2


def test_fetch_errors_do_not_count_as_decision_failures():
    md = [make_market_data(symbol="SOLUSDT"), {"symbol": "BROKENUSDT", "error": "timeout"}]
    res = brain.get_decisions_for_all(md, sentiment(), NEUTRAL, mode="rules")
    assert res.attempted == 1     # the broken symbol was never attempted
    assert res.failed == 0        # a fetch error is not an engine failure
    assert not res.is_dead


def test_unknown_brain_mode_falls_back_to_rules_rather_than_crashing():
    md = [make_market_data()]
    res = brain.get_decisions_for_all(md, sentiment(), NEUTRAL, mode="nonsense")
    assert res.mode == "rules"
    assert len(res.decisions) == 1


def test_hybrid_makes_zero_llm_calls_when_nothing_scores_high():
    """Most scans: no candidates, no LLM calls. This is why rate limits are never hit."""
    md = [make_market_data(symbol=s) for s in ("SOLUSDT", "SUIUSDT")]  # flat = low scores
    res = brain.get_decisions_for_all(md, sentiment(), NEUTRAL, mode="hybrid")
    assert res.llm_calls == 0
    assert res.failed == 0
    assert not res.is_dead
