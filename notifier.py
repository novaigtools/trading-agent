import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import GMAIL_SENDER, GMAIL_APP_PASSWORD, NOTIFY_EMAIL, PAPER_TRADING


def send_trade_email(symbol: str, action: str, price: float, quantity: float,
                     value: float, pnl: float | None, confidence: int, reasoning: str):
    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD or not NOTIFY_EMAIL:
        print("  Email notification skipped — credentials not configured in .env")
        return

    mode = "PAPER TRADE" if PAPER_TRADING else "LIVE TRADE"
    pnl_line = f"P&L: ${pnl:+.4f}" if pnl is not None else ""
    emoji = "🟢" if action == "BUY" else "🔴"

    subject = f"{emoji} [{mode}] {action} {symbol} @ ${price:,.4f}"

    body = f"""
Your crypto trading agent just executed a trade.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {mode}
  Time:       {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
  Action:     {action}
  Symbol:     {symbol}
  Price:      ${price:,.4f}
  Quantity:   {quantity}
  Value:      ${value:.2f}
  {pnl_line}
  Confidence: {confidence}/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Claude's Reasoning:
{reasoning}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is an automated message from your trading agent.
"""

    msg = MIMEMultipart()
    msg["From"] = GMAIL_SENDER
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER, NOTIFY_EMAIL, msg.as_string())
        print(f"  Email notification sent to {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"  Email notification failed: {e}")
