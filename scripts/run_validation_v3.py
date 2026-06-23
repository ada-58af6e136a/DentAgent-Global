"""
run_validation_v3.py

Runs the 28-question benchmark through the full V3 retrieval pipeline:
  2.1  Query rewriting   — LLM extracts the core question from the email
  2.2  HyDE              — LLM generates a KB-style hypothesis for MMR
  3.1  BM25 + MMR (RRF)  — hybrid retrieval on the clean/hypothesis query
  3.4  MMR diversity     — applied on the semantic side
  4.1  CrossEncoder      — reranks on (rewritten_query, chunk)
  3.3  Dynamic k         — intent-specific final chunk count

Each question is tagged with its expected intent so that the k-map
(PRICING=2, MATERIAL=3, TECHNICAL=5, PROGRESS=2, REWORK=3) applies correctly.

API calls per question: 2 generation (rewrite + HyDE) + 1 embedding (MMR)
QUERY_DELAY is set conservatively to avoid free-tier rate limits.

Outputs:
  validation/Validation_Results_V3_28Q.csv
  (inline comparison with V1 and V2 printed to stdout)

Usage:
    python scripts/run_validation_v3.py
"""

import csv
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.rag_chain import retrieve_for_email

V1_CSV  = PROJECT_ROOT / "validation" / "Validation_Results_V1_28Q.csv"
V2_CSV  = PROJECT_ROOT / "validation" / "Validation_Results_V2_28Q.csv"
OUT_CSV = PROJECT_ROOT / "validation" / "Validation_Results_V3_28Q.csv"

# 7 s between questions: 2 generation + 1 embedding call per question
QUERY_DELAY = 7

# ── 28 questions (identical to V1 / V2) ──────────────────────────────────────
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

# ── Intent label for each question (drives dynamic k via INTENT_K_MAP) ────────
QUESTION_INTENTS = [
    "PRICING",    # Q1  zenostar crown price
    "PRICING",    # Q2  e.max price
    "PRICING",    # Q3  PFM price
    "PRICING",    # Q4  denture cost
    "PRICING",    # Q5  implant crown price
    "PRICING",    # Q6  Valplast price
    "PRICING",    # Q7  bridge price
    "PRICING",    # Q8  volume discount
    "PRICING",    # Q9  rush surcharge
    "PROGRESS",   # Q10 crown lead time
    "PROGRESS",   # Q11 denture lead time
    "PROGRESS",   # Q12 impression received
    "PROGRESS",   # Q13 order not arrived
    "TECHNICAL",  # Q14 digital scan format
    "MATERIAL",   # Q15 bruxism material
    "MATERIAL",   # Q16 monolithic vs layered
    "MATERIAL",   # Q17 e.max vs zirconia anterior
    "MATERIAL",   # Q18 Valplast vs CoCr
    "PRICING",    # Q19 rush for implant (service availability)
    "REWORK",     # Q20 shade error
    "PRICING",    # Q21 ZH zenostar price
    "TECHNICAL",  # Q22 ZH digital scan
    "MATERIAL",   # Q23 ZH bruxism
    "REWORK",     # Q24 ZH shade mismatch
    "PROGRESS",   # Q25 FR crown lead time
    "BILLING",    # Q26 FR payment methods
    "MATERIAL",   # Q27 FR monolithic vs layered
    "PROGRESS",   # Q28 FR order not arrived
]

# ── Acceptable source files per question ──────────────────────────────────────
EXPECTED_SOURCES = [
    {"pricing.txt", "faq.txt"},              #  1
    {"pricing.txt", "faq.txt"},              #  2
    {"pricing.txt", "faq.txt"},              #  3
    {"pricing.txt"},                         #  4
    {"pricing.txt"},                         #  5
    {"pricing.txt", "faq.txt"},              #  6
    {"pricing.txt"},                         #  7  bridge section specifically
    {"pricing.txt", "faq.txt"},              #  8
    {"faq.txt", "pricing.txt", "order_process.txt"},  #  9
    {"order_process.txt", "faq.txt"},        # 10  faq.txt also has 5-7d Q&A
    {"order_process.txt"},                   # 11
    {"faq.txt"},                             # 12
    {"order_process.txt", "faq.txt"},        # 13  faq.txt has direct Q&A
    {"faq.txt"},                             # 14
    {"faq.txt", "materials.txt"},            # 15
    {"materials.txt", "faq.txt"},            # 16
    {"materials.txt"},                       # 17
    {"materials.txt"},                       # 18
    {"faq.txt", "order_process.txt"},        # 19  must mention implant exception
    {"faq.txt"},                             # 20
    {"pricing.txt", "faq.txt"},              # 21
    {"faq.txt"},                             # 22
    {"faq.txt", "materials.txt"},            # 23
    {"faq.txt"},                             # 24
    {"order_process.txt", "faq.txt"},        # 25
    {"faq.txt"},                             # 26
    {"materials.txt", "faq.txt"},            # 27
    {"order_process.txt", "faq.txt"},        # 28
]

# ── Snippet-level checks where the correct source file alone is insufficient ──
SNIPPET_CHECKS = {
    9:  lambda s: "5 to 7" in s and "7 to 10" not in s,
    13: lambda s: "STL" in s or "scan file" in s.lower(),
    18: lambda s: "implant" in s.lower() and "not available" in s.lower(),
    24: lambda s: "5 to 7" in s or "5 à 7" in s,
}


def _verdict(idx: int, source: str, snippet: str, kb_miss: bool) -> str:
    if kb_miss:
        return "KB_MISS"
    if source not in EXPECTED_SOURCES[idx]:
        return "N"
    if idx in SNIPPET_CHECKS and not SNIPPET_CHECKS[idx](snippet):
        return "N"
    return "Y"


def _load_verdicts(csv_path: Path, col: str) -> dict:
    """Return {question: verdict} from a previous results CSV."""
    out = {}
    if csv_path.exists():
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                out[row["Question"]] = row.get(col, "?")
    return out


def run_validation() -> None:
    v1 = _load_verdicts(V1_CSV, "Source correct (Y/N)")
    v2 = _load_verdicts(V2_CSV, "V2 Correct")

    print(f"Running {len(QUESTIONS)}-question V3 benchmark  "
          f"(2.1 query rewrite + 2.2 HyDE + 3.3 dynamic-k)\n")
    print(f"{'#':>2}  {'V1':^5}  {'V2':^5}  {'V3':^8}  {'Score':>6}  {'k':>2}  {'Src':12}  Question")
    print("─" * 100)

    rows = []
    correct = {"v1": 0, "v2": 0, "v3": 0}

    for i, (question, intent) in enumerate(zip(QUESTIONS, QUESTION_INTENTS), start=1):
        v1_verdict = v1.get(question, "?")
        v2_verdict = v2.get(question, "?")
        if v1_verdict == "Y":
            correct["v1"] += 1
        if v2_verdict == "Y":
            correct["v2"] += 1

        result = retrieve_for_email(question, intent)

        kb_miss  = result["kb_miss"]
        score    = result["retrieval_score"]
        rewritten = result["rewritten_query"]
        sources  = result["sources"]
        docs     = result["docs"]
        top_src  = sources[0] if sources else ("kb_miss" if kb_miss else "no result")
        snippet  = docs[0].page_content.replace("\n", " ").strip()[:300] if docs else ""
        k_used   = len(docs)

        v3_verdict = _verdict(i - 1, top_src, snippet, kb_miss)
        if v3_verdict == "Y":
            correct["v3"] += 1

        change = (
            " ↑" if v2_verdict != "Y" and v3_verdict == "Y"
            else " ↓" if v2_verdict == "Y" and v3_verdict != "Y"
            else "  "
        )

        print(f"{i:>2}  {v1_verdict:^5}  {v2_verdict:^5}  {v3_verdict:^8}  "
              f"{score:.4f}  {k_used:>2}  {top_src:12}  {question[:40]}")
        print(f"     {'':5}  {'':5}  {'':8}  {'':6}  {'':2}  "
              f"{'':12}  ↳ {rewritten[:70]}{change}")

        rows.append({
            "Question":         question,
            "Intent":           intent,
            "V1 Correct":       v1_verdict,
            "V2 Correct":       v2_verdict,
            "V3 Correct":       v3_verdict,
            "V3 Score":         score,
            "V3 k":             k_used,
            "V3 Source":        top_src,
            "V3 Rewritten":     rewritten,
            "V3 Snippet":       snippet,
        })

        if i < len(QUESTIONS):
            time.sleep(QUERY_DELAY)

    n = len(QUESTIONS)
    print("─" * 100)
    print(f"\n{'Pipeline':<30}  {'Correct':>7}  {'Accuracy':>8}")
    print(f"{'V1  (similarity_search)':<30}  {correct['v1']:>4}/{n}  {correct['v1']/n*100:>7.1f}%")
    print(f"{'V2  (BM25+MMR+Rerank)':<30}  {correct['v2']:>4}/{n}  {correct['v2']/n*100:>7.1f}%")
    print(f"{'V3  (+QueryRewrite+HyDE+DynK)':<30}  {correct['v3']:>4}/{n}  {correct['v3']/n*100:>7.1f}%")
    d23 = correct["v3"] - correct["v2"]
    d13 = correct["v3"] - correct["v1"]
    print(f"\nV2 → V3 delta: {'+' if d23 >= 0 else ''}{d23} questions")
    print(f"V1 → V3 delta: {'+' if d13 >= 0 else ''}{d13} questions")

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved → {OUT_CSV}")


if __name__ == "__main__":
    run_validation()
