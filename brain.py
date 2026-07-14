"""
brain — the single entry point run_once.py calls for decisions.

Dispatches to one of four engines based on BRAIN_MODE and, crucially, reports
*health*: how many decision calls were attempted, how many failed, and the first
error. The old code returned a bare list, so "every LLM call failed" and "the market
was quiet" produced identical output — the bot was brain-dead for 6 days and the logs
looked fine. That ambiguity is now impossible to express.
"""
from dataclasses import dataclass, field

import local_brain
from config import BRAIN_MODE, MAX_LLM_CALLS_PER_SCAN, HYBRID_CANDIDATE_SCORE


@dataclass
class BrainResult:
    decisions: list = field(default_factory=list)
    attempted: int = 0          # symbols we tried to get a decision for
    failed: int = 0             # decision calls that raised / returned nothing usable
    first_error: str | None = None
    mode: str = "rules"         # mode actually used (may differ from requested on fallback)
    llm_calls: int = 0          # how many LLM round-trips this scan actually made
    disagreements: list = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return self.attempted - self.failed

    @property
    def is_dead(self) -> bool:
        """Every single decision call failed — the bot is not trading."""
        return self.attempted > 0 and self.succeeded == 0

    @property
    def is_degraded(self) -> bool:
        """Some calls failed but not all — quality is reduced, trading continues."""
        return self.failed > 0 and not self.is_dead


def _tradeable(market_data_list: list) -> list:
    return [md for md in market_data_list if "error" not in md]


def _run_rules(market_data_list, sentiment, regime, active_trending, open_positions) -> BrainResult:
    """The rule engine cannot fail as a unit — a broken symbol degrades to HOLD."""
    tradeable = _tradeable(market_data_list)
    decisions = local_brain.get_decisions_for_all(
        market_data_list, sentiment, regime, active_trending, open_positions)
    return BrainResult(decisions=decisions, attempted=len(tradeable), failed=0, mode="rules")


def _run_cli(market_data_list, sentiment, regime, active_trending, open_positions) -> BrainResult:
    """Pure CLI mode: every symbol goes to the LLM, rules catch any failure."""
    import cli_brain

    tradeable = _tradeable(market_data_list)
    if not cli_brain.available():
        res = _run_rules(market_data_list, sentiment, regime, active_trending, open_positions)
        res.mode = "rules (cli unavailable)"
        return res

    rules_by_symbol = {
        d["symbol"]: d
        for d in local_brain.get_decisions_for_all(
            market_data_list, sentiment, regime, active_trending, open_positions)
    }

    res = BrainResult(attempted=len(tradeable), mode="cli")
    for md in tradeable:
        sym = md["symbol"]
        decision = cli_brain.get_trading_decision(md, sentiment, regime, active_trending)
        if decision is None:
            res.failed += 1
            res.first_error = res.first_error or f"CLI call failed for {sym}"
            res.decisions.append(rules_by_symbol[sym])  # fall back, keep trading
        else:
            res.llm_calls += 1
            res.decisions.append(decision)
    return res


def _run_hybrid(market_data_list, sentiment, regime, active_trending, open_positions) -> BrainResult:
    """
    The default. Rules score everything (free); only genuine candidates get a
    second opinion from the CLI, hard-capped so we can't burn rate limits.
    Most scans produce zero candidates and make zero LLM calls.
    """
    import cli_brain

    tradeable = _tradeable(market_data_list)
    rules = local_brain.get_decisions_for_all(
        market_data_list, sentiment, regime, active_trending, open_positions)
    by_symbol = {d["symbol"]: d for d in rules}

    res = BrainResult(decisions=list(rules), attempted=len(tradeable), mode="hybrid")

    candidates = sorted(
        (d for d in rules if d["confidence"] >= HYBRID_CANDIDATE_SCORE),
        key=lambda d: d["confidence"], reverse=True,
    )[:MAX_LLM_CALLS_PER_SCAN]

    if not candidates:
        print(f"  No candidates scored >= {HYBRID_CANDIDATE_SCORE} — 0 LLM calls needed.")
        return res

    if not cli_brain.available():
        res.mode = "hybrid (cli unavailable, rules only)"
        return res

    md_by_symbol = {md["symbol"]: md for md in tradeable}
    for cand in candidates:
        sym = cand["symbol"]
        print(f"  Candidate {sym} scored {cand['confidence']}/10 — asking CLI for a second opinion...")
        second = cli_brain.get_trading_decision(md_by_symbol[sym], sentiment, regime, active_trending)

        if second is None:
            res.failed += 1
            res.first_error = res.first_error or f"CLI second-opinion failed for {sym}"
            print(f"  HYBRID: CLI unavailable for {sym} — keeping rules decision "
                  f"({cand['action']} @{cand['confidence']}).")
            continue

        res.llm_calls += 1
        if second["action"] != cand["action"]:
            note = (f"rules said {cand['action']} {sym} @{cand['confidence']}, "
                    f"CLI said {second['action']} @{second.get('confidence', '?')} "
                    f"({str(second.get('reasoning', ''))[:120]})")
            res.disagreements.append(note)
            print(f"  HYBRID: {note}")

        # The CLI is the tiebreaker — it can veto a rules BUY or confirm it.
        second["reasoning"] = (f"[HYBRID] {second.get('reasoning', '')} "
                               f"|| {cand['reasoning']}")
        res.decisions = [second if d["symbol"] == sym else d for d in res.decisions]

    return res


def _run_api(market_data_list, sentiment, regime, active_trending, open_positions) -> BrainResult:
    """Legacy paid API. Kept working, never the default. Falls back to rules per-symbol."""
    import claude_brain

    tradeable = _tradeable(market_data_list)
    rules_by_symbol = {
        d["symbol"]: d
        for d in local_brain.get_decisions_for_all(
            market_data_list, sentiment, regime, active_trending, open_positions)
    }

    res = BrainResult(attempted=len(tradeable), mode="api")
    for md in tradeable:
        sym = md["symbol"]
        try:
            decision = claude_brain.get_trading_decision(md, sentiment, regime, active_trending)
            decision["market_price"] = md["price"]
            res.decisions.append(decision)
            res.llm_calls += 1
        except Exception as e:
            res.failed += 1
            res.first_error = res.first_error or f"{type(e).__name__}: {e}"
            print(f"  API decision failed for {sym}: {e}")
            res.decisions.append(rules_by_symbol[sym])
    return res


_MODES = {
    "rules":  _run_rules,
    "cli":    _run_cli,
    "hybrid": _run_hybrid,
    "api":    _run_api,
}


def get_decisions_for_all(market_data_list: list, sentiment: dict = None, regime: dict = None,
                          active_trending: set = None, open_positions: dict = None,
                          mode: str = None) -> BrainResult:
    """Contract entry point. Always returns a BrainResult — never raises."""
    requested = (mode or BRAIN_MODE).lower()
    runner = _MODES.get(requested)
    if runner is None:
        print(f"  Unknown BRAIN_MODE '{requested}' — falling back to rules.")
        runner = _run_rules

    return runner(market_data_list, sentiment or {}, regime or {},
                  active_trending or set(), open_positions or {})
