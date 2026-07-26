"""
run_validation_category_level.py

Targeted regression test for the "category-level question" retrieval gap
found 2026-07: pricing.txt/materials.txt store one chunk per specific
product (e.g. one Wieland Zenostar crown paragraph, one PFM paragraph),
so a question asking about a whole category ("what dentures do you
offer") matched each product chunk only partially and fell below the
CrossEncoder rerank threshold, forcing an unnecessary escalation even
though the KB had all the underlying facts.

Fixed by adding one overview paragraph per category (crowns, veneers,
dentures) that names every option and its price range in one chunk.
This script exists to catch a regression if that pattern breaks again
(e.g. a KB edit removes an overview paragraph, or a new category is
added without one) — separate from run_validation_42q.py, whose
28+14 scoring structure isn't shaped for this category of question.

Usage:
    python scripts/run_validation_category_level.py
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.rag_chain import retrieve_for_email

QUERY_DELAY = 10  # 2 generation + 1 embedding call per question

# Each case: (question, intent, must_appear) — must_appear are substrings
# that should all be present across the retrieved chunks if the overview
# paragraph was found (a weak proxy for "actually covers every option").
CASES = [
    (
        "你好，请问一下能提供哪些义齿，价格分别多少呢？",
        "PRICING",
        ["180", "260", "100", "140", "55", "80", "140", "200"],  # 4 denture price ranges
    ),
    (
        "What types of removable dentures do you offer and what are the prices?",
        "PRICING",
        ["180", "260", "100", "140", "55", "80", "140", "200"],
    ),
    (
        "What crown types do you offer and what are their prices?",
        "PRICING",
        ["85", "130", "95", "145", "55", "85", "35", "55"],  # 4 crown price ranges
    ),
    (
        "What veneer and inlay/onlay options do you offer?",
        "PRICING",
        ["85", "120", "65", "95", "75", "110"],  # 3 veneer/inlay price ranges
    ),
    (
        "What restoration materials do you work with?",
        "MATERIAL",
        # "porcelain-fused-to-metal" not "PFM": the surviving faq.txt answer
        # spells it out rather than using the abbreviation — verified 2026-07,
        # not a retrieval gap.
        ["Zenostar", "e.max", "porcelain-fused-to-metal", "PMMA", "PEEK"],
    ),
]


def _retrieve(question: str, intent: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            return retrieve_for_email(question, intent)
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"  [transient error, retry {attempt+1}/{max_retries} in {wait}s] {exc}")
                time.sleep(wait)
            else:
                raise


def run() -> None:
    print("Category-level retrieval regression check\n")
    passed = 0

    for i, (question, intent, must_appear) in enumerate(CASES, start=1):
        result = _retrieve(question, intent)
        kb_miss = result["kb_miss"]
        score = result["retrieval_score"]
        combined_text = " ".join(d.page_content for d in result["docs"])

        if kb_miss:
            ok, reason = False, "kb_miss — escalated instead of answering"
        else:
            missing = [m for m in must_appear if m not in combined_text]
            ok = not missing
            reason = "all expected values present" if ok else f"missing: {missing}"

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{status}] Q{i} (score={score:.3f}): {question[:60]}")
        print(f"        {reason}\n")

        if i < len(CASES):
            time.sleep(QUERY_DELAY)

    print(f"{passed}/{len(CASES)} passed")


if __name__ == "__main__":
    run()
