"""
agent/db.py

SQLite persistence layer for the draft queue.
Replaces draft_queue.jsonl and processed_queue.jsonl.

WAL mode allows app.py (reader/updater) and email_handler.py (writer)
to operate concurrently without file-level locking or corruption.
INSERT OR IGNORE on message_id gives idempotent writes.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "drafts.db"


def get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id      TEXT UNIQUE NOT NULL,
                timestamp       TEXT,
                sender          TEXT,
                subject         TEXT,
                body            TEXT,
                intent          TEXT,
                language        TEXT,
                escalate        INTEGER DEFAULT 1,
                draft_reply     TEXT,
                sources         TEXT DEFAULT '[]',
                retrieval_score REAL DEFAULT 0.0,
                status          TEXT DEFAULT 'pending_review',
                final_reply     TEXT,
                human_edited    INTEGER DEFAULT 0,
                processed_at    TEXT
            )
        """)


def save_draft(entry: dict) -> bool:
    """
    Insert one draft; silently ignores duplicates (idempotent by message_id).
    Returns True if inserted, False if already existed.
    """
    init_db()
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT OR IGNORE INTO drafts
                (message_id, timestamp, sender, subject, body,
                 intent, language, escalate, draft_reply, sources,
                 retrieval_score, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            entry["message_id"],
            entry.get("timestamp"),
            entry.get("from", ""),
            entry.get("subject", ""),
            entry.get("body", ""),
            entry.get("intent", "OTHER"),
            entry.get("language", "en"),
            int(entry.get("escalate", True)),
            entry.get("draft_reply"),
            json.dumps(entry.get("sources", []), ensure_ascii=False),
            entry.get("retrieval_score", 0.0),
            entry.get("status", "pending_review"),
        ))
        return cur.rowcount > 0


def load_pending_drafts() -> list:
    """Return all drafts with status='pending_review', oldest first."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE status='pending_review' ORDER BY id"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_as_processed(message_id: str, action: str,
                       final_reply: str, human_edited: bool) -> dict | None:
    """
    Update status of a pending draft to action ('approved'/'edited'/'escalated').
    Returns the updated row dict, or None if message_id not found.
    """
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            UPDATE drafts
               SET status=?, final_reply=?, human_edited=?, processed_at=?
             WHERE message_id=? AND status='pending_review'
        """, (action, final_reply, int(human_edited), now, message_id))
        row = conn.execute(
            "SELECT * FROM drafts WHERE message_id=?", (message_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def count_processed() -> int:
    """Return total number of non-pending drafts (for dashboard stats)."""
    init_db()
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status != 'pending_review'"
        ).fetchone()[0]


def is_already_queued(message_id: str) -> bool:
    """
    Return True if message_id already exists in the drafts table.

    Used as a pre-processing guard: if an email was saved on a previous
    cycle but mark_seen failed (crash / network drop), it will be re-fetched
    as UNSEEN. Checking here prevents redundant classify + RAG API calls.
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM drafts WHERE message_id=?", (message_id,)
        ).fetchone()
    return row is not None


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["sources"] = json.loads(d.get("sources") or "[]")
    d["escalate"] = bool(d.get("escalate"))
    d["human_edited"] = bool(d.get("human_edited"))
    d["from"] = d.pop("sender", "")
    return d
