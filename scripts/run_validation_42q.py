"""
run_validation_42q.py

Expanded 42-question benchmark.
Original 28 questions retained verbatim; 14 new questions added:
  - 3 x English (inlay price, bridge lead time, credit card)
  - 2 x English edge cases that should return KB_MISS (refund, competitor)
  - 1 x English new product (PMMA provisional)
  - 3 x German  (price, material, lead time)
  - 2 x Dutch   (price, lead time)
  - 2 x Spanish (price, rush)
  - 1 x Chinese (credit card / payment)

Outputs:
  validation/Validation_Results_V3_42Q.csv

Usage:
    python scripts/run_validation_42q.py
"""

import csv
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.rag_chain import retrieve_for_email

V3_CSV  = PROJECT_ROOT / "validation" / "Validation_Results_V3_28Q.csv"
OUT_CSV = PROJECT_ROOT / "validation" / "Validation_Results_V3_42Q.csv"

QUERY_DELAY = 10  # 2 generation + 1 embedding call per question; give server breathing room

# ── 42 questions ──────────────────────────────────────────────────────────────
QUESTIONS = [
    # ── Original 28 (EN / ZH / FR) ───────────────────────────────────────────
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
    # ── New 14 questions ──────────────────────────────────────────────────────
    "What is the price for a zirconia inlay or onlay?",                           # Q29  EN  pricing
    "What is the production lead time for a standard 3-unit zirconia bridge?",    # Q30  EN  progress
    "Do you accept credit card payments?",                                         # Q31  EN  billing
    "I would like to request a full refund for my last order.",                   # Q32  EN  kb_miss
    "Can you compare your pricing to other dental labs in the market?",           # Q33  EN  kb_miss
    "My patient needs a PMMA provisional crown — can you make one?",              # Q34  EN  pricing
    "Was kostet eine Wieland Zenostar Zirkonkrone?",                              # Q35  DE  pricing
    "Welche Materialien empfehlen Sie für einen Patienten mit Bruxismus?",        # Q36  DE  material
    "Wie lange dauert die Produktion einer Standardkrone aus Zirkon?",            # Q37  DE  progress
    "Wat is de prijs voor een IPS e.max kroon?",                                  # Q38  NL  pricing
    "Hoe lang duurt de productie van een volledige prothese?",                    # Q39  NL  progress
    "¿Cuál es el precio de una corona de zirconio Wieland Zenostar?",            # Q40  ES  pricing
    "¿Ofrecen producción urgente y cuál es el recargo adicional?",                # Q41  ES  pricing
    "你们接受信用卡支付吗？",                                                          # Q42  ZH  billing
]

# ── Intent per question (drives dynamic k) ────────────────────────────────────
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
    "PRICING",    # Q19 rush for implant
    "REWORK",     # Q20 shade error
    "PRICING",    # Q21 ZH zenostar price
    "TECHNICAL",  # Q22 ZH digital scan
    "MATERIAL",   # Q23 ZH bruxism
    "REWORK",     # Q24 ZH shade mismatch
    "PROGRESS",   # Q25 FR crown lead time
    "BILLING",    # Q26 FR payment methods
    "MATERIAL",   # Q27 FR monolithic vs layered
    "PROGRESS",   # Q28 FR order not arrived
    "PRICING",    # Q29 inlay price
    "PROGRESS",   # Q30 bridge lead time
    "BILLING",    # Q31 credit card
    "BILLING",    # Q32 full refund  ← expected KB_MISS
    "OTHER",      # Q33 competitor   ← expected KB_MISS
    "PRICING",    # Q34 PMMA provisional
    "PRICING",    # Q35 DE zenostar price
    "MATERIAL",   # Q36 DE bruxism material
    "PROGRESS",   # Q37 DE crown lead time
    "PRICING",    # Q38 NL e.max price
    "PROGRESS",   # Q39 NL denture lead time
    "PRICING",    # Q40 ES zenostar price
    "PRICING",    # Q41 ES rush surcharge
    "BILLING",    # Q42 ZH credit card
]

# ── Questions where KB_MISS is the correct/expected answer ───────────────────
EXPECTED_KB_MISS = {31, 32}   # Q32 full refund, Q33 competitor comparison (0-indexed)

# ── Acceptable source files per question ──────────────────────────────────────
EXPECTED_SOURCES = [
    # original 28
    {"pricing.txt", "faq.txt"},              #  0  Q1
    {"pricing.txt", "faq.txt"},              #  1  Q2
    {"pricing.txt", "faq.txt"},              #  2  Q3
    {"pricing.txt"},                         #  3  Q4
    {"pricing.txt"},                         #  4  Q5
    {"pricing.txt", "faq.txt"},              #  5  Q6
    {"pricing.txt"},                         #  6  Q7
    {"pricing.txt", "faq.txt"},              #  7  Q8
    {"faq.txt", "pricing.txt", "order_process.txt"},  #  8  Q9
    {"order_process.txt", "faq.txt"},        #  9  Q10
    {"order_process.txt"},                   # 10  Q11
    {"faq.txt"},                             # 11  Q12
    {"order_process.txt", "faq.txt"},        # 12  Q13
    {"faq.txt"},                             # 13  Q14
    {"faq.txt", "materials.txt"},            # 14  Q15
    {"materials.txt", "faq.txt"},            # 15  Q16
    {"materials.txt"},                       # 16  Q17
    {"materials.txt"},                       # 17  Q18
    {"faq.txt", "order_process.txt"},        # 18  Q19
    {"faq.txt"},                             # 19  Q20
    {"pricing.txt", "faq.txt"},              # 20  Q21
    {"faq.txt"},                             # 21  Q22
    {"faq.txt", "materials.txt"},            # 22  Q23
    {"faq.txt"},                             # 23  Q24
    {"order_process.txt", "faq.txt"},        # 24  Q25
    {"faq.txt"},                             # 25  Q26
    {"materials.txt", "faq.txt"},            # 26  Q27
    {"order_process.txt", "faq.txt"},        # 27  Q28
    # new 14
    {"pricing.txt", "faq.txt"},              # 28  Q29  inlay price
    {"order_process.txt", "faq.txt"},        # 29  Q30  bridge lead time
    {"faq.txt"},                             # 30  Q31  credit card
    set(),                                   # 31  Q32  full refund      (KB_MISS expected)
    set(),                                   # 32  Q33  competitor       (KB_MISS expected)
    {"pricing.txt", "faq.txt", "materials.txt"},  # 33  Q34  PMMA provisional
    {"pricing.txt", "faq.txt"},              # 34  Q35  DE zenostar price
    {"faq.txt", "materials.txt"},            # 35  Q36  DE bruxism material
    {"order_process.txt", "faq.txt"},        # 36  Q37  DE crown lead time
    {"pricing.txt", "faq.txt"},              # 37  Q38  NL e.max price
    {"order_process.txt", "faq.txt"},        # 38  Q39  NL denture lead time
    {"pricing.txt", "faq.txt"},              # 39  Q40  ES zenostar price
    {"faq.txt", "pricing.txt", "order_process.txt"},  # 40  Q41  ES rush
    {"faq.txt"},                             # 41  Q42  ZH credit card
]

# ── Snippet-level checks where source file alone is insufficient ──────────────
SNIPPET_CHECKS = {
    # original (unchanged)
    9:  lambda s: "5 to 7" in s and "7 to 10" not in s,           # Q10: crown 5-7d not implant
    13: lambda s: "STL" in s or "scan file" in s.lower(),          # Q14: digital scan format
    18: lambda s: "implant" in s.lower() and "not available" in s.lower(),  # Q19: rush NOT for implant
    24: lambda s: "5 to 7" in s or "5 à 7" in s,                  # Q25: crown 5-7d
    # new
    29: lambda s: "7 to 10" in s,                                  # Q30: bridge 7-10d not crown
    36: lambda s: "5 to 7" in s,                                   # Q37: DE crown 5-7d
    38: lambda s: "10 to 14" in s,                                 # Q39: NL denture 10-14d
}


def _retrieve(question: str, intent: str, max_retries: int = 3) -> dict:
    """Call retrieve_for_email with exponential-backoff retry on transient errors."""
    for attempt in range(max_retries):
        try:
            return retrieve_for_email(question, intent)
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"\n  [transient error, retry {attempt+1}/{max_retries} in {wait}s] {exc}")
                time.sleep(wait)
            else:
                raise


def _verdict(idx: int, source: str, snippet: str, kb_miss: bool) -> str:
    if idx in EXPECTED_KB_MISS:
        return "Y" if kb_miss else "N"
    if kb_miss:
        return "KB_MISS"
    if source not in EXPECTED_SOURCES[idx]:
        return "N"
    if idx in SNIPPET_CHECKS and not SNIPPET_CHECKS[idx](snippet):
        return "N"
    return "Y"


def _load_v3_verdicts() -> dict:
    out = {}
    if V3_CSV.exists():
        with open(V3_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                out[row["Question"]] = row.get("V3 Correct", "?")
    return out


def run_validation() -> None:
    v3_prev = _load_v3_verdicts()

    print(f"Running 42-question benchmark  "
          f"(V3 pipeline: QueryRewrite + HyDE + BM25+MMR + CrossEncoder + DynK)\n")
    print(f"{'#':>2}  {'Prev':^6}  {'Now':^8}  {'Score':>6}  {'k':>2}  {'Source':14}  Question / Rewritten")
    print("─" * 105)

    rows, correct_prev, correct_now = [], 0, 0
    new_correct, new_total = 0, 0

    for i, (question, intent) in enumerate(zip(QUESTIONS, QUESTION_INTENTS), start=1):
        idx = i - 1
        is_new = idx >= 28
        prev = v3_prev.get(question, "new")
        if prev == "Y":
            correct_prev += 1

        result = _retrieve(question, intent)
        kb_miss   = result["kb_miss"]
        score     = result["retrieval_score"]
        rewritten = result["rewritten_query"]
        docs      = result["docs"]
        sources   = result["sources"]
        top_src   = sources[0] if sources else ("kb_miss" if kb_miss else "none")
        snippet   = docs[0].page_content.replace("\n", " ").strip()[:300] if docs else ""
        k_used    = len(docs)

        verdict = _verdict(idx, top_src, snippet, kb_miss)
        if verdict == "Y":
            correct_now += 1
        if is_new:
            new_total += 1
            if verdict == "Y":
                new_correct += 1

        change = (
            " ↑" if prev not in ("Y", "new") and verdict == "Y"
            else " ↓" if prev == "Y" and verdict != "Y"
            else "  "
        )
        tag = " [NEW]" if is_new else ""
        print(f"{i:>2}  {prev:^6}  {verdict:^8}  {score:.4f}  {k_used:>2}  {top_src:14}  "
              f"{question[:38]}{tag}")
        print(f"    {'':6}  {'':8}  {'':6}  {'':2}  {'':14}  "
              f"↳ {rewritten[:72]}{change}")

        rows.append({
            "Question":     question,
            "Lang/Tag":     "new" if is_new else "orig",
            "Intent":       intent,
            "Prev Correct": prev,
            "Correct":      verdict,
            "Score":        score,
            "k":            k_used,
            "Source":       top_src,
            "Rewritten":    rewritten,
            "Snippet":      snippet,
        })

        if i < len(QUESTIONS):
            time.sleep(QUERY_DELAY)

    n = len(QUESTIONS)
    print("─" * 105)
    print(f"\n{'Scope':<28}  {'Correct':>7}  {'Accuracy':>8}")
    print(f"{'Original 28Q (prev V3)':<28}  {correct_prev:>4}/28  {correct_prev/28*100:>7.1f}%")
    print(f"{'Original 28Q (this run)':<28}  {correct_now-new_correct:>4}/28  {(correct_now-new_correct)/28*100:>7.1f}%")
    print(f"{'New 14Q':<28}  {new_correct:>4}/14  {new_correct/14*100:>7.1f}%")
    print(f"{'Total 42Q':<28}  {correct_now:>4}/{n}  {correct_now/n*100:>7.1f}%")

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved → {OUT_CSV}")


if __name__ == "__main__":
    run_validation()
