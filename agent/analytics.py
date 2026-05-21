"""
analytics.py

Logs every processed email interaction to interaction_log.jsonl.
Used for tracking accuracy, identifying knowledge base gaps,
and making the case for enabling auto-send in Phase 5.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = "data/interaction_log.jsonl"


def log_interaction(
    email_data: dict,
    classification: dict,
    draft_reply: str,
    sources: list,
    human_edited: bool = False,
    final_reply: str = None,
    action: str = "pending"
):
    """
    Append one interaction record to the log file.

    Args:
        email_data:    original email dict from email_handler
        classification: result from classify_intent()
        draft_reply:   AI-generated draft
        sources:       knowledge base chunks used
        human_edited:  True if CS staff modified the draft
        final_reply:   what was actually sent (after edits)
        action:        'approved' / 'edited' / 'escalated' / 'pending'
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": email_data.get("message_id", ""),
        "from": email_data.get("from", ""),
        "subject": email_data.get("subject", ""),
        "intent": classification.get("intent", "OTHER"),
        "language": classification.get("language", "en"),
        "escalate": classification.get("escalate", True),
        "confidence": classification.get("confidence", 0.0),
        "draft_reply": draft_reply,
        "sources": sources,
        "human_edited": human_edited,
        "final_reply": final_reply or draft_reply,
        "action": action
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  Logged: intent={record['intent']} | action={action}")


def get_accuracy_report():
    """
    Read the log and calculate approval rates per intent category.
    Run this after 2 weeks of data to decide if auto-send is ready.
    """
    if not Path(LOG_FILE).exists():
        print("No log file found.")
        return

    records = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        print("Log file is empty.")
        return

    print(f"\n=== Accuracy Report ({len(records)} interactions) ===\n")

    # Group by intent
    from collections import defaultdict
    by_intent = defaultdict(list)
    for r in records:
        by_intent[r["intent"]].append(r)

    for intent, items in sorted(by_intent.items()):
        total = len(items)
        approved = sum(1 for r in items if r["action"] == "approved")
        edited = sum(1 for r in items if r["action"] == "edited")
        escalated = sum(1 for r in items if r["action"] == "escalated")
        pending = sum(1 for r in items if r["action"] == "pending")

        approved_rate = (approved / total * 100) if total > 0 else 0
        print(f"{intent:12} | total={total:3} | "
              f"approved={approved:3} ({approved_rate:.0f}%) | "
              f"edited={edited:3} | escalated={escalated:3} | pending={pending:3}")

    print(f"\nAuto-send ready when approved rate >= 90% for PRICING, MATERIAL, PROGRESS.")


if __name__ == "__main__":
    get_accuracy_report()