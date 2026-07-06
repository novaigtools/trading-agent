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
from datetime import datetime

RISK_FILE   = "risk_state.json"
TRADES_FILE = "trades.csv"


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
    ts    = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
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
    state     = load_state()
    positions = state.get("open_positions", {})

    if not positions:
        print("  No open positions — nothing to monitor.")
        return

    triggered = []
    for symbol, pos in list(positions.items()):
        try:
            price = fetch_price(symbol)
            entry = pos["entry_price"]
            sl    = pos["stop_loss"]
            tp    = pos["take_profit"]
            pct   = (price - entry) / entry * 100
            pnl   = (price - entry) * pos["quantity"]
            print(f"  {symbol:<12} entry=${entry}  now=${price}  {pct:+.2f}%  P&L=${pnl:+.2f}  SL={sl}  TP={tp}")

            if price <= sl:
                reason = "Automated STOP LOSS triggered"
            elif price >= tp:
                reason = "Automated TAKE PROFIT triggered"
            else:
                continue

            log_trade(symbol, price, pos["quantity"], reason)
            # Sale proceeds return to cash — realized P&L captured automatically
            state["cash"] = round(state.get("cash", 0) + price * pos["quantity"], 4)
            del state["open_positions"][symbol]
            label = "SL" if "STOP" in reason else "TP"
            triggered.append(f"{label} {symbol} @ ${price}  P&L=${pnl:+.2f}")

        except Exception as e:
            print(f"  Could not check {symbol}: {e}")

    if triggered:
        save_state(state)
        print(f"\n  EXECUTED: {len(triggered)} trade(s):")
        for t in triggered:
            print(f"    {t}")
        send_alert_email(triggered)
    else:
        print(f"\n  All {len(positions)} position(s) within range — no action needed.")


if __name__ == "__main__":
    print(f"\n  SL/TP Monitor  --  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {'-'*50}")
    run()
