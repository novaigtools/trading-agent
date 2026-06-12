import json
import os
from datetime import datetime, timedelta
from config import (
    WEEKLY_BUDGET, MAX_POSITION_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    PENNY_PAIRS, PENNY_MAX_PCT, PENNY_STOP_LOSS_PCT, PENNY_TAKE_PROFIT_PCT,
    MAX_PENNY_POSITIONS,
)

RISK_STATE_FILE = "risk_state.json"


def _load_state() -> dict:
    if os.path.exists(RISK_STATE_FILE):
        with open(RISK_STATE_FILE) as f:
            return json.load(f)
    return {"week_start": _week_start(), "spent_this_week": 0.0, "open_positions": {}}


def _save_state(state: dict):
    with open(RISK_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _week_start() -> str:
    today = datetime.utcnow()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def _reset_if_new_week(state: dict) -> dict:
    if state["week_start"] != _week_start():
        state["week_start"] = _week_start()
        state["spent_this_week"] = 0.0
        print(f"  New week — budget reset to ${WEEKLY_BUDGET:.2f}")
    return state


def _is_penny(symbol: str) -> bool:
    return symbol in PENNY_PAIRS


def _penny_positions_open(state: dict) -> int:
    return sum(1 for s in state.get("open_positions", {}) if s in PENNY_PAIRS)


def get_position_size(price: float, symbol: str = "") -> float:
    state = _load_state()
    state = _reset_if_new_week(state)
    remaining = WEEKLY_BUDGET - state["spent_this_week"]

    if _is_penny(symbol):
        if _penny_positions_open(state) >= MAX_PENNY_POSITIONS:
            return 0.0  # Already at max penny exposure
        max_trade = WEEKLY_BUDGET * PENNY_MAX_PCT
    else:
        max_trade = WEEKLY_BUDGET * MAX_POSITION_PCT

    amount_usd = min(remaining, max_trade)
    if amount_usd < 5:
        return 0.0
    return round(amount_usd / price, 6)


def budget_remaining() -> float:
    state = _load_state()
    state = _reset_if_new_week(state)
    return round(WEEKLY_BUDGET - state["spent_this_week"], 2)


def record_trade(symbol: str, side: str, price: float, quantity: float):
    state = _load_state()
    state = _reset_if_new_week(state)
    cost = price * quantity
    if side == "BUY":
        state["spent_this_week"] += cost
        sl_pct = PENNY_STOP_LOSS_PCT if _is_penny(symbol) else STOP_LOSS_PCT
        tp_pct = PENNY_TAKE_PROFIT_PCT if _is_penny(symbol) else TAKE_PROFIT_PCT
        state["open_positions"][symbol] = {
            "entry_price": price,
            "quantity": quantity,
            "stop_loss": round(price * (1 - sl_pct), 8),
            "take_profit": round(price * (1 + tp_pct), 8),
            "opened_at": datetime.utcnow().isoformat(),
            "is_penny": _is_penny(symbol),
        }
    elif side == "SELL" and symbol in state["open_positions"]:
        # Recycle the original capital back into available budget
        original_cost = state["open_positions"][symbol]["entry_price"] * state["open_positions"][symbol]["quantity"]
        state["spent_this_week"] = max(0, state["spent_this_week"] - original_cost)
        del state["open_positions"][symbol]
    _save_state(state)


def check_stop_loss_take_profit(current_prices: dict) -> list[dict]:
    state = _load_state()
    triggers = []
    for symbol, pos in list(state["open_positions"].items()):
        price = current_prices.get(symbol)
        if price is None:
            continue
        if price <= pos["stop_loss"]:
            triggers.append({"symbol": symbol, "action": "SELL", "reason": "stop_loss", "price": price})
        elif price >= pos["take_profit"]:
            triggers.append({"symbol": symbol, "action": "SELL", "reason": "take_profit", "price": price})
    return triggers


def get_open_positions() -> dict:
    return _load_state().get("open_positions", {})


def weekly_summary() -> dict:
    state = _load_state()
    return {
        "week_start": state["week_start"],
        "budget": WEEKLY_BUDGET,
        "spent": round(state["spent_this_week"], 2),
        "remaining": round(WEEKLY_BUDGET - state["spent_this_week"], 2),
        "open_positions": len(state.get("open_positions", {})),
    }
