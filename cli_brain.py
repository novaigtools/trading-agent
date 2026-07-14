"""
cli_brain — talks to the local Claude Code CLI (`claude -p`), billed to the Claude
subscription rather than API credits. This is what replaces the paid API that ran dry.

Design rule: this module can NEVER stop the bot from trading. Every failure path —
CLI missing, timeout, bad JSON, non-zero exit — returns None so the caller falls back
to the rules decision. An LLM outage degrades quality, never availability.
"""
import json
import shutil
import subprocess

from config import CLAUDE_CLI_PATH, CLAUDE_CLI_TIMEOUT
from prompts import SYSTEM_PROMPT, build_user_prompt, strip_json_fence

# Resolved once per process. None = unavailable, don't keep retrying.
_cli_path = None
_checked = False
_warned = False


def _resolve_cli() -> str | None:
    """Find the claude binary. Task Scheduler runs with a thinner PATH than a
    terminal does, so an explicit CLAUDE_CLI_PATH in .env may be required."""
    global _cli_path, _checked, _warned
    if _checked:
        return _cli_path
    _checked = True

    found = shutil.which(CLAUDE_CLI_PATH)
    if not found:
        if not _warned:
            print(f"  [CLI] 'claude' not found on PATH (looked for: {CLAUDE_CLI_PATH}). "
                  f"Falling back to rules-only. Set CLAUDE_CLI_PATH in .env to the "
                  f"absolute path if the CLI is installed.")
            _warned = True
        return None

    # Self-test: a binary that exists but errors is worse than one that's absent.
    try:
        r = subprocess.run([found, "-p", "say OK"], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"  [CLI] self-test failed (exit {r.returncode}) — rules-only this scan.")
            return None
    except Exception as e:
        print(f"  [CLI] self-test errored ({e}) — rules-only this scan.")
        return None

    _cli_path = found
    print(f"  [CLI] Claude Code CLI available at {found}")
    return _cli_path


def available() -> bool:
    return _resolve_cli() is not None


def get_trading_decision(market_data: dict, sentiment: dict = None, regime: dict = None,
                         active_trending: set = None) -> dict | None:
    """One decision via the CLI. Returns None on ANY failure — caller falls back."""
    cli = _resolve_cli()
    if not cli:
        return None

    prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{build_user_prompt(market_data, sentiment, regime, active_trending)}"

    try:
        proc = subprocess.run(
            [cli, "-p", prompt, "--output-format", "json", "--max-turns", "1"],
            capture_output=True, text=True, timeout=CLAUDE_CLI_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"  [CLI] timeout after {CLAUDE_CLI_TIMEOUT}s on {market_data['symbol']} — using rules.")
        return None
    except Exception as e:
        print(f"  [CLI] subprocess error on {market_data['symbol']}: {e} — using rules.")
        return None

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:200]
        print(f"  [CLI] exit {proc.returncode} on {market_data['symbol']}: {err} — using rules.")
        return None

    # The CLI wraps the model's answer in an envelope: {"result": "...", ...}
    try:
        envelope = json.loads(proc.stdout)
        inner = envelope.get("result", proc.stdout) if isinstance(envelope, dict) else proc.stdout
    except json.JSONDecodeError:
        inner = proc.stdout

    try:
        decision = json.loads(strip_json_fence(inner))
    except (json.JSONDecodeError, TypeError) as e:
        print(f"  [CLI] could not parse decision JSON for {market_data['symbol']}: {e} — using rules.")
        return None

    if not isinstance(decision, dict) or "action" not in decision:
        print(f"  [CLI] malformed decision for {market_data['symbol']} — using rules.")
        return None

    decision["symbol"] = market_data["symbol"]
    decision["market_price"] = market_data["price"]
    decision.setdefault("trade_type", "intraday")
    decision.setdefault("confidence", 0)
    decision.setdefault("reasoning", "")
    return decision
