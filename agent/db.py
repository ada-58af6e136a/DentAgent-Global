"""
agent/db.py

SQLite persistence layer for the draft queue.
Replaces draft_queue.jsonl and processed_queue.jsonl.

WAL mode allows app.py (reader/updater) and email_handler.py (writer)
to operate concurrently without file-level locking or corruption.
INSERT OR IGNORE on message_id gives idempotent writes.
"""

import json
import math
import sqlite3
from datetime import datetime, timezone

from .paths import DATA_DIR

_DB_PATH = DATA_DIR / "drafts.db"


def get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_DRAFTS_MIGRATION_COLUMNS = {
    "confidence":        "REAL DEFAULT 0.0",
    "classify_elapsed":  "REAL",
    "rag_elapsed":       "REAL",
    "total_elapsed":     "REAL",
    "prompt_tokens":     "INTEGER DEFAULT 0",
    "output_tokens":     "INTEGER DEFAULT 0",
    "total_tokens":      "INTEGER DEFAULT 0",
    "estimated_cost_usd": "REAL DEFAULT 0.0",
    "used_fallback":     "INTEGER DEFAULT 0",
    "would_auto_send":   "INTEGER DEFAULT 0",
}


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

        # Migration: add columns introduced after the table already existed
        # in deployed dbs. CREATE TABLE IF NOT EXISTS above is a no-op on an
        # existing table, so new columns must be added explicitly.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(drafts)")}
        for col, ddl in _DRAFTS_MIGRATION_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE drafts ADD COLUMN {col} {ddl}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_health (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                last_poll_ts       TEXT,
                last_success_ts    TEXT,
                last_error         TEXT,
                consecutive_errors INTEGER DEFAULT 0,
                imap_status        TEXT DEFAULT 'unknown',
                smtp_status        TEXT DEFAULT 'unknown',
                updated_at         TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS live_demo_runs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT
            )
        """)


def save_draft(entry: dict) -> bool:
    """
    Insert one draft; silently ignores duplicates (idempotent by message_id).
    Returns True if inserted, False if already existed.

    entry may optionally include final_reply/human_edited (set when the
    auto-send path resolves a draft immediately) plus confidence, timing,
    and token/cost fields — all default to 0/None when absent so existing
    callers keep working unchanged.
    """
    init_db()
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT OR IGNORE INTO drafts
                (message_id, timestamp, sender, subject, body,
                 intent, language, escalate, draft_reply, sources,
                 retrieval_score, status, final_reply, human_edited,
                 processed_at, confidence, classify_elapsed, rag_elapsed,
                 total_elapsed, prompt_tokens, output_tokens, total_tokens,
                 estimated_cost_usd, used_fallback, would_auto_send)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            entry.get("final_reply"),
            int(entry.get("human_edited", False)),
            entry.get("processed_at"),
            entry.get("confidence", 0.0),
            entry.get("classify_elapsed"),
            entry.get("rag_elapsed"),
            entry.get("total_elapsed"),
            entry.get("prompt_tokens", 0),
            entry.get("output_tokens", 0),
            entry.get("total_tokens", 0),
            entry.get("estimated_cost_usd", 0.0),
            int(entry.get("used_fallback", False)),
            int(entry.get("would_auto_send", False)),
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


def update_health(imap_status: str = None, smtp_status: str = None,
                   error: str = None) -> dict:
    """
    Upsert the single system_health row.

    Called once per poll cycle in email_handler.run_loop(): a clean cycle
    passes imap_status='ok' and resets consecutive_errors; an exception
    passes error=str(ex) and increments it. Used by the Ops Dashboard to
    show "last poll Ns ago" / error streaks without tailing agent.log.

    Returns {"just_started_failing": bool, "just_recovered": bool} — whether
    THIS call represents a state transition, not just an ongoing state. Callers
    (agent/email_handler.py) use this to fire a Slack alert only on the edge
    (error just started / just cleared), not on every single poll cycle while
    an outage continues — otherwise a 10-minute outage at a 60s poll interval
    would be 10 separate Slack messages for one incident.
    """
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM system_health WHERE id=1").fetchone()
        if row is None:
            conn.execute("""
                INSERT INTO system_health
                    (id, last_poll_ts, last_success_ts, last_error,
                     consecutive_errors, imap_status, smtp_status, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                now if error is None else None,
                error,
                1 if error else 0,
                imap_status or "unknown",
                smtp_status or "unknown",
                now,
            ))
            return {"just_started_failing": error is not None, "just_recovered": False}

        prev_consecutive_errors = row["consecutive_errors"] or 0
        consecutive_errors = prev_consecutive_errors
        last_success_ts = row["last_success_ts"]
        last_error = row["last_error"]
        if error:
            consecutive_errors += 1
            last_error = error
        else:
            consecutive_errors = 0
            last_success_ts = now

        conn.execute("""
            UPDATE system_health
               SET last_poll_ts=?, last_success_ts=?, last_error=?,
                   consecutive_errors=?,
                   imap_status=COALESCE(?, imap_status),
                   smtp_status=COALESCE(?, smtp_status),
                   updated_at=?
             WHERE id=1
        """, (now, last_success_ts, last_error, consecutive_errors,
              imap_status, smtp_status, now))

    return {
        "just_started_failing": prev_consecutive_errors == 0 and consecutive_errors > 0,
        "just_recovered": prev_consecutive_errors > 0 and consecutive_errors == 0,
    }


def get_health() -> dict:
    """Return the current system_health row, or defaults if never written."""
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM system_health WHERE id=1").fetchone()
    if row is None:
        return {
            "last_poll_ts": None, "last_success_ts": None, "last_error": None,
            "consecutive_errors": 0, "imap_status": "unknown",
            "smtp_status": "unknown", "updated_at": None,
        }
    return dict(row)


def get_data_date_range() -> tuple:
    """
    Return (earliest_date, latest_date) as 'YYYY-MM-DD' strings across all
    drafts, or (None, None) if there's no timestamped data yet.

    Powers the Ops Dashboard's date-range picker default — defaulting to
    "last 7 days" would silently show an empty dashboard whenever the actual
    data is older than that (e.g. a dev DB last touched weeks ago), which
    looks like a bug rather than an empty range.
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT MIN(date(timestamp)) AS earliest, MAX(date(timestamp)) AS latest
              FROM drafts
             WHERE timestamp IS NOT NULL
        """).fetchone()
    return row["earliest"], row["latest"]


def get_daily_volume(start_date: str = None, end_date: str = None) -> list:
    """
    Return [{date, status, count}] — daily email volume grouped by status.

    start_date/end_date are inclusive 'YYYY-MM-DD' strings; omit either for
    an open-ended range. Powers the Ops Dashboard's date-range filter.
    """
    init_db()
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT date(timestamp) AS date, status, COUNT(*) AS count
              FROM drafts
             WHERE timestamp IS NOT NULL
               {"AND date(timestamp) >= ?" if start_date else ""}
               {"AND date(timestamp) <= ?" if end_date else ""}
             GROUP BY date(timestamp), status
             ORDER BY date
        """, tuple(d for d in (start_date, end_date) if d)).fetchall()
    return [dict(r) for r in rows]


def get_latency_summary(start_date: str = None, end_date: str = None) -> list:
    """Return [{date, avg_classify, avg_rag, avg_total}] per day, optionally date-filtered."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT date(timestamp) AS date,
                   AVG(classify_elapsed) AS avg_classify,
                   AVG(rag_elapsed)      AS avg_rag,
                   AVG(total_elapsed)    AS avg_total
              FROM drafts
             WHERE timestamp IS NOT NULL AND total_elapsed IS NOT NULL
               {"AND date(timestamp) >= ?" if start_date else ""}
               {"AND date(timestamp) <= ?" if end_date else ""}
             GROUP BY date(timestamp)
             ORDER BY date
        """, tuple(d for d in (start_date, end_date) if d)).fetchall()
    return [dict(r) for r in rows]


def _percentile(sorted_values: list, p: float) -> float:
    """Linear-interpolation percentile (numpy's default method) of a pre-sorted list."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def get_latency_percentiles(start_date: str = None, end_date: str = None) -> list:
    """
    Return [{date, p50_total, p95_total, p99_total}] per day, optionally date-filtered.

    SQLite has no native percentile function, so this pulls raw per-email
    total_elapsed values and computes percentiles in Python. Exists alongside
    get_latency_summary() (daily averages) specifically because an average
    hides tail latency — a handful of slow outliers a day won't move the
    average much but will show up clearly at p95/p99.
    """
    init_db()
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT date(timestamp) AS date, total_elapsed
              FROM drafts
             WHERE timestamp IS NOT NULL AND total_elapsed IS NOT NULL
               {"AND date(timestamp) >= ?" if start_date else ""}
               {"AND date(timestamp) <= ?" if end_date else ""}
             ORDER BY date(timestamp), total_elapsed
        """, tuple(d for d in (start_date, end_date) if d)).fetchall()

    by_date: dict = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r["total_elapsed"])

    return [
        {
            "date": date,
            "p50_total": round(_percentile(values, 50), 2),
            "p95_total": round(_percentile(values, 95), 2),
            "p99_total": round(_percentile(values, 99), 2),
        }
        for date, values in sorted(by_date.items())
    ]


def get_cost_summary(start_date: str = None, end_date: str = None) -> dict:
    """Return {daily: [...], by_intent: [...]} token/cost aggregates, optionally date-filtered."""
    init_db()
    date_params = tuple(d for d in (start_date, end_date) if d)
    with get_conn() as conn:
        daily = conn.execute(f"""
            SELECT date(timestamp) AS date,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(total_tokens)  AS total_tokens,
                   SUM(estimated_cost_usd) AS cost_usd
              FROM drafts
             WHERE timestamp IS NOT NULL
               {"AND date(timestamp) >= ?" if start_date else ""}
               {"AND date(timestamp) <= ?" if end_date else ""}
             GROUP BY date(timestamp)
             ORDER BY date
        """, date_params).fetchall()
        by_intent = conn.execute(f"""
            SELECT intent,
                   SUM(total_tokens) AS total_tokens,
                   SUM(estimated_cost_usd) AS cost_usd,
                   COUNT(*) AS count
              FROM drafts
             WHERE 1=1
               {"AND date(timestamp) >= ?" if start_date else ""}
               {"AND date(timestamp) <= ?" if end_date else ""}
             GROUP BY intent
             ORDER BY cost_usd DESC
        """, date_params).fetchall()
    return {
        "daily": [dict(r) for r in daily],
        "by_intent": [dict(r) for r in by_intent],
    }


def get_today_stats() -> dict:
    """Return today's (UTC) aggregate counts — powers the Ops Dashboard KPI row."""
    init_db()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total,
                   SUM(escalate) AS escalated,
                   SUM(CASE WHEN status='auto_sent' THEN 1 ELSE 0 END) AS auto_sent,
                   SUM(used_fallback) AS fallback_count,
                   SUM(would_auto_send) AS would_auto_send_count,
                   AVG(total_elapsed) AS avg_total_elapsed,
                   SUM(estimated_cost_usd) AS cost_usd
              FROM drafts
             WHERE date(timestamp) = date('now')
        """).fetchone()
    d = dict(row)
    for key in ("total", "escalated", "auto_sent", "fallback_count", "would_auto_send_count"):
        d[key] = d[key] or 0
    d["avg_total_elapsed"] = d["avg_total_elapsed"] or 0.0
    d["cost_usd"] = d["cost_usd"] or 0.0
    return d


def count_recent_auto_sends(window_minutes: int = 60) -> int:
    """
    Count real auto-sends (status='auto_sent') in the last window_minutes.

    Backs the auto-send rate circuit breaker in email_handler.py — a rolling
    count, not a persisted "tripped" flag, so there's no extra state to keep
    consistent with reality.
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) FROM drafts
             WHERE status='auto_sent'
               AND timestamp >= datetime('now', ?)
        """, (f'-{window_minutes} minutes',)).fetchone()
    return row[0]


def record_live_demo_run() -> None:
    """Log one Live Demo page click — backs count_recent_live_demo_runs()."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO live_demo_runs (timestamp) VALUES (?)",
            (datetime.now(timezone.utc).isoformat(),),
        )


def count_recent_live_demo_runs(window_minutes: int = 60) -> int:
    """
    Count Live Demo page runs in the last window_minutes — a global cap
    across all visitors (not per-session), same rolling-count pattern as
    count_recent_auto_sends(). Session-based limiting alone can be bypassed
    by opening a new incognito window; this can't be.
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) FROM live_demo_runs
             WHERE timestamp >= datetime('now', ?)
        """, (f'-{window_minutes} minutes',)).fetchone()
    return row[0]


def get_shadow_mode_calibration() -> list:
    """
    Return raw (intent, status, human_edited) for every human-reviewed draft
    that shadow mode marked would_auto_send=1.

    Kept as raw rows rather than pre-aggregated here so agent/analytics.py's
    report can classify outcomes using BOTH status and human_edited — status
    alone is ambiguous, since the "Approve" button in app.py doesn't force
    human_edited=False if the reviewer tweaked the text before clicking it.
    """
    init_db()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT intent, status, human_edited
              FROM drafts
             WHERE would_auto_send = 1
               AND status IN ('approved', 'edited', 'escalated')
        """).fetchall()
    return [dict(r) for r in rows]


def get_recent_auto_sent(limit: int = 20) -> list:
    """Return the most recent auto-sent drafts, newest first — audit trail."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM drafts
             WHERE status='auto_sent'
             ORDER BY id DESC
             LIMIT ?
        """, (limit,)).fetchall()
    return [_row_to_dict(row) for row in rows]


def _ensure_archive_table(conn: sqlite3.Connection) -> None:
    """
    Create drafts_archive with the exact same schema as drafts — derived
    dynamically from sqlite_master rather than a second hand-written CREATE
    TABLE. drafts' schema has grown by migration several times already
    (confidence, timing, tokens, would_auto_send, ...); a hand-duplicated
    archive schema would silently drift out of sync the next time it does.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts_archive'"
    ).fetchone()
    if exists:
        return
    create_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='drafts'"
    ).fetchone()[0]
    conn.execute(create_sql.replace("CREATE TABLE drafts", "CREATE TABLE drafts_archive", 1))


def archive_old_drafts(days: int = 90) -> int:
    """
    Move terminal-state drafts (everything except pending_review) older than
    `days` into drafts_archive, keeping the live `drafts` table lean for Ops
    Dashboard queries. pending_review rows are never touched regardless of
    age — those are still-actionable work, not history.

    Not run automatically: unlike auto-send/circuit-breaker logic, archival
    isn't latency-sensitive or safety-critical, so it's a periodic maintenance
    task (see scripts/archive_old_drafts.py) rather than baked into
    email_handler.run_loop().

    Atomic — INSERT and DELETE share one connection/transaction (commits
    together on success via the `with` block, same as everywhere else in
    this module), so a failure can't duplicate rows into both tables or lose
    them from both.
    """
    init_db()
    cutoff = f"-{days} days"
    with get_conn() as conn:
        _ensure_archive_table(conn)
        conn.execute("""
            INSERT INTO drafts_archive
            SELECT * FROM drafts
             WHERE status != 'pending_review'
               AND date(timestamp) < date('now', ?)
        """, (cutoff,))
        cur = conn.execute("""
            DELETE FROM drafts
             WHERE status != 'pending_review'
               AND date(timestamp) < date('now', ?)
        """, (cutoff,))
        return cur.rowcount


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["sources"] = json.loads(d.get("sources") or "[]")
    d["escalate"] = bool(d.get("escalate"))
    d["human_edited"] = bool(d.get("human_edited"))
    d["from"] = d.pop("sender", "")
    return d
