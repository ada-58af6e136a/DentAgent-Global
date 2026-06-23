import math
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from google import genai
from sentence_transformers import CrossEncoder
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

from .system_prompt import SYSTEM_PROMPT

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

load_dotenv(PROJECT_ROOT / ".env")

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=os.getenv("GEMINI_API_KEY"),
)

_db = Chroma(
    persist_directory=str(CHROMA_DIR),
    embedding_function=_embeddings,
)

# ── 3.1  Hybrid retrieval: BM25 (exact term) + semantic (vector) ──────────────
# BM25Retriever is initialised from all docs stored in ChromaDB so the two
# retrievers share exactly the same corpus.
_candidate_k = 10

_raw = _db.get(include=["documents", "metadatas"])
_bm25_corpus = [
    Document(page_content=d, metadata=m)
    for d, m in zip(_raw["documents"], _raw["metadatas"])
]
_bm25_retriever = BM25Retriever.from_documents(_bm25_corpus, k=_candidate_k)

# ── 3.4  MMR semantic retriever: diversity over redundancy ────────────────────
# fetch_k=3× candidate_k gives MMR enough candidates to pick diverse ones.
# lambda_mult=0.7 weights relevance slightly above diversity.
_mmr_retriever = _db.as_retriever(
    search_type="mmr",
    search_kwargs={
        "k": _candidate_k,
        "fetch_k": _candidate_k * 3,
        "lambda_mult": 0.7,
    },
)

# ── 4.1  CrossEncoder reranker ────────────────────────────────────────────────
# mmarco-mMiniLMv2-L12-H384-v1: multilingual MS-MARCO trained cross-encoder.
# Handles Chinese/French/German/Dutch/Spanish queries against English KB chunks.
# Downloaded from HuggingFace on first run (~120 MB) and cached locally.
_reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")

RERANK_TOP_K = 4     # default final chunks passed to the LLM
RERANK_THRESHOLD = 0.0  # CrossEncoder logit; below = nothing relevant found

# 3.3 Dynamic k: different intents need different context depth.
# PRICING/PROGRESS need 1-2 focused chunks; TECHNICAL/MATERIAL benefit from more breadth.
INTENT_K_MAP: dict[str, int] = {
    "PRICING":   3,   # was 2; raised to 3 so LLM sees both available + exception chunks for nuanced policy questions
    "MATERIAL":  3,
    "TECHNICAL": 5,
    "PROGRESS":  2,
    "REWORK":    3,
    "BILLING":   2,
    "OTHER":     3,
}


def _rrf_merge(ranked_lists: list, rrf_k: int = 60) -> list:
    """Reciprocal Rank Fusion: merge multiple ranked lists, deduplicating by content.

    Each doc's RRF score = Σ 1/(rrf_k + rank + 1) across all lists it appears in.
    Docs appearing in both BM25 and semantic lists get a natural boost.
    """
    scores: dict = {}
    doc_map: dict = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked):
            key = doc.page_content
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in doc_map:
                doc_map[key] = doc
    return [doc_map[k] for k in sorted(scores, key=lambda k: scores[k], reverse=True)]


# ── 2.1  Query Rewriting ─────────────────────────────────────────────────────
def _rewrite_query(email_body: str) -> str:
    """Strip greeting/signature noise; return one-sentence core query for retrieval.

    Falls back to the original email if the LLM call fails, so retrieval is
    never blocked by a rewriting error.
    """
    try:
        prompt = (
            "Extract the single core question or request from this dental lab email "
            "as one concise sentence. Output only the question, nothing else.\n\n"
            f"Email:\n{email_body[:600]}"
        )
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
        )
        return response.text.strip() or email_body
    except Exception:
        return email_body


# ── 2.2  HyDE (Hypothetical Document Embedding) ───────────────────────────────
def _generate_hypothesis(email_body: str) -> str:
    """Generate a hypothetical KB-style answer to bridge vocabulary gap.

    Semantic search works better when the query vector lives in the same
    embedding space as KB chunks. A product-language hypothesis (prices,
    materials, lead times) is closer to chunk vectors than the original email.
    Falls back to the original email on failure.
    """
    try:
        prompt = (
            "Write a 2–3 sentence knowledge-base answer for this dental lab inquiry. "
            "Use formal product terminology: product names, materials, prices, lead times. "
            "Output only the answer, nothing else.\n\n"
            f"Inquiry:\n{email_body[:500]}"
        )
        response = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
        )
        return response.text.strip() or email_body
    except Exception:
        return email_body


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc)
    return "503" in msg or "UNAVAILABLE" in msg or "429" in msg or "quota" in msg.lower()


def retrieve_for_email(email_body: str, intent: str = "OTHER") -> dict:
    """Full retrieval pipeline — no LLM generation.

    Stages:
      2.1  Query rewriting    → clean keyword query for BM25 + CrossEncoder
      2.2  HyDE               → KB-vocabulary hypothesis for MMR semantic search
      3.1  BM25 + MMR via RRF → diverse, high-recall candidate pool
      3.4  MMR diversity      → already applied on the semantic side
      4.1  CrossEncoder rerank→ precision re-score on (rewritten_query, chunk)
      3.3  Dynamic k          → intent-specific final chunk count

    Returns:
        {
            "docs":             list[Document],   # top-k reranked chunks
            "sources":          list[str],        # filename of each doc
            "retrieval_score":  float,            # sigmoid-normalised best score [0,1]
            "kb_miss":          bool,
            "rewritten_query":  str,              # for logging / debugging
        }
    """
    # 2.1 clean query for keyword matching and reranking
    rewritten = _rewrite_query(email_body)
    # 2.2 KB-style hypothesis for dense semantic search
    hypothesis = _generate_hypothesis(email_body)

    # Stage 1: hybrid retrieval (3.1 + 3.4)
    bm25_results = _bm25_retriever.invoke(rewritten)   # exact-term matching on clean query
    try:
        mmr_results = _mmr_retriever.invoke(hypothesis)  # dense search on KB-vocabulary hypothesis
    except Exception:
        mmr_results = []  # fall back to BM25-only on network / rate-limit error
    candidates = _rrf_merge([mmr_results, bm25_results])

    if not candidates:
        return {
            "docs": [], "sources": [], "retrieval_score": 0.0,
            "kb_miss": True, "rewritten_query": rewritten,
        }

    # Stage 2: CrossEncoder reranking (4.1) — scored against the clean rewritten query
    pairs = [(rewritten, doc.page_content) for doc in candidates]
    rerank_scores = _reranker.predict(pairs)
    ranked = sorted(zip(candidates, rerank_scores), key=lambda x: float(x[1]), reverse=True)

    best_score = float(ranked[0][1])
    retrieval_score = round(1.0 / (1.0 + math.exp(-best_score)), 4)

    if best_score < RERANK_THRESHOLD:
        return {
            "docs": [], "sources": [], "retrieval_score": retrieval_score,
            "kb_miss": True, "rewritten_query": rewritten,
        }

    # 3.3 intent-aware final chunk count
    top_k = INTENT_K_MAP.get(intent, RERANK_TOP_K)
    final_docs = [doc for doc, _ in ranked[:top_k]]
    sources = [Path(doc.metadata.get("source", "unknown")).name for doc in final_docs]

    return {
        "docs": final_docs,
        "sources": sources,
        "retrieval_score": retrieval_score,
        "kb_miss": False,
        "rewritten_query": rewritten,
    }


@retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def generate_reply(email_body: str, language: str, intent: str = "OTHER") -> dict:
    """Run retrieval then generate a reply with the top-k reranked chunks.

    Returns:
        {
            "reply":            str | None,
            "sources":          list[str],
            "retrieval_score":  float,
            "kb_miss":          bool,
        }
    """
    retrieval = retrieve_for_email(email_body, intent)

    if retrieval["kb_miss"]:
        return {
            "reply": None, "sources": [],
            "retrieval_score": retrieval["retrieval_score"], "kb_miss": True,
        }

    context = "\n\n---\n\n".join(doc.page_content for doc in retrieval["docs"])

    user_message = f"""Reply language: {language}

Knowledge base context (use this to answer — do not invent information):
{context}

Client email:
{email_body}"""

    response = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_message}]}
        ],
    )

    return {
        "reply": response.text.strip(),
        "sources": retrieval["sources"],
        "retrieval_score": retrieval["retrieval_score"],
        "kb_miss": False,
    }


if __name__ == "__main__":
    import time

    test_cases = [
        ("What is the price for a full ceramic crown?", "en"),
        ("Quel est le délai de production pour une couronne?", "fr"),
        ("全瓷冠的价格是多少？", "zh"),
        ("What material do you recommend for a bruxism patient needing an anterior crown?", "en"),
        ("Can you help me with my refund?", "en"),  # off-topic — expect kb_miss
    ]

    for i, (email_body, lang) in enumerate(test_cases):
        if i > 0:
            time.sleep(5)
        print(f"\n{'='*60}")
        print(f"({lang}) {email_body}")
        result = generate_reply(email_body, lang)
        if result["kb_miss"]:
            print(f"  KB MISS  (retrieval_score={result['retrieval_score']:.4f})")
        else:
            print(f"  Sources: {result['sources']}")
            print(f"  Retrieval score: {result['retrieval_score']:.4f}")
            print(f"  Reply: {result['reply'][:120]}...")
