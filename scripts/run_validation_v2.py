"""
run_validation_v2.py

Runs the 28-question benchmark through the V2 retrieval pipeline
(BM25 + MMR semantic + CrossEncoder reranking) and prints a side-by-side
comparison with the V1 baseline.

Outputs:
  validation/Validation_Results_V2_28Q.csv

Usage:
    python scripts/run_validation_v2.py
"""

import csv
import math
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Fix M: lazy-init globals (_bm25_retriever, _mmr_retriever, _reranker) are
# None at import time (Fix D). Importing them by value would freeze the None.
# Import the module reference instead and call _ensure_initialized() once
# before first use so the globals are populated.
from dotenv import load_dotenv
import agent.rag_chain as rag_chain
from agent.rag_chain import _rrf_merge, RERANK_THRESHOLD

load_dotenv(PROJECT_ROOT / ".env")

V1_CSV = PROJECT_ROOT / "validation" / "Validation_Results_V1_28Q.csv"
OUTPUT_CSV = PROJECT_ROOT / "validation" / "Validation_Results_V2_28Q.csv"
QUERY_DELAY = 2.5   # seconds between MMR embedding calls

# ── Same 28 questions as V1 ───────────────────────────────────────────────────
QUESTIONS = [
    "What is the price for a Wieland Zenostar zirconia crown?",
    "How much does an IPS e.max lithium disilicate crown cost per unit?",
    "What is your price for a PFM crown?",
    "How much does a full-arch complete removable denture cost?",
    "What is the price for an implant crown with a custom zirconia abutment?",
    "How much does a Valplast flexible partial denture cost?",
    "What is the price for a standard 3-unit Wieland Zenostar zirconia bridge?",
    "Do you offer a volume discount, and how many units do I need to qualify?",
    "Do you offer rush production and what is the additional surcharge?",
    "How long does it take to produce a standard Wieland Zenostar zirconia crown?",
    "What is the production lead time for a complete removable denture?",
    "How do I know you have received my physical impression?",
    "My order has not arrived and the expected delivery date has passed — what should I do?",
    "Can I submit a digital scan file instead of a physical impression, and what file format do you require?",
    "What material do you recommend for a patient who grinds their teeth?",
    "What is the difference between monolithic zirconia and high-translucency layered zirconia?",
    "For a single upper central incisor where aesthetics are the top priority, should I choose IPS e.max or Wieland Zenostar zirconia?",
    "What is the difference between a Valplast flexible partial denture and a cobalt-chromium framework partial denture?",
    "Is rush processing available for implant crown cases?",
    "We found a shade error in the prescription after production has already started — is it possible to correct this?",
    "威兰德氧化锆牙冠的价格是多少？",
    "你们接受数字扫描文件吗？需要什么格式？",
    "磨牙症患者最适合选择什么修复材料？",
    "如果收到的修复体颜色与我们订购的颜色不符，应该怎么处理？",
    "Quel est le délai de production standard pour une couronne en zircone ?",
    "Quels sont les moyens de paiement que vous acceptez ?",
    "Quelle est la différence entre la zircone monolithique et la zircone stratifiée haute translucidité ?",
    "Ma commande n'est pas arrivée à la date prévue — que dois-je faire ?",
]

# ── Expected source file(s) per question (any match = correct at source level) ─
EXPECTED_SOURCES = [
    {"pricing.txt", "faq.txt"},              #  1 zenostar crown price
    {"pricing.txt", "faq.txt"},              #  2 e.max price
    {"pricing.txt", "faq.txt"},              #  3 PFM price
    {"pricing.txt"},                         #  4 denture cost
    {"pricing.txt"},                         #  5 implant crown price
    {"pricing.txt", "faq.txt"},              #  6 Valplast price
    {"pricing.txt"},                         #  7 bridge price  (must be bridge section)
    {"pricing.txt", "faq.txt"},              #  8 volume discount
    {"faq.txt", "pricing.txt", "order_process.txt"},  #  9 rush production
    {"order_process.txt", "faq.txt"},         # 10 crown lead time (faq.txt also has correct 5-7d Q&A)
    {"order_process.txt"},                   # 11 denture lead time
    {"faq.txt"},                             # 12 impression received
    {"order_process.txt", "faq.txt"},        # 13 order not arrived (faq.txt has direct Q&A)
    {"faq.txt"},                             # 14 digital scan format
    {"faq.txt", "materials.txt"},            # 15 bruxism material
    {"materials.txt", "faq.txt"},            # 16 monolithic vs layered
    {"materials.txt"},                       # 17 e.max vs zirconia anterior
    {"materials.txt"},                       # 18 Valplast vs CoCr
    {"faq.txt", "order_process.txt"},        # 19 rush for implant
    {"faq.txt"},                             # 20 shade error
    {"pricing.txt", "faq.txt"},              # 21 ZH zenostar price
    {"faq.txt"},                             # 22 ZH digital scan
    {"faq.txt", "materials.txt"},            # 23 ZH bruxism
    {"faq.txt"},                             # 24 ZH shade mismatch
    {"order_process.txt", "faq.txt"},         # 25 FR crown lead time (faq.txt also has correct 5-7d Q&A)
    {"faq.txt"},                             # 26 FR payment methods
    {"materials.txt", "faq.txt"},            # 27 FR monolithic vs layered
    {"order_process.txt", "faq.txt"},        # 28 FR order not arrived (faq.txt has direct Q&A)
]

# ── Extra snippet-level checks for questions where source file alone is
#    insufficient (V1 retrieved the right file but wrong chunk).
SNIPPET_CHECKS = {
    9:  lambda s: "5 to 7" in s and "7 to 10" not in s,           # crown 5-7d, not implant 7-10d
    13: lambda s: "STL" in s or "scan file" in s.lower(),          # digital scan format, not impression handling
    18: lambda s: "implant" in s.lower() and "not available" in s.lower(),  # rush NOT available for implant
    24: lambda s: "5 to 7" in s or "5 à 7" in s,                  # crown 5-7d, not implant 7-10d
}


def _retrieve_v2(question: str) -> tuple:
    """Run BM25 + MMR + CrossEncoder and return (doc, source_name, score, kb_miss)."""
    bm25_results = rag_chain._bm25_retriever.invoke(question)
    mmr_results = rag_chain._mmr_retriever.invoke(question)
    candidates = _rrf_merge([mmr_results, bm25_results])

    if not candidates:
        return None, "no result", 0.0, True

    pairs = [(question, doc.page_content) for doc in candidates]
    rerank_scores = rag_chain._reranker.predict(pairs)
    ranked = sorted(zip(candidates, rerank_scores), key=lambda x: float(x[1]), reverse=True)

    top_doc, top_score = ranked[0]
    sigmoid_score = round(1.0 / (1.0 + math.exp(-float(top_score))), 4)
    kb_miss = float(top_score) < RERANK_THRESHOLD

    source = Path(top_doc.metadata.get("source", "unknown")).name
    return top_doc, source, sigmoid_score, kb_miss


def _is_correct_v2(idx: int, source: str, snippet: str, kb_miss: bool) -> str:
    """Return 'Y', 'N', or 'KB_MISS'."""
    if kb_miss:
        return "KB_MISS"
    if source not in EXPECTED_SOURCES[idx]:
        return "N"
    if idx in SNIPPET_CHECKS and not SNIPPET_CHECKS[idx](snippet):
        return "N"
    return "Y"


def run_validation() -> None:
    # Fix M: initialize lazy-init retrievers before first use.
    rag_chain._ensure_initialized()
    # Fix M: create output dir if it doesn't exist (works from any CWD).
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    # Load V1 results for comparison
    v1_rows: dict = {}
    if V1_CSV.exists():
        with open(V1_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                v1_rows[row["Question"]] = row

    print(f"Running {len(QUESTIONS)}-question V2 benchmark...\n")
    print(f"{'#':>2}  {'V1':^6}  {'V2':^8}  {'Score':>6}  {'Chg':^4}  Question")
    print("─" * 90)

    output_rows = []
    correct_v1 = correct_v2 = 0

    for i, question in enumerate(QUESTIONS, start=1):
        v1 = v1_rows.get(question, {})
        v1_source = v1.get("Top-1 Source File", "?")
        v1_verdict = v1.get("Source correct (Y/N)", "?")
        if v1_verdict == "Y":
            correct_v1 += 1

        doc, source, score, kb_miss = _retrieve_v2(question)
        snippet = doc.page_content.replace("\n", " ").strip()[:300] if doc else ""
        v2_verdict = _is_correct_v2(i - 1, source, snippet, kb_miss)
        if v2_verdict == "Y":
            correct_v2 += 1

        change = (
            " ↑ " if v1_verdict == "N" and v2_verdict == "Y"
            else " ↓ " if v1_verdict == "Y" and v2_verdict != "Y"
            else "   "
        )
        print(f"{i:>2}  {v1_verdict:^6}  {v2_verdict:^8}  {score:.4f}  {change}  {question[:55]}")

        output_rows.append({
            "Question":     question,
            "V1 Source":    v1_source,
            "V1 Correct":   v1_verdict,
            "V2 Source":    source,
            "V2 Correct":   v2_verdict,
            "V2 Score":     score,
            "V2 Snippet":   snippet,
        })

        if i < len(QUESTIONS):
            time.sleep(QUERY_DELAY)

    print("─" * 90)
    print(f"\nV1 (similarity_search): {correct_v1}/{len(QUESTIONS)} = {correct_v1/len(QUESTIONS)*100:.1f}%")
    print(f"V2 (BM25+MMR+Rerank):   {correct_v2}/{len(QUESTIONS)} = {correct_v2/len(QUESTIONS)*100:.1f}%")
    delta = correct_v2 - correct_v1
    print(f"Delta: {'+' if delta >= 0 else ''}{delta} questions ({'+' if delta >= 0 else ''}{delta/len(QUESTIONS)*100:.1f}%)")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0].keys()))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nResults saved → {OUTPUT_CSV}")


if __name__ == "__main__":
    run_validation()
