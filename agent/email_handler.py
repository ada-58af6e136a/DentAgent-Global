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
import re
import signal
import time
import os
import smtplib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime, timezone
from dotenv import load_dotenv

from .classifier import classify_intent
from .rag_chain import generate_reply
from .analytics import log_interaction
from .db import (
    save_draft, is_already_queued, update_health,
    count_recent_auto_sends, mark_as_processed,
)
from .api_client import start_usage_tracking, get_usage_totals
from .alerts import send_slack_alert
from .auto_send_rules import meets_auto_send_criteria, parse_to_address
from .logger import get_logger

log = get_logger(__name__)

load_dotenv()

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# ── Automated-sender pre-filter ─────────────────────────────────────────────
# Every unread email previously got a full classify_intent() call (and, if
# not escalated, a full RAG pipeline: query rewrite + HyDE + embedding +
# rerank + reply generation) with zero relevance filtering first — including
# platform notifications like Google's own "privacy settings" / "Terms of
# Service" emails, confirmed hitting a real inbox during testing. Filtering
# on email CONTENT (subject/body heuristics) risks the opposite failure —
# silently dropping a real customer inquiry that happens to use the wrong
# words — so this only matches structural sender-address signals with no
# ambiguity: a known automated local-part prefix, or a known automated
# domain. Anything not matched here still goes through the full pipeline.
AUTOMATED_SENDER_PATTERNS = {
    s.strip().lower() for s in os.getenv(
        "AUTOMATED_SENDER_PATTERNS",
        "noreply@,no-reply@,donotreply@,do-not-reply@,mailer-daemon@,"
        "postmaster@,accounts.google.com"
    ).split(",") if s.strip()
}


def _is_automated_sender(raw_from: str) -> bool:
    """
    True if the sender matches a known automated/notification pattern.

    Local-part patterns (end with "@", e.g. "noreply@") match as a prefix
    of the full address. Bare domain patterns (e.g. "accounts.google.com")
    match the address's domain exactly or as a subdomain — never a plain
    substring check, to avoid an unlikely-but-possible false match against
    part of a real customer's address.
    """
    if not AUTOMATED_SENDER_PATTERNS:
        return False
    address = parse_to_address(raw_from).lower()
    domain = address.split("@")[-1] if "@" in address else ""
    for pattern in AUTOMATED_SENDER_PATTERNS:
        if pattern.endswith("@"):
            if address.startswith(pattern):
                return True
        elif domain == pattern or domain.endswith("." + pattern):
            return True
    return False


# ── Auto-send ─────────────────────────────────────────────────────────────────
# Off by default. When enabled, emails meeting all three thresholds in
# agent.auto_send_rules are sent immediately without human review.
#
# Shadow mode is always on and needs no toggle: meets_auto_send_criteria() is
# evaluated for every email regardless of AUTO_SEND_ENABLED, and the result is
# persisted as drafts.would_auto_send. Since every human-reviewed draft already
# has a real outcome (approved/edited/escalated), this silently accumulates
# labeled calibration data for free — whether or not the feature is ever
# turned on.
AUTO_SEND_ENABLED = os.getenv("AUTO_SEND_ENABLED", "false").strip().lower() == "true"
# Circuit breaker: caps real auto-sends per rolling hour. Stateless — recomputed
# from the DB each time via count_recent_auto_sends(), not a persisted flag.
AUTO_SEND_MAX_PER_HOUR = int(os.getenv("AUTO_SEND_MAX_PER_HOUR", "20"))
# Serializes the entire check-breaker -> send -> record sequence for
# auto-send. Without this, concurrent ThreadPoolExecutor workers can each
# read count_recent_auto_sends() before any of them has recorded a send,
# letting the batch overshoot AUTO_SEND_MAX_PER_HOUR by up to (workers-1).
# Trading a little throughput for correctness is the right call for an
# irreversible action sent to a real customer.
_auto_send_lock = threading.Lock()

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


class _HTMLTextExtractor(HTMLParser):
    """Minimal dependency-free HTML->text: collects text nodes, skips
    script/style content, and inserts a newline at block-level tags so
    paragraphs don't run together into one wall of text."""
    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP_TAGS = {"script", "style"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    """Crude but dependency-free HTML->text fallback for emails with no
    text/plain part (some CRM/webform-forwarded mail sends HTML-only).
    Not meant to be a faithful render — just to avoid the actual failure
    mode this replaces: silently losing the entire email body and leaving
    the classifier/RAG pipeline with only the subject line to work with.
    """
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return html  # malformed markup — pass it through raw rather than lose the content
    text = parser.get_text()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_body(msg):
    """
    Extract plain text body from email message.

    Prefers text/plain; falls back to converting text/html when no
    text/plain part exists at all, rather than returning an empty body.
    Previously an HTML-only email (no text/plain alternative) vanished
    entirely — classify_intent()/generate_reply() would see only the
    subject line, with zero visibility into the actual request.
    """
    body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if content_type == "text/plain" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    body = _decode_payload(payload, part)
            elif content_type == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload:
                    html_body = _decode_payload(payload, part)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            if msg.get_content_type() == "text/html":
                html_body = _decode_payload(payload, msg)
            else:
                body = _decode_payload(payload, msg)
        elif isinstance(msg.get_payload(), str):
            body = msg.get_payload()

    if body:
        return body.strip()
    if html_body:
        return _html_to_text(html_body)
    return ""


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


def _circuit_breaker_tripped() -> bool:
    """True if the auto-send rate cap has been hit in the last rolling hour."""
    return count_recent_auto_sends(60) >= AUTO_SEND_MAX_PER_HOUR


# Tracks whether the last check already found the breaker tripped, so the
# Slack alert fires once on the transition (not once per email blocked while
# it stays tripped). process_email() runs concurrently via ThreadPoolExecutor
# (Fix F), so this needs its own lock — separate from _smtp_lock.
_breaker_alert_lock = threading.Lock()
_breaker_was_tripped = False


def _check_circuit_breaker() -> bool:
    """Like _circuit_breaker_tripped(), but also fires an edge-triggered
    Slack alert on trip/reset. Use this at the actual send-decision point;
    use the plain function above anywhere a side-effect-free check is fine."""
    global _breaker_was_tripped
    tripped = _circuit_breaker_tripped()
    with _breaker_alert_lock:
        if tripped and not _breaker_was_tripped:
            _breaker_was_tripped = True
            send_slack_alert(
                f":red_circle: DentAgent auto-send circuit breaker tripped "
                f"(>= {AUTO_SEND_MAX_PER_HOUR} sends in the last hour)."
            )
        elif not tripped and _breaker_was_tripped:
            _breaker_was_tripped = False
            send_slack_alert(":white_check_mark: DentAgent auto-send circuit breaker reset.")
    return tripped


def process_email(email_data):
    """Classify intent and generate reply draft for one email."""
    t0 = time.perf_counter()
    subject = email_data["subject"][:50]
    log.debug("Processing: '%s'", subject)

    start_usage_tracking()

    # Combine subject + body so classifier has context even when body is short/empty
    text_for_classifier = (email_data["subject"] + "\n" + email_data["body"]).strip()

    t_classify = time.perf_counter()
    classification = classify_intent(text_for_classifier)
    classify_elapsed = time.perf_counter() - t_classify

    intent = classification.get("intent", "OTHER")
    language = classification.get("language", "en")
    escalate = classification.get("escalate", True)
    confidence = classification.get("confidence", 0.0)
    log.debug("classify done: intent=%s lang=%s escalate=%s confidence=%.2f (%.1fs)",
              intent, language, escalate, confidence, classify_elapsed)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": email_data["message_id"],
        "from": email_data["from"],
        "subject": email_data["subject"],
        "body": email_data["body"],
        "intent": intent,
        "language": language,
        "escalate": escalate,
        "confidence": confidence,
        "draft_reply": None,
        "sources": [],
        "retrieval_score": 0.0,
        "status": "pending_review",
    }

    rag_elapsed = 0.0
    if not escalate:
        t_rag = time.perf_counter()
        result = generate_reply(
            email_data["body"], language, intent,
            rewritten_query=classification.get("rewritten_query"),
            hypothesis=classification.get("hypothesis"),
        )
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

    action = "escalated" if escalate else "pending"

    # Shadow mode: always compute and persist whether this email *would*
    # qualify, regardless of AUTO_SEND_ENABLED — see the comment on that flag.
    would_send = meets_auto_send_criteria(
        intent, confidence, entry["retrieval_score"], escalate, email_data["from"]
    )
    entry["would_auto_send"] = would_send

    usage = get_usage_totals()
    entry["classify_elapsed"] = classify_elapsed
    entry["rag_elapsed"] = rag_elapsed
    entry["prompt_tokens"] = usage["prompt_tokens"]
    entry["output_tokens"] = usage["output_tokens"]
    entry["total_tokens"] = usage["total_tokens"]
    entry["estimated_cost_usd"] = usage["cost_usd"]
    entry["used_fallback"] = usage["fallback_calls"] > 0
    # Measured up to this point, not through the SMTP round-trip below for
    # auto-sent mail — a few hundred ms of latency-metric imprecision is a
    # fully acceptable trade for the ordering fix directly below.
    entry["total_elapsed"] = time.perf_counter() - t0

    # Fix (2026-07): establish idempotency BEFORE any irreversible action.
    # Previously send_reply() ran before this save; a crash or DB error
    # between a successful send and the write left is_already_queued()
    # returning False, so the next poll cycle would re-fetch and genuinely
    # re-send the same email. Saving now (status=pending_review) means any
    # failure past this point leaves an ordinary pending-review draft
    # behind — is_already_queued() already returns True on the next cycle
    # either way, so reprocessing (and re-sending) can no longer happen.
    save_draft(entry)

    if AUTO_SEND_ENABLED and would_send:
        with _auto_send_lock:
            if _check_circuit_breaker():
                log.warning(
                    "Auto-send circuit breaker tripped (>= %d in the last hour) — "
                    "leaving '%s' in pending_review",
                    AUTO_SEND_MAX_PER_HOUR, subject,
                )
            else:
                to_address = parse_to_address(email_data["from"])
                sent = send_reply(
                    to_address=to_address,
                    subject=email_data["subject"],
                    reply_body=entry["draft_reply"],
                    original_message_id=email_data["message_id"],
                )
                if sent:
                    updated = mark_as_processed(
                        email_data["message_id"], "auto_sent",
                        entry["draft_reply"], False,
                    )
                    if updated:
                        entry.update(updated)
                    action = "auto_sent"
                    log.info("Auto-sent reply for '%s' (intent=%s confidence=%.2f score=%.3f)",
                              subject, intent, confidence, entry["retrieval_score"])
                else:
                    log.warning("Auto-send eligible but send_reply failed — "
                                "leaving '%s' in pending_review", subject)

    log_interaction(
        email_data=email_data,
        classification={
            "intent": intent,
            "language": language,
            "escalate": escalate,
            "confidence": confidence,
        },
        draft_reply=entry["draft_reply"],
        sources=entry["sources"],
        final_reply=entry.get("final_reply"),
        action=action,
    )

    log.info(
        "Processed '%s' | intent=%s lang=%s escalate=%s score=%.3f | "
        "classify=%.1fs rag=%.1fs total=%.1fs",
        subject, intent, language, escalate,
        entry["retrieval_score"], classify_elapsed, rag_elapsed, entry["total_elapsed"],
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
            health_result = update_health(imap_status="ok")
            if health_result["just_recovered"]:
                send_slack_alert(":white_check_mark: DentAgent IMAP recovered.")

            if not emails:
                log.debug("No new emails")
            else:
                log.info("Found %d new email(s)", len(emails))

                # Fix H: split into "already saved" vs "needs processing"
                to_process = []
                for e, mid in zip(emails, raw_mids):
                    if _is_automated_sender(e["from"]):
                        log.info(
                            "Skipping automated/notification sender (no "
                            "classify/RAG calls made): '%s' from %s",
                            e["subject"][:40], e["from"][:60],
                        )
                        try:
                            mark_seen(mail, mid)
                        except Exception as ex:
                            log.warning("mark_seen failed: %s", ex)
                    elif is_already_queued(e["message_id"]):
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
            health_result = update_health(imap_status="error", error=str(ex))
            if health_result["just_started_failing"]:
                send_slack_alert(f":red_circle: DentAgent IMAP error: {ex}")
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
            health_result = update_health(smtp_status="ok")
            if health_result["just_recovered"]:
                send_slack_alert(":white_check_mark: DentAgent SMTP recovered.")
            return True
        except Exception as e:
            global _smtp_conn
            _smtp_conn = None   # force fresh connection on next attempt
            log.error("Failed to send reply to %s: %s", to_address, e, exc_info=True)
            health_result = update_health(smtp_status="error", error=f"SMTP send failed: {e}")
            if health_result["just_started_failing"]:
                send_slack_alert(f":red_circle: DentAgent SMTP error: {e}")
            return False


if __name__ == "__main__":
    run_loop(interval_seconds=60)