"""
email_handler.py

Handles inbound email reading via IMAP.
Polls the inbox every 60 seconds for unread emails,
passes each through classifier and rag_chain,
and saves drafts to a local queue file (draft_queue.jsonl).
"""

import imaplib
import email
import json
import time
import os
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime, timezone
from dotenv import load_dotenv

from .classifier import classify_intent
from .rag_chain import generate_reply
from .analytics import log_interaction

load_dotenv()

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
DRAFT_QUEUE = "data/draft_queue.jsonl"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

Path("data").mkdir(exist_ok=True)


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


def fetch_unread_emails():
    """Connect to inbox and fetch all unread emails."""
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    email_user = os.getenv("GMAIL_EMAIL")
    email_pass = os.getenv("GMAIL_PASSWORD")
    if not email_user or not email_pass:
        raise ValueError("GMAIL_EMAIL and GMAIL_PASSWORD must be set in .env")
    mail.login(email_user, email_pass)
    mail.select("inbox")

    _, message_ids = mail.search(None, "UNSEEN")
    emails = []

    for mid in message_ids[0].split():
        _, data = mail.fetch(mid, "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        # Mark as read
        mail.store(mid, "+FLAGS", "\\Seen")

        email_data = {
            "message_id": decode_str(msg.get("Message-ID", "")),
            "from": decode_str(msg.get("From", "")),
            "subject": decode_str(msg.get("Subject", "")),
            "body": extract_body(msg),
            "date": msg.get("Date", ""),
            "raw_message_id": mid.decode()
        }
        emails.append(email_data)
        print(f"  Fetched: {email_data['subject'][:50]} from {email_data['from'][:40]}")

    mail.logout()
    return emails


def save_to_queue(entry):
    """Append one processed email to the draft queue file."""
    with open(DRAFT_QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def process_email(email_data):
    """Classify intent and generate reply draft for one email."""
    print(f"\nProcessing: {email_data['subject'][:50]}")

    # Combine subject + body so classifier has context even when body is short/empty
    text_for_classifier = (email_data["subject"] + "\n" + email_data["body"]).strip()
    classification = classify_intent(text_for_classifier)
    intent = classification.get("intent", "OTHER")
    language = classification.get("language", "en")
    escalate = classification.get("escalate", True)

    print(f"  Intent: {intent} | Language: {language} | Escalate: {escalate}")

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
        "status": "pending_review"
    }

    if not escalate:
        result = generate_reply(email_data["body"], language, intent)
        entry["retrieval_score"] = result.get("retrieval_score", 0.0)

        if result.get("kb_miss"):
            # No KB chunk passed the relevance threshold — escalate instead of guessing
            escalate = True
            entry["escalate"] = True
            print(f"  KB miss (best score {result['retrieval_score']:.3f}) — forcing escalation")
        else:
            entry["draft_reply"] = result["reply"]
            entry["sources"] = result["sources"]
            print(f"  Draft generated ({len(result['reply'])} chars, score {result['retrieval_score']:.3f})")

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
            "review your enquiry and follow up within 1 business day."
        )
        print(f"  Escalated — acknowledgement draft added")

    save_to_queue(entry)

    log_interaction(
    email_data=email_data,
    classification={
        "intent": intent,
        "language": language,
        "escalate": escalate,
        "confidence": classification.get("confidence", 0.0)
    },
    draft_reply=entry["draft_reply"],
    sources=entry["sources"],
    action="escalated" if escalate else "pending"
    )
    
    return entry


def run_loop(interval_seconds=60):
    """Main polling loop — checks inbox every interval_seconds."""
    print(f"Email handler started. Checking inbox every {interval_seconds}s.")
    print(f"Drafts will be saved to: {DRAFT_QUEUE}")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Checking inbox...")
            emails = fetch_unread_emails()

            if not emails:
                print("  No new emails.")
            else:
                print(f"  Found {len(emails)} new email(s).")
                for e in emails:
                    process_email(e)

        except Exception as ex:
            print(f"  Error: {ex}")

        time.sleep(interval_seconds)


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

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = email_user
        msg["To"] = to_address
        msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        msg["In-Reply-To"] = original_message_id
        msg["References"] = original_message_id

        msg.attach(MIMEText(reply_body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(email_user, email_pass)
            server.sendmail(email_user, to_address, msg.as_string())

        print(f"  Sent reply to {to_address}")
        return True

    except Exception as e:
        print(f"  Failed to send: {e}")
        return False


if __name__ == "__main__":
    run_loop(interval_seconds=60)