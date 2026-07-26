"""
debug_crown_retrieval.py

One-off diagnostic for the Q3 failure in run_validation_category_level.py:
"What crown types do you offer and what are their prices?" hits kb_miss
even though pricing.txt now has a crowns overview paragraph.

Prints every stage of retrieve_for_email()'s pipeline manually (query
rewrite, HyDE hypothesis, RRF-merged candidates pre-rerank, CrossEncoder
scores post-rerank) so we can see whether the overview chunk is missing
from the candidate pool entirely, or present but scored too low.

Usage:
    python scripts/debug_crown_retrieval.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent import rag_chain as rc

QUESTION = "What crown types do you offer and what are their prices?"

rc._ensure_initialized()

rewritten = rc._rewrite_query(QUESTION)
hypothesis = rc._generate_hypothesis(QUESTION)
print(f"Rewritten query: {rewritten!r}")
print(f"HyDE hypothesis: {hypothesis!r}\n")

bm25_results = rc._bm25_retriever.invoke(rewritten)
try:
    mmr_results = rc._mmr_retriever.invoke(hypothesis)
except Exception as exc:
    print(f"MMR retrieval failed: {exc}")
    mmr_results = []

print(f"BM25 returned {len(bm25_results)} candidates:")
for d in bm25_results:
    src = Path(d.metadata.get("source", "?")).name
    print(f"  [{src}] {d.page_content[:90]!r}")

print(f"\nMMR returned {len(mmr_results)} candidates:")
for d in mmr_results:
    src = Path(d.metadata.get("source", "?")).name
    print(f"  [{src}] {d.page_content[:90]!r}")

candidates = rc._rrf_merge([mmr_results, bm25_results])
print(f"\nRRF-merged candidate pool ({len(candidates)} total, pre-rerank):")
overview_in_pool = False
for d in candidates:
    src = Path(d.metadata.get("source", "?")).name
    is_overview = "Overview of crown" in d.page_content
    if is_overview:
        overview_in_pool = True
    marker = "  <-- CROWNS OVERVIEW" if is_overview else ""
    print(f"  [{src}] {d.page_content[:90]!r}{marker}")

print(f"\nCrowns overview chunk in candidate pool: {overview_in_pool}")

if candidates:
    pairs = [(rewritten, doc.page_content) for doc in candidates]
    scores = rc._reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: float(x[1]), reverse=True)
    print(f"\nCrossEncoder reranked (threshold={rc.RERANK_THRESHOLD}):")
    for doc, score in ranked:
        src = Path(doc.metadata.get("source", "?")).name
        is_overview = "Overview of crown" in doc.page_content
        marker = "  <-- CROWNS OVERVIEW" if is_overview else ""
        print(f"  score={float(score):+.4f}  [{src}] {doc.page_content[:80]!r}{marker}")
