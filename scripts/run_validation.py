"""
run_validation.py

Runs all 28 Task B1 validation questions against the local ChromaDB
and writes results to b2_results.csv in the project root.

Usage:
    python scripts/run_validation.py

Requires:
    - ChromaDB must already be built. Run `python scripts/build_kb.py` first.
    - GEMINI_API_KEY must be present in the project root .env file.
"""

import csv
import sys
import time
from pathlib import Path

# Allow importing from the same scripts/ directory regardless of working directory.
sys.path.insert(0, str(Path(__file__).parent))
from test_retrieval import load_vector_database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = PROJECT_ROOT / "b2_results.csv"
SNIPPET_LENGTH = 300
QUERY_DELAY = 2.5       # seconds between embedding calls; ~24 QPM, well under Gemini's limit
RETRY_WAIT_BASE = 15    # seconds to wait on first 429; doubles each subsequent retry
MAX_RETRIES = 3

FIELDNAMES = [
    "Question",
    "Top-1 Source File",
    "Top-1 Content Snippet",
    "Source correct (Y/N)",
    "Score",
]

# ── Task B1 test bank ────────────────────────────────────────────────────────
# 20 English questions followed by 4 Chinese and 4 French questions.

QUESTIONS = [
    # ── English: Pricing (7) ─────────────────────────────────────────────────
    "What is the price for a Wieland Zenostar zirconia crown?",
    "How much does an IPS e.max lithium disilicate crown cost per unit?",
    "What is your price for a PFM crown?",
    "How much does a full-arch complete removable denture cost?",
    "What is the price for an implant crown with a custom zirconia abutment?",
    "How much does a Valplast flexible partial denture cost?",
    "What is the price for a standard 3-unit Wieland Zenostar zirconia bridge?",

    # ── English: Order process (5) ───────────────────────────────────────────
    "Do you offer a volume discount, and how many units do I need to qualify?",
    "Do you offer rush production and what is the additional surcharge?",
    "How long does it take to produce a standard Wieland Zenostar zirconia crown?",
    "What is the production lead time for a complete removable denture?",
    "How do I know you have received my physical impression?",

    # ── English: Rework / urgent (1) ─────────────────────────────────────────
    "My order has not arrived and the expected delivery date has passed — what should I do?",

    # ── English: Technical / submission (1) ──────────────────────────────────
    "Can I submit a digital scan file instead of a physical impression, and what file format do you require?",

    # ── English: Material recommendations (2) ────────────────────────────────
    "What material do you recommend for a patient who grinds their teeth?",
    "What is the difference between monolithic zirconia and high-translucency layered zirconia?",

    # ── English: Material comparisons (2) ────────────────────────────────────
    "For a single upper central incisor where aesthetics are the top priority, should I choose IPS e.max or Wieland Zenostar zirconia?",
    "What is the difference between a Valplast flexible partial denture and a cobalt-chromium framework partial denture?",

    # ── English: Edge cases (2) ──────────────────────────────────────────────
    "Is rush processing available for implant crown cases?",
    "We found a shade error in the prescription after production has already started — is it possible to correct this?",

    # ── Chinese (4) ──────────────────────────────────────────────────────────
    "威兰德氧化锆牙冠的价格是多少？",
    "你们接受数字扫描文件吗？需要什么格式？",
    "磨牙症患者最适合选择什么修复材料？",
    "如果收到的修复体颜色与我们订购的颜色不符，应该怎么处理？",

    # ── French (4) ───────────────────────────────────────────────────────────
    "Quel est le délai de production standard pour une couronne en zircone ?",
    "Quels sont les moyens de paiement que vous acceptez ?",
    "Quelle est la différence entre la zircone monolithique et la zircone stratifiée haute translucidité ?",
    "Ma commande n'est pas arrivée à la date prévue — que dois-je faire ?",
]


def _query_with_retry(db, question: str) -> list:
    """Call similarity_search_with_score with exponential backoff on 429 errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return db.similarity_search_with_score(question, k=1)
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = RETRY_WAIT_BASE * (2 ** attempt)
                print(f"  [rate limit] 429 received — waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...")
                time.sleep(wait)
            else:
                raise
    print("  [warning] All retries exhausted for this query — skipping.")
    return []


def run_validation() -> None:
    print("Loading vector database...")
    db = load_vector_database()
    print(f"Running {len(QUESTIONS)} validation queries...\n")

    rows = []
    for i, question in enumerate(QUESTIONS, start=1):
        results = _query_with_retry(db, question)

        if results:
            doc, _ = results[0]
            source_file = Path(doc.metadata.get("source", "unknown")).name
            snippet = doc.page_content.replace("\n", " ").strip()[:SNIPPET_LENGTH]
        else:
            source_file = "no result"
            snippet = ""

        label = f"[{i:02d}/{len(QUESTIONS)}]"
        print(f"{label} {question[:70]}")
        print(f"         Source : {source_file}")
        print(f"         Snippet: {snippet[:90]}...")
        print()

        rows.append(
            {
                "Question": question,
                "Top-1 Source File": source_file,
                "Top-1 Content Snippet": snippet,
                "Source correct (Y/N)": "",
                "Score": "",
            }
        )

        # Pace requests to stay well under Gemini's rate limit.
        # Skip the sleep after the last question to avoid unnecessary delay.
        if i < len(QUESTIONS):
            time.sleep(QUERY_DELAY)

    # utf-8-sig adds a BOM so Google Sheets and Excel both handle
    # Chinese and French characters correctly on import.
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Results written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    run_validation()
