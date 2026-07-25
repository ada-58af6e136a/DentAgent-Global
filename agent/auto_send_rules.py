"""
agent/auto_send_rules.py

Pure auto-send eligibility rules, deliberately isolated from
agent/email_handler.py so this exact logic can be imported by anything that
needs a real eligibility answer — the live pipeline AND
scripts/seed_demo_data.py — without pulling in email_handler's heavy
transitive imports (classify_intent/generate_reply -> chromadb /
sentence-transformers / torch / langchain_*), which this logic has zero
actual dependency on.

Before this module existed, the demo seed data had would_auto_send values
typed by hand (checked against these thresholds by eye, not computed) —
correct at the time, but with no guarantee of staying correct if the
thresholds ever changed. Importing this module's function instead makes that
impossible to get wrong: the demo is scored by the same code path production
would use, not a hand-kept approximation of it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

AUTO_SEND_INTENTS = {
    s.strip() for s in os.getenv("AUTO_SEND_INTENTS", "PRICING,MATERIAL,PROGRESS").split(",")
    if s.strip()
}
AUTO_SEND_CONFIDENCE_THRESHOLD = float(os.getenv("AUTO_SEND_CONFIDENCE_THRESHOLD", "0.9"))
AUTO_SEND_RETRIEVAL_THRESHOLD = float(os.getenv("AUTO_SEND_RETRIEVAL_THRESHOLD", "0.5"))
# Per-client override: emails or bare domains that should never be auto-sent
# to regardless of confidence/score — e.g. a VIP account you always want a
# human to personally handle. Matched case-insensitively against either the
# sender's full address or its domain (with a leading "@").
AUTO_SEND_EXCLUDED_CLIENTS = {
    s.strip().lower() for s in os.getenv("AUTO_SEND_EXCLUDED_CLIENTS", "").split(",")
    if s.strip()
}


def parse_to_address(raw_from: str) -> str:
    """Extract the bare email address from a 'Display Name <addr>' header."""
    if "<" in raw_from and ">" in raw_from:
        return raw_from.split("<")[1].split(">")[0].strip()
    return raw_from.strip()


def is_excluded_client(raw_from: str) -> bool:
    """True if the sender is on AUTO_SEND_EXCLUDED_CLIENTS, by exact address or domain."""
    if not AUTO_SEND_EXCLUDED_CLIENTS:
        return False
    email = parse_to_address(raw_from).lower()
    domain = "@" + email.split("@")[-1] if "@" in email else ""
    return email in AUTO_SEND_EXCLUDED_CLIENTS or domain in AUTO_SEND_EXCLUDED_CLIENTS


def meets_auto_send_criteria(intent: str, confidence: float, retrieval_score: float,
                              escalate: bool, sender: str) -> bool:
    """
    True if this email qualifies for auto-send — intent on the allow-list AND
    both confidence and retrieval score clearing their thresholds AND not
    escalated AND the sender isn't on AUTO_SEND_EXCLUDED_CLIENTS. Any one
    weak signal disqualifies it.

    Deliberately does NOT check AUTO_SEND_ENABLED — evaluated for every
    email regardless (shadow mode), so the "is the feature even on" gate
    lives at the call site (agent/email_handler.py:process_email()), not
    here. That split is what makes shadow mode free: this function's answer
    is recorded whether or not anything acts on it. The client exclusion
    check lives *inside* this function rather than only gating the real send
    — otherwise would_auto_send would say "yes" for a client that could
    never actually qualify, which would be a lie in the calibration data.
    """
    if escalate or is_excluded_client(sender):
        return False
    return (
        intent in AUTO_SEND_INTENTS
        and confidence >= AUTO_SEND_CONFIDENCE_THRESHOLD
        and retrieval_score >= AUTO_SEND_RETRIEVAL_THRESHOLD
    )
