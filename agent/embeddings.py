"""
agent/embeddings.py

Local multilingual embedding model, shared by scripts/build_kb.py (build
time) and agent/rag_chain.py (query time) — both must use the exact same
model, since build-time and query-time vectors have to live in the same
space for similarity search to mean anything.

Replaces GoogleGenerativeAIEmbeddings (gemini-embedding-001). That was the
last hard Gemini dependency in the retrieval path — Gemini now only backs
generate_content_tracked()'s transient-failure fallback for text generation
(agent/api_client.py), unrelated to embeddings. Running locally also removes
one network round-trip per email (the MMR retriever's query embedding) and
Gemini's embeddings free-tier rate limit that forced build_kb.py to batch
with sleep pauses (see EMBED_BATCH_SIZE note there — no longer needed).

Model choice: paraphrase-multilingual-MiniLM-L12-v2 — same L12-H384 family
as the CrossEncoder reranker already loaded in rag_chain.py, so no new
size/latency class is introduced. Multilingual for the same reason the
reranker is (rag_chain.py's _ensure_initialized() docstring): queries arrive
in en/fr/de/nl/es/zh against an English-only knowledge base.
"""

import threading

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_lock = threading.Lock()
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


class LocalEmbeddings(Embeddings):
    """Minimal langchain Embeddings adapter around a local SentenceTransformer."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return _get_model().encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return _get_model().encode(text, show_progress_bar=False).tolist()


def get_embeddings() -> LocalEmbeddings:
    return LocalEmbeddings()
