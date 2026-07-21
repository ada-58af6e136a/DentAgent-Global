"""
scripts/migrate_to_sqlite.py

One-time migration: import existing draft_queue.jsonl and
processed_queue.jsonl records into the new SQLite database.

Run once from the project root:
    python scripts/migrate_to_sqlite.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.db import init_db, save_draft

DRAFT_QUEUE     = PROJECT_ROOT / "data" / "draft_queue.jsonl"
PROCESSED_QUEUE = PROJECT_ROOT / "data" / "processed_queue.jsonl"


def migrate_file(path: Path, label: str) -> tuple:
    if not path.exists():
        print(f"  {label}: not found, skipping.")
        return 0, 0

    inserted = skipped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                # processed_queue rows have 'status' already set; draft_queue rows
                # default to 'pending_review' — both handled by save_draft()
                if save_draft(entry):
                    inserted += 1
                else:
                    skipped += 1
            except json.JSONDecodeError as e:
                print(f"  Warning: skipped malformed line — {e}")

    print(f"  {label}: {inserted} inserted, {skipped} already existed.")
    return inserted, skipped


def main():
    print("Initialising SQLite database...")
    init_db()

    print("Migrating draft_queue.jsonl...")
    migrate_file(DRAFT_QUEUE, "draft_queue.jsonl")

    print("Migrating processed_queue.jsonl...")
    migrate_file(PROCESSED_QUEUE, "processed_queue.jsonl")

    print("\nMigration complete. You can verify with:")
    print("  sqlite3 data/drafts.db 'SELECT status, COUNT(*) FROM drafts GROUP BY status;'")


if __name__ == "__main__":
    main()
