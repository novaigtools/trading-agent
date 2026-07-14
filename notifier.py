import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from config import GMAIL_SENDER, GMAIL_APP_PASSWORD, NOTIFY_EMAIL, PAPER_TRADING

# Alert throttle state lives in logs/, NOT risk_state.json — that file gets committed
# and pushed to GitHub every run, and alert bookkeeping has no business in there.
ALERT_STATE_FILE = os.path.join("logs", "last_alert.json")
ALERT_COOLDOWN_HOURS = 6


def _send(subject: str, body: str) -> bool:
    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD or not NOTIFY_EMAIL:
        print("  Email skipped — credentials not configured in .env")
        return False
    msg = MIMEMultipart()
    msg["From"] = GMAIL_SENDER
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER, NOTIFY_EMAIL, msg.as_string())
        print(f"  Email sent to {NOTIFY_EMAIL}")
        return True
    except Exception as e:
        print(f"  Email failed: {e}")
        return False


def _alert_throttled(key: str) -> bool:
    """True if we already alerted for `key` within the cooldown window."""
    try:
        with open(ALERT_STATE_FILE) as f:
            last = json.load(f)
        stamp = last.get(key)
        if not stamp:
            return False
        sent_at = datetime.fromisoformat(stamp)
        return datetime.now(timezone.utc) - sent_at < timedelta(hours=ALERT_COOLDOWN_HOURS)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
        return False


def _record_alert(key: str):
    os.makedirs("logs", exist_ok=True)
    try:
        with open(ALERT_STATE_FILE) as f:
            last = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        last = {}
    last[key] = datetime.now(timezone.utc).isoformat()
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(last, f, indent=2)


def _write_local_alert(subject: str, body: str):
    """
    Always record alerts on disk, even when email works — and especially when it
    doesn't. Email is the only channel that can fail silently (expired Gmail App
    Password, no network), and an alerting system that can go quiet is worthless.
    """
    os.makedirs("logs", exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join("logs", "ALERTS.log"), "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 70}\n[{stamp} UTC] {subject}\n{'=' * 70}\n{body}\n")


def send_alert_email(subject: str, body: str, key: str = "default") -> bool:
    """
    Health alert (engine dead, bot stalled). Rate-limited to one per `key` per 6 hours
    so a persistent outage can't spam the inbox every 30 minutes.

    Returns True only if the email actually went out. A failed send is NOT recorded,
    so a broken mail server doesn't consume the alert budget — the next scan retries.
    """
    if _alert_throttled(key):
        print(f"  Alert '{key}' suppressed — already sent within {ALERT_COOLDOWN_HOURS}h.")
        return False

    full_body = (
        f"{body}\n\n"
        f"{'-' * 50}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"Mode: {'PAPER' if PAPER_TRADING else 'LIVE'}\n"
        f"This alert is rate-limited to once per {ALERT_COOLDOWN_HOURS} hours.\n"
    )

    _write_local_alert(subject, full_body)   # never lost, even if email is dead

    if _send(subject, full_body):
        _record_alert(key)
        return True

    print(f"  !! ALERT COULD NOT BE EMAILED — recorded in logs/ALERTS.log instead: {subject}")
    return False


def send_trade_email(symbol: str, action: str, price: float, quantity: float,
                     value: float, pnl: float | None, confidence: int, reasoning: str):
    mode = "PAPER TRADE" if PAPER_TRADING else "LIVE TRADE"
    pnl_line = f"P&L: ${pnl:+.4f}" if pnl is not None else ""
    emoji = "🟢" if action == "BUY" else "🔴"

    subject = f"{emoji} [{mode}] {action} {symbol} @ ${price:,.4f}"
    body = f"""
Your crypto trading agent just executed a trade.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {mode}
  Time:       {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
  Action:     {action}
  Symbol:     {symbol}
  Price:      ${price:,.4f}
  Quantity:   {quantity}
  Value:      ${value:.2f}
  {pnl_line}
  Confidence: {confidence}/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Reasoning:
{reasoning}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is an automated message from your trading agent.
"""
    _send(subject, body)
