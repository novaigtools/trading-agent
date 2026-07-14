"""
claude_brain — LEGACY paid Anthropic API brain.

Kept for the future but never the default: ~21 symbols x 48 scans/day was ~1,000 paid
calls/day, which drained the credit balance on 2026-07-09 and left the bot brain-dead
for 6 days. Use BRAIN_MODE=hybrid (rules + Claude Code CLI) instead.

Importing this module must never fail, even with CLAUDE_API_KEY empty — the client is
constructed lazily so `import claude_brain` stays safe in every environment.
"""
import json

from config import CLAUDE_API_KEY
from prompts import SYSTEM_PROMPT, build_user_prompt, strip_json_fence

_client = None


def _get_client():
    """Lazy client. Raises only when someone actually tries to USE the paid API."""
    global _client
    if _client is None:
        if not CLAUDE_API_KEY:
            raise RuntimeError(
                "CLAUDE_API_KEY is not set — the paid API brain is unavailable. "
                "Use BRAIN_MODE=hybrid or BRAIN_MODE=rules."
            )
        import anthropic
        _client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    return _client


def get_trading_decision(market_data: dict, sentiment: dict = None, regime: dict = None,
                         active_trending: set = None) -> dict:
    """One decision via the paid API. Raises on failure — brain.py handles fallback."""
    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": build_user_prompt(market_data, sentiment, regime, active_trending),
        }],
    )
    decision = json.loads(strip_json_fence(response.content[0].text))
    decision["market_price"] = market_data["price"]
    return decision
