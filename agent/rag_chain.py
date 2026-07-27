import math
import re
import threading
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from sentence_transformers import CrossEncoder
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

from .api_client import generate_content_tracked, _is_transient
from .embeddings import get_embeddings, EMBEDDING_MODEL_NAME
from .system_prompt import SYSTEM_PROMPT
from .logger import get_logger
from .paths import PROJECT_ROOT, CHROMA_DIR

log = get_logger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

# ── Fix D: Lazy initialization ────────────────────────────────────────────────
# All heavy components (ChromaDB, BM25, CrossEncoder) are deferred until the
# first actual retrieval call. This means:
#   • Importing this module never crashes (no ChromaDB required at import time)
#   • app.py starts instantly — no 120 MB model download on Streamlit boot
#   • concurrent callers are safe: double-checked locking prevents double-init
_init_lock = threading.Lock()
_initialized = False

_embeddings = None
_db = None
_bm25_retriever = None
_mmr_retriever = None
_reranker = None

# ── Fix L: KB hot reload ─────────────────────────────────────────────────────
# build_kb.py writes chroma_db/.build_timestamp on every rebuild. We cache the
# timestamp seen at init time and compare on each retrieval call. If the file
# is newer, we reset _initialized so the next call re-loads all retrievers from
# the updated ChromaDB — no process restart required.
_kb_build_ts: float = 0.0

_candidate_k = 10
RERANK_TOP_K = 4
RERANK_THRESHOLD = 0.0

INTENT_K_MAP: dict[str, int] = {
    "PRICING":   3,   # was 2; raised to 3 so LLM sees both available + exception chunks for nuanced policy questions
    "MATERIAL":  3,
    "TECHNICAL": 5,
    "PROGRESS":  2,
    "REWORK":    3,
    "BILLING":   2,
    "OTHER":     3,
}


def _read_kb_timestamp() -> float:
    """Return the mtime written by build_kb.py, or 0.0 if not present."""
    ts_file = CHROMA_DIR / ".build_timestamp"
    try:
        return float(ts_file.read_text().strip())
    except Exception:
        return 0.0


def _check_kb_staleness() -> None:
    """Reset _initialized if build_kb.py has rebuilt the KB since last init.

    Called at the top of retrieve_for_email(). Cheap when the KB is current
    (one file read). On mismatch, drops all cached retrievers so
    _ensure_initialized() reloads them from the updated ChromaDB on the
    next call — hot reload with no process restart.
    """
    global _initialized, _kb_build_ts, _embeddings, _db
    global _bm25_retriever, _mmr_retriever, _reranker

    if not _initialized:
        return
    current_ts = _read_kb_timestamp()
    if current_ts <= _kb_build_ts:
        return
    with _init_lock:
        if _read_kb_timestamp() <= _kb_build_ts:
            return
        import logging
        logging.getLogger(__name__).info(
            "KB rebuild detected (old=%.0f new=%.0f) — reloading retrievers",
            _kb_build_ts, current_ts,
        )
        _initialized = False
        _embeddings = _db = _bm25_retriever = _mmr_retriever = _reranker = None


def _ensure_initialized() -> None:
    """
    Initialize ChromaDB, BM25, and CrossEncoder on first call.

    Double-checked locking pattern:
      - First `if` avoids acquiring the lock on every call after init (fast path).
      - Second `if` inside the lock prevents double-initialization when two
        threads race past the first check simultaneously.
    """
    global _initialized, _kb_build_ts
    global _embeddings, _db, _bm25_retriever, _mmr_retriever, _reranker

    if _initialized:
        return

    with _init_lock:
        if _initialized:
            return

        if not CHROMA_DIR.exists():
            # chroma_db/ is gitignored (it's a build artifact, not source) —
            # a fresh deploy on ephemeral storage (e.g. Streamlit Community
            # Cloud) never has it. Build it from knowledge_base/*.txt (which
            # IS committed) on first use instead of crashing and requiring a
            # manual `python scripts/build_kb.py` that can't be run on a
            # read-only-except-for-this-process cloud container anyway.
            log.info("chroma_db not found — building it now from knowledge_base/ "
                      "(expected on first boot of a fresh deploy)")
            from scripts.build_kb import build_knowledge_base
            build_knowledge_base(reset=False)
        else:
            # An existing chroma_db may have been built with a different
            # embedding model (e.g. a persistent volume from before the
            # switch away from Gemini embeddings) — a missing marker file
            # means the same thing, since it predates this check. Its
            # vectors live in a different space/dimensionality than the
            # current model produces, so loading it as-is would silently
            # return meaningless similarity scores rather than a clean
            # error. Rebuild from scratch instead.
            marker = CHROMA_DIR / ".embedding_model"
            built_with = marker.read_text().strip() if marker.exists() else None
            if built_with != EMBEDDING_MODEL_NAME:
                log.warning("chroma_db embedding model mismatch (built_with=%r, "
                            "current=%r) — rebuilding", built_with, EMBEDDING_MODEL_NAME)
                from scripts.build_kb import build_knowledge_base
                build_knowledge_base(reset=True)

        _embeddings = get_embeddings()

        _db = Chroma(
            persist_directory=str(CHROMA_DIR),
            embedding_function=_embeddings,
        )

        raw = _db.get(include=["documents", "metadatas"])
        bm25_corpus = [
            Document(page_content=d, metadata=m)
            for d, m in zip(raw["documents"], raw["metadatas"])
        ]
        _bm25_retriever = BM25Retriever.from_documents(bm25_corpus, k=_candidate_k)

        _mmr_retriever = _db.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": _candidate_k,
                "fetch_k": _candidate_k * 3,
                "lambda_mult": 0.7,
            },
        )

        # ~120 MB model; downloaded from HuggingFace on first run and cached.
        # Multilingual: handles zh/fr/de/nl/es queries against English KB chunks.
        _reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")

        _kb_build_ts = _read_kb_timestamp()   # Fix L: snapshot current KB version
        _initialized = True


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
        response = generate_content_tracked(
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
            "If the inquiry asks broadly about a category (e.g. 'what dentures do you offer') "
            "rather than one specific product, briefly name each relevant product type in that "
            "category rather than answering as if only one was asked about. "
            "Output only the answer, nothing else.\n\n"
            f"Inquiry:\n{email_body[:500]}"
        )
        response = generate_content_tracked(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
        )
        return response.text.strip() or email_body
    except Exception:
        return email_body


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
    _check_kb_staleness()   # Fix L: reload retrievers if KB was rebuilt
    _ensure_initialized()

    # 2.1 clean query for keyword matching and reranking
    rewritten = _rewrite_query(email_body)
    # 2.2 KB-style hypothesis for dense semantic search
    hypothesis = _generate_hypothesis(email_body)

    # Stage 1: hybrid retrieval (3.1 + 3.4)
    bm25_results = _bm25_retriever.invoke(rewritten)
    try:
        mmr_results = _mmr_retriever.invoke(hypothesis)
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


# ── Markdown safety net ──────────────────────────────────────────────────────
# Replies are sent as MIMEText "plain" (agent/email_handler.py:send_reply) —
# not rendered, so markdown syntax the LLM emits shows up as literal
# characters in the customer's inbox. SYSTEM_PROMPT now says not to use
# markdown, but prompt instructions aren't 100% reliable on their own (see
# today's HyDE fix, where "don't invent prices" alone didn't stop the model
# from inventing a brand name instead) — this is a code-side backstop, not a
# replacement for the prompt instruction.
# Underscore variants need \b guards — _ counts as a word character in regex,
# so without them "Price_per_unit" would be mangled into "Priceperunit"
# (matched as italic) instead of left alone.
_MD_BOLD_ITALIC = re.compile(
    r"\*\*(.+?)\*\*|\*(.+?)\*|\b__(.+?)__\b|\b_(.+?)_\b"
)
_MD_HEADING = re.compile(r"^#{1,6}[ \t]+", re.MULTILINE)


def _strip_markdown(text: str) -> str:
    """Strip common markdown artifacts (bold/italic/headings) from LLM output."""
    if not text:
        return text
    text = _MD_BOLD_ITALIC.sub(lambda m: next(g for g in m.groups() if g is not None), text)
    text = _MD_HEADING.sub("", text)
    return text


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

    response = generate_content_tracked(
        model="gemini-2.5-flash",
        contents=[
            {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_message}]}
        ],
    )

    return {
        "reply": _strip_markdown(response.text.strip()),
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
