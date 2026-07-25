"""
analytics.py

Logs every processed email interaction to interaction_log.jsonl.
Used for tracking accuracy, identifying knowledge base gaps,
and making the case for enabling auto-send in Phase 5.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .db import get_shadow_mode_calibration
from .logger import get_logger
from .paths import DATA_DIR

log = get_logger(__name__)

LOG_FILE = str(DATA_DIR / "interaction_log.jsonl")


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

    log.debug("Logged: intent=%s action=%s mid=%s",
              record["intent"], action, record["message_id"][:30])


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
    by_intent = defaultdict(list)
    for r in records:
        by_intent[r["intent"]].append(r)

    for intent, items in sorted(by_intent.items()):
        total = len(items)
        approved = sum(1 for r in items if r["action"] == "approved")
        auto_sent = sum(1 for r in items if r["action"] == "auto_sent")
        edited = sum(1 for r in items if r["action"] == "edited")
        escalated = sum(1 for r in items if r["action"] == "escalated")
        pending = sum(1 for r in items if r["action"] == "pending")

        # auto_sent is deliberately excluded from approved_rate — it was never
        # human-reviewed, so conflating it with human approval would overstate
        # how much of the "approved" signal is actually validated.
        approved_rate = (approved / total * 100) if total > 0 else 0
        print(f"{intent:12} | total={total:3} | "
              f"approved={approved:3} ({approved_rate:.0f}%) | "
              f"auto_sent={auto_sent:3} | "
              f"edited={edited:3} | escalated={escalated:3} | pending={pending:3}")

    print(f"\nAuto-send ready when approved rate >= 90% for PRICING, MATERIAL, PROGRESS.")


# Below this sample size, per-intent would-be accuracy is noise, not signal —
# flagged inline rather than silently trusted.
MIN_CALIBRATION_SAMPLE = 30


def get_shadow_mode_calibration_report():
    """
    Compares what shadow mode says auto-send WOULD have done
    (drafts.would_auto_send=1 — see agent/email_handler.py) against what the
    human reviewer actually decided, per intent. This is the tool that answers
    "are AUTO_SEND_CONFIDENCE_THRESHOLD / AUTO_SEND_RETRIEVAL_THRESHOLD in
    .env actually trustworthy" — run this before ever setting
    AUTO_SEND_ENABLED=true, not after.
    """
    rows = get_shadow_mode_calibration()

    print(f"\n=== Shadow Mode Calibration ({len(rows)} would-be-eligible, "
          f"human-reviewed) ===\n")

    if not rows:
        print("No would-be-eligible + human-reviewed drafts yet. Shadow mode "
              "is always on (see .env.example), so this fills in as the "
              "pipeline processes real email — nothing to configure, just "
              "re-run this later.")
        return

    print("Would auto-send have been right, based on what the human actually did:\n")

    by_intent = defaultdict(lambda: {"correct": 0, "needed_edit": 0, "wrong": 0})
    for r in rows:
        bucket = by_intent[r["intent"]]
        if r["status"] == "escalated":
            bucket["wrong"] += 1
        elif r["status"] == "approved" and not r["human_edited"]:
            bucket["correct"] += 1
        else:  # status == "edited", or approved-but-tweaked-before-clicking
            bucket["needed_edit"] += 1

    total_correct = total_all = 0
    for intent, b in sorted(by_intent.items()):
        total = b["correct"] + b["needed_edit"] + b["wrong"]
        rate = (b["correct"] / total * 100) if total else 0
        flag = "" if total >= MIN_CALIBRATION_SAMPLE else "  <- sample too small to trust"
        print(f"{intent:12} | n={total:3} | would-be correct={b['correct']:3} ({rate:.0f}%) | "
              f"needed edit={b['needed_edit']:3} | would-be wrong={b['wrong']:3}{flag}")
        total_correct += b["correct"]
        total_all += total

    overall_rate = (total_correct / total_all * 100) if total_all else 0
    print(f"\nOverall: {total_correct}/{total_all} ({overall_rate:.0f}%) would-be correct.")

    if total_all < MIN_CALIBRATION_SAMPLE:
        print(f"Total sample ({total_all}) is below the {MIN_CALIBRATION_SAMPLE}-sample "
              f"minimum this project treats as trustworthy — do not use this number to "
              f"justify enabling AUTO_SEND_ENABLED yet.")
    else:
        print("Compare this against AUTO_SEND_CONFIDENCE_THRESHOLD / "
              "AUTO_SEND_RETRIEVAL_THRESHOLD in .env before deciding whether to "
              "raise, lower, or leave them as-is.")


if __name__ == "__main__":
    get_accuracy_report()
    get_shadow_mode_calibration_report()