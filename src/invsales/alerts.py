"""Reorder alerts via Slack webhook and/or SMTP email. Dry-run unless `send=True`."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import pandas as pd
import requests

from .config import Settings

log = logging.getLogger(__name__)
ICON = {"Stockout": ":red_circle:", "Critical": ":large_orange_circle:", "Low": ":large_yellow_circle:"}


def format_message(alerts: pd.DataFrame, max_rows: int = 15) -> str:
    if alerts.empty:
        return "All products are above their reorder level."
    counts = alerts.severity.value_counts()
    head = (f"{len(alerts)} item(s) need reordering "
            f"(stockout: {counts.get('Stockout', 0)}, critical <=3d: {counts.get('Critical', 0)}, low: {counts.get('Low', 0)})")
    lines = [head, ""]
    for r in alerts.head(max_rows).itertuples():
        left = "n/a" if pd.isna(r.days_of_stock_left) else f"{r.days_of_stock_left:g}d left"
        lines.append(f"{ICON.get(r.severity, '-')} {r.product_name} @ {r.warehouse_name}: stock {r.current_stock} "
                     f"/ reorder at {r.reorder_level} - {left}, lead time {r.lead_time_days}d")
    if len(alerts) > max_rows:
        lines.append(f"... and {len(alerts) - max_rows} more")
    return "\n".join(lines)


def send_slack(webhook_url: str, text: str, timeout: int = 10) -> None:
    resp = requests.post(webhook_url, json={"text": text}, timeout=timeout)
    resp.raise_for_status()


def send_email(settings: Settings, subject: str, body: str) -> None:
    if not (settings.smtp_host and settings.alert_to and settings.alert_from):
        raise ValueError("SMTP_HOST, ALERT_FROM and ALERT_TO are required for email alerts")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings.alert_from, settings.alert_to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)


def dispatch(alerts: pd.DataFrame, settings: Settings, send: bool = False) -> str:
    """Build the message and, if `send`, push it to every configured channel. Returns the message."""
    text = format_message(alerts)
    if not send:
        log.info("dry-run, not sending:\n%s", text)
        return text
    if alerts.empty:
        return text
    sent = False
    if settings.slack_webhook_url:
        send_slack(settings.slack_webhook_url, text)
        sent = True
    if settings.smtp_host:
        send_email(settings, f"[Inventory] {len(alerts)} items need reordering", text)
        sent = True
    if not sent:
        log.warning("no alert channel configured (set SLACK_WEBHOOK_URL and/or SMTP_HOST)")
    return text
