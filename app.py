"""
app.py

Streamlit review dashboard for the dental CS agent.
Shows pending drafts from SQLite (agent/db.py).
CS staff can Approve, Edit, or Escalate each draft.

Fix B: draft queue is now SQLite — no more JSONL race conditions
       or full-file rewrites on every approval action.

DEMO_MODE (default false, zero change to normal behavior): when true, skips
importing agent.email_handler entirely — that module pulls in chromadb,
sentence-transformers/torch, and langchain_* at module level just to reach
send_reply(), which a demo deployment has no use for and shouldn't have to
carry the weight or the real-Gmail-credential risk of. Approve/Edit&Approve
still update status locally; they just don't actually send.
"""

import os

import streamlit as st
from agent.analytics import log_interaction
from agent.db import load_pending_drafts, mark_as_processed, count_processed, get_conn, init_db

DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() == "true"

if not DEMO_MODE:
    from agent.email_handler import send_reply
else:
    # data/ is gitignored, so a fresh clone (e.g. Streamlit Cloud spinning up
    # a new container) has no drafts.db at all. Self-seed once per cold boot
    # rather than committing a binary db file to git — cheap (one COUNT
    # query) on every rerun, only does real work the first time the table's
    # actually empty. Also means the demo quietly resets to a clean state
    # whenever the container restarts, instead of drifting from visitor clicks.
    init_db()
    with get_conn() as _conn:
        if _conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0:
            from scripts.seed_demo_data import seed
            seed()

st.set_page_config(
    page_title="Dental CS Agent — Review Dashboard",
    layout="wide"
)

st.title("Dental CS Agent — Review Dashboard")
if DEMO_MODE:
    st.caption(":information_source: Running in demo mode — replies are logged but not actually sent.")


def _maybe_send_reply(to_address: str, subject: str, reply_body: str,
                       original_message_id: str) -> bool:
    """
    Send the reply unless DEMO_MODE is on, in which case it's a no-op that
    reports success — the draft still gets marked processed either way, the
    demo just never touches real SMTP.
    """
    if DEMO_MODE:
        return True
    return send_reply(
        to_address=to_address, subject=subject,
        reply_body=reply_body, original_message_id=original_message_id,
    )


def _handle_action(message_id: str, action: str,
                   final_reply: str, human_edited: bool) -> None:
    """Update SQLite status and log the interaction to analytics."""
    target = mark_as_processed(message_id, action, final_reply, human_edited)
    if target:
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
            action=action,
        )


# ── Main dashboard ──────────────────────────────────────────

drafts = load_pending_drafts()

if not drafts:
    st.info("No pending drafts. The agent will populate this list "
            "as new emails arrive.")
    st.caption("Queue: data/drafts.db")
    st.caption("Auto-sent replies bypass this queue — see the Ops Dashboard page for those.")
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

                        sent = _maybe_send_reply(
                            to_address=to_address,
                            subject=draft.get("subject", ""),
                            reply_body=edited_reply,
                            original_message_id=draft.get("message_id", "")
                        )
                        _handle_action(message_id, "approved",
                                       edited_reply, human_edited)
                        if DEMO_MODE:
                            st.info("Demo mode — reply logged but not actually sent.")
                        elif sent:
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

                        sent = _maybe_send_reply(
                            to_address=to_address,
                            subject=draft.get("subject", ""),
                            reply_body=edited_reply,
                            original_message_id=draft.get("message_id", "")
                        )
                        _handle_action(message_id, "edited", edited_reply, True)
                        if DEMO_MODE:
                            st.info("Demo mode — edited reply logged but not actually sent.")
                        elif sent:
                            st.success("Edited reply sent and logged.")
                        else:
                            st.error("Edited reply logged but failed to send — check terminal for details.")
                        st.rerun()

                with col_c:
                    if st.button("🚨 Escalate",
                                 key=f"escalate_{i}",
                                 use_container_width=True):
                        _handle_action(message_id, "escalated",
                                       draft_reply, False)
                        st.warning("Escalated to human team.")
                        st.rerun()

# ── Sidebar: quick stats ────────────────────────────────────

with st.sidebar:
    st.markdown("### Quick stats")

    st.metric("Pending review", len(drafts))
    st.metric("Processed total", count_processed())

    st.divider()
    st.caption("Run `python -m agent.analytics` for accuracy + shadow-mode calibration.")
    st.caption("Queue: `data/drafts.db`")
    st.caption("Log: `data/interaction_log.jsonl`")
    st.caption("Auto-sent replies bypass this queue — see Ops Dashboard.")