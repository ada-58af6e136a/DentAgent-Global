"""
email_handler.py

Handles inbound email reading via IMAP.
Polls the inbox every 60 seconds for unread emails,
passes each through classifier and rag_chain,
and saves drafts to SQLite via agent.db.

Fix A: emails are marked \\Seen only after successful queue write.
Fix B: draft queue is SQLite (ACID, no race conditions).
Fix E: single IMAP connection reused across cycles (NOOP keepalive).
Fix F: multiple emails processed concurrently via ThreadPoolExecutor.
Fix H: already-queued emails skipped before API calls (idempotent).
"""

import imaplib
import email
import signal
import time
import os
import smtplib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime, timezone
from dotenv import load_dotenv

from .classifier import classify_intent
from .rag_chain import generate_reply
from .analytics import log_interaction
from .db import save_draft, is_already_queued
from .logger import get_logger

log = get_logger(__name__)

load_dotenv()

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# ── Fix I: SMTP connection pool ──────────────────────────────────────────────
# Reuse one authenticated SMTP connection across successive sends.
# NOOP probe detects stale connections; reconnect transparently on failure.
_smtp_lock = threading.Lock()
_smtp_conn: smtplib.SMTP | None = None

# ── Fix J: Graceful shutdown ─────────────────────────────────────────────────
# Set by signal handler; run_loop() checks it before each new cycle and uses
# it as the interruptible sleep, so Ctrl-C / SIGTERM drains the current batch
# then exits cleanly instead of leaving in-flight emails half-processed.
_stop_event = threading.Event()


def _handle_signal(signum: int, frame) -> None:
    log.info("Signal %d received — finishing current batch then stopping", signum)
    _stop_event.set()


def decode_str(value):
    """Decode email header strings, handling multi-part encoded headers."""
    if value is None:
        return ""
    parts = decode_header(value)
    result = []
    for decoded, encoding in parts:
        if isinstance(decoded, bytes):
            result.append(decoded.decode(encoding or "utf-8", errors="ignore"))
        else:
            result.append(decoded)
    return "".join(result)


def _decode_payload(payload: bytes, part) -> str:
    """Decode bytes using the charset declared in the MIME part."""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def extract_body(msg):
    """Extract plain text body from email message."""
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    body = _decode_payload(payload, part)
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = _decode_payload(payload, msg)
        elif isinstance(msg.get_payload(), str):
            body = msg.get_payload()

    return body.strip() if body else ""


def _connect() -> imaplib.IMAP4_SSL:
    """Open and authenticate an IMAP connection."""
    email_user = os.getenv("GMAIL_EMAIL")
    email_pass = os.getenv("GMAIL_PASSWORD")
    if not email_user or not email_pass:
        raise ValueError("GMAIL_EMAIL and GMAIL_PASSWORD must be set in .env")
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(email_user, email_pass)
    return mail


def _keepalive(mail: imaplib.IMAP4_SSL) -> imaplib.IMAP4_SSL:
    """
    Send NOOP to keep the connection alive; silently reconnect on failure.

    Fix E: IMAP servers drop idle connections after ~30 min. A NOOP every
    60 s resets the server-side idle timer at negligible cost (< 1 ms round
    trip), avoiding the TLS handshake overhead of reconnecting each cycle.
    """
    try:
        mail.noop()
        return mail
    except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError):
        log.warning("IMAP connection lost — reconnecting")
        try:
            mail.logout()
        except Exception:
            pass
        return _connect()


def fetch_unread_emails(mail: imaplib.IMAP4_SSL) -> tuple:
    """
    Fetch all UNSEEN messages. Does NOT mark them as read.
    Returns (emails, raw_mids) so the caller can mark each
    message seen only after it has been successfully processed.
    """
    mail.select("inbox")
    _, message_ids = mail.search(None, "UNSEEN")
    emails = []
    raw_mids = []

    for mid in message_ids[0].split():
        _, data = mail.fetch(mid, "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        email_data = {
            "message_id": decode_str(msg.get("Message-ID", "")),
            "from": decode_str(msg.get("From", "")),
            "subject": decode_str(msg.get("Subject", "")),
            "body": extract_body(msg),
            "date": msg.get("Date", ""),
            "raw_message_id": mid.decode(),
        }
        emails.append(email_data)
        raw_mids.append(mid)
        log.debug("Fetched: '%s' from %s",
                  email_data["subject"][:50], email_data["from"][:40])

    return emails, raw_mids


def mark_seen(mail: imaplib.IMAP4_SSL, mid: bytes) -> None:
    """Mark a single message as read on the server."""
    mail.store(mid, "+FLAGS", "\\Seen")


def process_email(email_data):
    """Classify intent and generate reply draft for one email."""
    t0 = time.perf_counter()
    subject = email_data["subject"][:50]
    log.debug("Processing: '%s'", subject)

    # Combine subject + body so classifier has context even when body is short/empty
    text_for_classifier = (email_data["subject"] + "\n" + email_data["body"]).strip()

    t_classify = time.perf_counter()
    classification = classify_intent(text_for_classifier)
    classify_elapsed = time.perf_counter() - t_classify

    intent = classification.get("intent", "OTHER")
    language = classification.get("language", "en")
    escalate = classification.get("escalate", True)
    log.debug("classify done: intent=%s lang=%s escalate=%s (%.1fs)",
              intent, language, escalate, classify_elapsed)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": email_data["message_id"],
        "from": email_data["from"],
        "subject": email_data["subject"],
        "body": email_data["body"],
        "intent": intent,
        "language": language,
        "escalate": escalate,
        "draft_reply": None,
        "sources": [],
        "retrieval_score": 0.0,
        "status": "pending_review",
    }

    rag_elapsed = 0.0
    if not escalate:
        t_rag = time.perf_counter()
        result = generate_reply(email_data["body"], language, intent)
        rag_elapsed = time.perf_counter() - t_rag
        entry["retrieval_score"] = result.get("retrieval_score", 0.0)

        if result.get("kb_miss"):
            escalate = True
            entry["escalate"] = True
            log.warning("KB miss score=%.3f — forcing escalation for '%s'",
                        result["retrieval_score"], subject)
        else:
            entry["draft_reply"] = result["reply"]
            entry["sources"] = result["sources"]
            log.debug("rag done: %d chars score=%.3f (%.1fs)",
                      len(result["reply"]), result["retrieval_score"], rag_elapsed)

    if escalate:
        ack_templates = {
            "zh": "感谢您的来信。我们的专业团队将在1个工作日内跟进处理您的问题。",
            "fr": (
                "Merci pour votre message. Notre équipe spécialisée "
                "examinera votre demande et vous répondra dans un délai d'un jour ouvrable."
            ),
            "de": (
                "Vielen Dank für Ihre Nachricht. Unser Fachteam wird "
                "Ihre Anfrage prüfen und sich innerhalb eines Werktages bei Ihnen melden."
            ),
            "nl": (
                "Bedankt voor uw bericht. Ons gespecialiseerde team zal "
                "uw verzoek bekijken en u binnen één werkdag terugkoppelen."
            ),
            "es": (
                "Gracias por su mensaje. Nuestro equipo especializado "
                "revisará su consulta y le responderá en un plazo de un día hábil."
            ),
        }
        entry["draft_reply"] = ack_templates.get(
            language,
            "Thank you for your message. Our specialist team will "
            "review your enquiry and follow up within 1 business day.",
        )
        log.debug("escalated — ack template added (lang=%s)", language)

    save_draft(entry)

    log_interaction(
        email_data=email_data,
        classification={
            "intent": intent,
            "language": language,
            "escalate": escalate,
            "confidence": classification.get("confidence", 0.0),
        },
        draft_reply=entry["draft_reply"],
        sources=entry["sources"],
        action="escalated" if escalate else "pending",
    )

    total_elapsed = time.perf_counter() - t0
    log.info(
        "Processed '%s' | intent=%s lang=%s escalate=%s score=%.3f | "
        "classify=%.1fs rag=%.1fs total=%.1fs",
        subject, intent, language, escalate,
        entry["retrieval_score"], classify_elapsed, rag_elapsed, total_elapsed,
    )

    return entry


def run_loop(interval_seconds=60, max_workers=5):
    """
    Main polling loop — checks inbox every interval_seconds.

    Fix A: mark_seen only after process_email succeeds.
    Fix E: single IMAP connection reused across all cycles (NOOP keepalive).
    Fix F: emails processed concurrently via ThreadPoolExecutor.
           mark_seen called on the main thread after all futures settle
           (IMAP is not thread-safe; keeping it on one thread is correct).
    Fix H: emails already in the DB are skipped before any API call,
           preventing wasted classify+RAG work on duplicate fetches.
    Fix J: SIGINT/SIGTERM trigger a graceful drain — the current batch
           finishes, IMAP is closed cleanly, then the process exits.
    """
    # Fix J: register signal handlers so Ctrl-C / SIGTERM set _stop_event
    # instead of raising KeyboardInterrupt mid-batch.
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("Email handler started. Polling every %ds.", interval_seconds)

    mail = _connect()   # Fix E: connect once, reuse across cycles

    while not _stop_event.is_set():
        try:
            mail = _keepalive(mail)   # Fix E: NOOP; reconnects transparently

            log.debug("Polling inbox...")
            emails, raw_mids = fetch_unread_emails(mail)

            if not emails:
                log.debug("No new emails")
            else:
                log.info("Found %d new email(s)", len(emails))

                # Fix H: split into "already saved" vs "needs processing"
                to_process = []
                for e, mid in zip(emails, raw_mids):
                    if is_already_queued(e["message_id"]):
                        log.warning(
                            "Duplicate re-fetch (already queued): '%s' — "
                            "skipping API calls, marking seen",
                            e["subject"][:40],
                        )
                        try:
                            mark_seen(mail, mid)
                        except Exception as ex:
                            log.warning("mark_seen failed: %s", ex)
                    else:
                        to_process.append((e, mid))

                if to_process:
                    workers = min(max_workers, len(to_process))
                    log.info("Processing %d email(s) with %d worker(s)",
                             len(to_process), workers)

                    # Fix F: concurrent classify + RAG for independent emails.
                    # Results collected first so mark_seen runs on the main
                    # thread (IMAP connection is not thread-safe).
                    successful_mids = []

                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        future_to_pair = {
                            pool.submit(process_email, e): (e, mid)
                            for e, mid in to_process
                        }
                        for future in as_completed(future_to_pair):
                            e, mid = future_to_pair[future]
                            try:
                                future.result()
                                successful_mids.append(mid)
                            except Exception as ex:
                                log.error(
                                    "Failed to process '%s' — will retry next cycle",
                                    e["subject"][:40],
                                    exc_info=True,
                                )

                    # Fix A + F: mark seen on main thread after all workers done
                    for mid in successful_mids:
                        try:
                            mark_seen(mail, mid)
                        except Exception as ex:
                            log.warning("mark_seen failed: %s", ex)

        except Exception as ex:
            log.error("Loop error — reconnecting", exc_info=True)
            try:
                mail.logout()
            except Exception:
                pass
            mail = _connect()

        # Fix J: interruptible sleep — wakes immediately when _stop_event is
        # set so the loop condition is re-evaluated without waiting out the
        # full interval.
        _stop_event.wait(interval_seconds)

    # Fix J: graceful exit — close IMAP cleanly after the last batch
    log.info("Stop signal received — closing IMAP connection and exiting")
    try:
        mail.logout()
    except Exception:
        pass
    log.info("Email handler stopped.")


def _get_or_create_smtp(email_user: str, email_pass: str) -> smtplib.SMTP:
    """Return the cached SMTP connection, creating or reconnecting as needed.

    Must be called with _smtp_lock already held.
    NOOP probes the connection; on failure the old socket is discarded and a
    fresh TLS session is established — one handshake instead of one per send.
    """
    global _smtp_conn
    if _smtp_conn is not None:
        try:
            _smtp_conn.noop()
        except Exception:
            log.warning("SMTP connection stale — reconnecting")
            try:
                _smtp_conn.quit()
            except Exception:
                pass
            _smtp_conn = None

    if _smtp_conn is None:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(email_user, email_pass)
        _smtp_conn = server
        log.debug("SMTP connection established")

    return _smtp_conn


def send_reply(to_address: str, subject: str,
               reply_body: str, original_message_id: str) -> bool:
    """
    Send a reply email via Gmail SMTP.
    Threads the reply to the original email using In-Reply-To header.

    Returns True if sent successfully, False otherwise.
    """
    email_user = os.getenv("GMAIL_EMAIL")
    email_pass = os.getenv("GMAIL_PASSWORD")
    if not email_user or not email_pass:
        raise ValueError("GMAIL_EMAIL and GMAIL_PASSWORD must be set in .env")

    msg = MIMEMultipart("alternative")
    msg["From"] = email_user
    msg["To"] = to_address
    msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
    msg["In-Reply-To"] = original_message_id
    msg["References"] = original_message_id
    msg.attach(MIMEText(reply_body, "plain", "utf-8"))

    # Fix I: hold the lock for the full send so the shared connection is
    # never used by two callers simultaneously.
    with _smtp_lock:
        try:
            server = _get_or_create_smtp(email_user, email_pass)
            server.sendmail(email_user, to_address, msg.as_string())
            log.info("Reply sent to %s", to_address)
            return True
        except Exception as e:
            global _smtp_conn
            _smtp_conn = None   # force fresh connection on next attempt
            log.error("Failed to send reply to %s: %s", to_address, e, exc_info=True)
            return False


if __name__ == "__main__":
    run_loop(interval_seconds=60)