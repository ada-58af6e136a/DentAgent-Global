"""Entry point for the email polling loop. Run from project root: python run_handler.py"""
import os

from agent.email_handler import run_loop

if __name__ == "__main__":
    # Default lowered from 60s: with classify+reply already down to ~4s of
    # actual processing, the poll interval was the dominant term in a
    # customer's end-to-end wait (up to 60s just sitting unpolled before
    # processing even starts) — see the token/latency optimization work.
    # Override via POLL_INTERVAL_SECONDS if 15s turns out to be too
    # aggressive for a given Gmail account/quota.
    run_loop(interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "15")))
