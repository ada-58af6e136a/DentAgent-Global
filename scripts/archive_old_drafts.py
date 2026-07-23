"""
scripts/archive_old_drafts.py

Moves terminal-state drafts (approved/edited/escalated/auto_sent) older than
DRAFTS_ARCHIVE_AFTER_DAYS into drafts_archive, keeping the live `drafts`
table lean for Ops Dashboard queries. pending_review rows are never touched
regardless of age — those are still-actionable work, not history.

Not run automatically — archival isn't latency-sensitive or safety-critical
the way auto-send/circuit-breaker logic is, so this is meant to be run
periodically by hand or via cron, not from inside email_handler.run_loop().

Run from the project root:
    python scripts/archive_old_drafts.py
    python scripts/archive_old_drafts.py --days 30
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.db import archive_old_drafts

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--days", type=int,
        default=int(os.getenv("DRAFTS_ARCHIVE_AFTER_DAYS", "90")),
        help="Archive terminal-state drafts older than this many days (default: 90, "
             "or DRAFTS_ARCHIVE_AFTER_DAYS from .env).",
    )
    args = parser.parse_args()

    count = archive_old_drafts(args.days)
    print(f"Archived {count} draft(s) older than {args.days} days into drafts_archive.")
