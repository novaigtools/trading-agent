"""
Lightweight Stop-Loss / Take-Profit monitor.
Uses ONLY Python built-ins (no pip install needed) — runs in ~5 seconds.
Runs locally every 5 minutes via Task Scheduler, and on GitHub Actions as a backstop.
"""
import json
import csv
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText
from datetime import datetime, timezone

from state_lock import state_lock, LockBusy       # stdlib-only, safe on GitHub Actions
import position_rules                              # stdlib-only shared position logic

RISK_FILE   = "risk_state.json"
TRADES_FILE = "trades.csv"

# Risk knobs. sl_monitor stays stdlib-only (no config import — it runs on GitHub with
# no pip install), so these mirror config.py's defaults and can be overridden via .env.
_ENV = None
def _cfg(key, default, cast=float):
    global _ENV
    if _ENV is None:
        _ENV = _load_env()
    try:
        return cast(_ENV.get(key, default))
    except (ValueError, TypeError):
        return default

PENNY_MARKERS = ("PEPE", "WIF", "FLOKI", "BONK", "TRUMP", "PENGU")


def _load_env():
    """Minimal .env parser (stdlib only). Real env vars take precedence."""
    env = {}
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    env.update(os.environ)
    return env


def fetch_price(symbol: str) -> float:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    with urllib.request.urlopen(url, timeout=5) as r:
        return float(json.loads(r.read())["price"])


def load_state() -> dict:
    if not os.path.exists(RISK_FILE):
        return {"cash": 0, "open_positions": {}}
    with open(RISK_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    with open(RISK_FILE, "w") as f:
        json.dump(state, f, indent=2)


def log_trade(symbol, price, quantity, reason):
    value = round(price * quantity, 2)
    ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    row   = f"{ts},{symbol},SELL,{price},{quantity},{value},{reason},10,intraday,PAPER"
    write_header = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a") as f:
        if write_header:
            f.write("timestamp,symbol,action,price,quantity,value_usd,reason,confidence,trade_type,mode\n")
        f.write(row + "\n")
    print(f"  [{reason}] {symbol} SELL @ ${price}  |  value: ${value}")


def send_alert_email(triggered: list):
    """Best-effort email alert — never blocks the sell logic."""
    env = _load_env()
    sender   = env.get("GMAIL_SENDER", "")
    password = env.get("GMAIL_APP_PASSWORD", "")
    to_addr  = env.get("NOTIFY_EMAIL", "") or sender
    if not sender or not password:
        return
    try:
        body = "SL/TP monitor executed the following paper trades:\n\n" + "\n".join(triggered)
        msg = MIMEText(body)
        msg["Subject"] = f"[Trading Bot] {len(triggered)} SL/TP trigger(s) fired"
        msg["From"] = sender
        msg["To"] = to_addr
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.send_message(msg)
        print(f"  Alert email sent to {to_addr}")
    except Exception as e:
        print(f"  Email alert failed (non-fatal): {e}")


def run():
    # A scan may be mid-write on risk_state.json. Rather than race it, skip — the
    # next monitor cycle is only 5 minutes away and prices barely move in that time.
    try:
        with state_lock(wait_sec=5, required=True):
            _run_locked()
    except LockBusy:
        print("  Scan is writing state right now — skipping this cycle (next in 5 min).")


def _run_locked():
    state     = load_state()
    positions = state.get("open_positions", {})

    if not positions:
        print("  No open positions — nothing to monitor.")
        return

    trail_enabled = str(_cfg("TRAIL_ENABLED", "true", str)).lower() == "true"
    trail_activate = _cfg("TRAIL_ACTIVATE_PCT", 0.03)
    trail_std      = _cfg("TRAIL_DISTANCE_PCT", 0.02)
    trail_penny    = _cfg("PENNY_TRAIL_DISTANCE_PCT", 0.03)
    max_hold       = _cfg("MAX_HOLD_HOURS", 48)

    triggered = []
    stops_moved = False
    for symbol, pos in list(positions.items()):
        try:
            price = fetch_price(symbol)
            entry = pos["entry_price"]

            # 1) Ratchet the trailing stop up on new highs (locks in gains).
            is_penny = pos.get("is_penny") or any(m in symbol for m in PENNY_MARKERS)
            if trail_enabled:
                updated = position_rules.update_trailing_stop(
                    pos, price, trail_activate, trail_penny if is_penny else trail_std)
                if updated["stop_loss"] != pos["stop_loss"] or \
                        updated.get("peak_price") != pos.get("peak_price"):
                    state["open_positions"][symbol] = updated
                    pos = updated
                    stops_moved = True

            sl    = pos["stop_loss"]
            tp    = pos["take_profit"]
            pct   = (price - entry) / entry * 100
            pnl   = (price - entry) * pos["quantity"]
            trail_note = "  [trailing]" if pos.get("trailing") else ""
            print(f"  {symbol:<12} entry=${entry}  now=${price}  {pct:+.2f}%  P&L=${pnl:+.2f}  SL={sl}  TP={tp}{trail_note}")

            if price <= sl:
                reason = "Automated STOP LOSS triggered" if not pos.get("trailing") \
                         else "Trailing stop triggered (gains locked)"
            elif price >= tp:
                reason = "Automated TAKE PROFIT triggered"
            elif position_rules.should_stale_exit(pos, price, max_hold):
                reason = f"Stale exit (held > {int(max_hold)}h, not in profit)"
            else:
                continue

            log_trade(symbol, price, pos["quantity"], reason)
            # Sale proceeds return to cash — realized P&L captured automatically
            state["cash"] = round(state.get("cash", 0) + price * pos["quantity"], 4)
            del state["open_positions"][symbol]
            label = "TP" if "TAKE PROFIT" in reason else ("SL" if "STOP" in reason or "Trailing" in reason else "EXIT")
            triggered.append(f"{label} {symbol} @ ${price}  P&L=${pnl:+.2f}  ({reason})")

        except Exception as e:
            print(f"  Could not check {symbol}: {e}")

    if triggered or stops_moved:
        save_state(state)

    if triggered:
        print(f"\n  EXECUTED: {len(triggered)} trade(s):")
        for t in triggered:
            print(f"    {t}")
        send_alert_email(triggered)
    elif stops_moved:
        print(f"\n  Trailing stops ratcheted up — no exits this cycle.")
    else:
        print(f"\n  All {len(positions)} position(s) within range — no action needed.")


if __name__ == "__main__":
    print(f"\n  SL/TP Monitor  --  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {'-'*50}")
    run()
