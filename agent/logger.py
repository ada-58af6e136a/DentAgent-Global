"""
agent/logger.py

Centralised logging configuration for the DentAgent pipeline.

Every module calls get_logger(__name__) to get a named logger.
Handlers are attached once on the first call; subsequent calls
return the same cached logger — safe to call at module level.

Log levels used across the codebase:
  DEBUG   — high-frequency detail: fetch per-email, intermediate classify values
  INFO    — key pipeline events: email processed, reply sent, cycle summary
  WARNING — recoverable issues: IMAP reconnect, KB miss, duplicate skip, retry
  ERROR   — actionable failures that need attention, always with full stack trace
"""

import logging
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LOG_FILE = _DATA_DIR / "agent.log"

_configured: set = set()


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for *name* with console + rotating-file handlers.

    Console outputs INFO+ (human-readable during development).
    File outputs DEBUG+ (full detail for post-incident analysis),
    rotated daily at midnight UTC with 30-day retention.
    """
    logger = logging.getLogger(name)

    if name in _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False   # don't bubble up to the root logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    fmt.converter = time.gmtime   # UTC timestamps everywhere

    # ── Console: INFO and above ──────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # ── File: DEBUG and above, daily rotation, 30-day retention ─────────────
    _DATA_DIR.mkdir(exist_ok=True)
    fh = TimedRotatingFileHandler(
        str(_LOG_FILE),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
        utc=True,
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    _configured.add(name)
    return logger
