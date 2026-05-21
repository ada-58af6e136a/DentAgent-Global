"""
app.py

Streamlit review dashboard for the dental CS agent.
Shows pending drafts from draft_queue.jsonl.
CS staff can Approve, Edit, or Escalate each draft.
"""

import json
import os
import streamlit as st
from pathlib import Path
from datetime import datetime, timezone
from agent.analytics import log_interaction
from agent.email_handler import send_reply

DRAFT_QUEUE = "data/draft_queue.jsonl"
PROCESSED_QUEUE = "data/processed_queue.jsonl"

st.set_page_config(
    page_title="Dental CS Agent — Review Dashboard",
    layout="wide"
)

st.title("Dental CS Agent — Review Dashboard")


def load_pending_drafts():
    """Load all drafts with status 'pending_review'."""
    drafts = []
    if not Path(DRAFT_QUEUE).exists():
        return drafts
    with open(DRAFT_QUEUE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                if entry.get("status") == "pending_review":
                    drafts.append(entry)
    return drafts


def mark_as_processed(message_id: str, action: str,
                       final_reply: str, human_edited: bool):
    """Move a draft from pending to processed and update analytics."""
    drafts = []
    target = None

    if Path(DRAFT_QUEUE).exists():
        with open(DRAFT_QUEUE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("message_id") == message_id:
                    entry["status"] = action
                    entry["final_reply"] = final_reply
                    entry["human_edited"] = human_edited
                    entry["processed_at"] = datetime.now(
                        timezone.utc).isoformat()
                    target = entry
                else:
                    drafts.append(entry)

    # Rewrite queue without the processed entry
    with open(DRAFT_QUEUE, "w", encoding="utf-8") as f:
        for d in drafts:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    # Append to processed queue
    if target:
        with open(PROCESSED_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps(target, ensure_ascii=False) + "\n")

        # Log to analytics
        log_interaction(
            email_data={
                "message_id": target.get("message_id", ""),
                "from": target.get("from", ""),
                "subject": target.get("subject", ""),
            },
            classification={
                "intent": target.get("intent", "OTHER"),
                "language": target.get("language", "en"),
                "escalate": target.get("escalate", True),
                "confidence": target.get("confidence", 0.0),
            },
            draft_reply=target.get("draft_reply", ""),
            sources=target.get("sources", []),
            human_edited=human_edited,
            final_reply=final_reply,
            action=action
        )


# ── Main dashboard ──────────────────────────────────────────

drafts = load_pending_drafts()

if not drafts:
    st.info("No pending drafts. The agent will populate this list "
            "as new emails arrive.")
    st.caption(f"Queue file: {DRAFT_QUEUE}")
else:
    st.markdown(f"**{len(drafts)} draft(s) awaiting review**")
    st.divider()

    for i, draft in enumerate(drafts):
        intent = draft.get("intent", "OTHER")
        language = draft.get("language", "en")
        escalate = draft.get("escalate", False)
        subject = draft.get("subject", "(no subject)")
        sender = draft.get("from", "")
        body = draft.get("body", "")
        draft_reply = draft.get("draft_reply", "")
        message_id = draft.get("message_id", "")
        sources = draft.get("sources", [])

        # Colour-code by intent
        intent_colours = {
            "PRICING": "🟢", "MATERIAL": "🔵",
            "PROGRESS": "🟡", "TECHNICAL": "🟠",
            "REWORK": "🔴", "BILLING": "🟣", "OTHER": "⚪"
        }
        icon = intent_colours.get(intent, "⚪")

        with st.expander(
            f"{icon} [{intent}] {subject[:60]} — from {sender[:40]}",
            expanded=(i == 0)
        ):
            col1, col2 = st.columns([1, 1])

            with col1:
                st.markdown("**Original email**")
                st.text_area(
                    "Email body",
                    value=body,
                    height=200,
                    key=f"body_{i}",
                    disabled=True
                )
                st.caption(
                    f"Language: `{language}` | "
                    f"Intent: `{intent}` | "
                    f"Escalate: `{escalate}`"
                )
                if sources:
                    st.caption(f"Sources: {', '.join(set(sources))}")

            with col2:
                st.markdown("**Draft reply**")

                if escalate:
                    st.warning(
                        "Flagged for human review — "
                        "please handle this email manually."
                    )

                edited_reply = st.text_area(
                    "Edit before sending",
                    value=draft_reply,
                    height=200,
                    key=f"reply_{i}"
                )

                col_a, col_b, col_c = st.columns(3)

                with col_a:
                    if st.button("✅ Approve", key=f"approve_{i}",
                                 use_container_width=True):
                        human_edited = edited_reply.strip() != draft_reply.strip()

                        raw_from = draft.get("from", "")
                        if "<" in raw_from and ">" in raw_from:
                            to_address = raw_from.split("<")[1].split(">")[0].strip()
                        else:
                            to_address = raw_from.strip()

                        sent = send_reply(
                            to_address=to_address,
                            subject=draft.get("subject", ""),
                            reply_body=edited_reply,
                            original_message_id=draft.get("message_id", "")
                        )
                        mark_as_processed(
                            message_id, "approved",
                            edited_reply, human_edited
                        )
                        if sent:
                            st.success("Reply sent and logged.")
                        else:
                            st.error("Reply logged but failed to send — check terminal for details.")
                        st.rerun()

                with col_b:
                    if st.button("✏️ Edit & Approve", key=f"edit_{i}",
                                 use_container_width=True):
                        raw_from = draft.get("from", "")
                        if "<" in raw_from and ">" in raw_from:
                            to_address = raw_from.split("<")[1].split(">")[0].strip()
                        else:
                            to_address = raw_from.strip()

                        sent = send_reply(
                            to_address=to_address,
                            subject=draft.get("subject", ""),
                            reply_body=edited_reply,
                            original_message_id=draft.get("message_id", "")
                        )
                        mark_as_processed(
                            message_id, "edited",
                            edited_reply, True
                        )
                        if sent:
                            st.success("Edited reply sent and logged.")
                        else:
                            st.error("Edited reply logged but failed to send — check terminal for details.")
                        st.rerun()

                with col_c:
                    if st.button("🚨 Escalate",
                                 key=f"escalate_{i}",
                                 use_container_width=True):
                        mark_as_processed(
                            message_id, "escalated",
                            draft_reply, False
                        )
                        st.warning("Escalated to human team.")
                        st.rerun()

# ── Sidebar: quick stats ────────────────────────────────────

with st.sidebar:
    st.markdown("### Quick stats")

    processed_count = 0
    if Path(PROCESSED_QUEUE).exists():
        with open(PROCESSED_QUEUE, "r", encoding="utf-8") as f:
            processed_count = sum(1 for line in f if line.strip())

    st.metric("Pending review", len(drafts))
    st.metric("Processed total", processed_count)

    st.divider()
    st.caption("Run `python analytics.py` for full accuracy report.")
    st.caption(f"Queue: `{DRAFT_QUEUE}`")
    st.caption(f"Log: `interaction_log.jsonl`")