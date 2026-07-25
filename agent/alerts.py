"""
agent/alerts.py

Slack alerting — a pure notification side-channel, deliberately independent
of email send/receive (a plain HTTPS POST, not SMTP) so a Gmail outage can't
also take down the ability to be notified about it. Same reasoning as the
Gemini->DeepSeek failover in api_client.py: don't let the alert channel share
a failure domain with the thing it's monitoring.

Fails safe: any error sending to Slack is logged and swallowed here, never
propagated — this module must never be the reason the pipeline crashes.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from .logger import get_logger

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = get_logger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()


def send_slack_alert(message: str) -> None:
    """
    POST message to the configured Slack Incoming Webhook.

    No-op if SLACK_WEBHOOK_URL isn't set — same "missing config = feature
    silently does nothing" pattern as DEEPSEEK_API_KEY. Never raises: a
    failed alert is logged, not propagated.
    """
    if not SLACK_WEBHOOK_URL:
        return
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=5)
        response.raise_for_status()
    except Exception as e:
        log.warning("Slack alert failed to send: %s", e)
