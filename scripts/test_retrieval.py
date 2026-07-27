"""
test_retrieval.py

Standalone retrieval tester for the local ChromaDB knowledge base.

This script:
1. Opens the local ChromaDB built by build_kb.py
2. Runs similarity search for a user query
3. Prints the retrieved chunks with similarity scores and source files

It does not call an LLM and does not generate replies.
It is used to debug whether the correct knowledge base chunks are retrieved.
"""

import sys
from pathlib import Path

from langchain_chroma import Chroma

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

sys.path.insert(0, str(PROJECT_ROOT))
from agent.embeddings import get_embeddings  # noqa: E402


def get_embedding_function():
    """
    Create the same embedding function used when building the ChromaDB.

    Important:
    The embedding model here must match the model used in build_kb.py —
    both now come from agent/embeddings.py so they can't drift apart.
    """
    return get_embeddings()


def load_vector_database():
    """
    Load the existing local ChromaDB.

    Returns:
        Chroma vector database instance.
    """

    if not CHROMA_DIR.exists():
        raise RuntimeError(
            f"Chroma database not found at {CHROMA_DIR}. "
            "Run `python scripts/build_kb.py` first."
        )

    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=get_embedding_function(),
    )


def test_retrieval(query: str, k: int = 4):
    """
    Run a similarity search and print retrieved chunks.

    Args:
        query: User question or email-style query.
        k: Number of chunks to retrieve.

    Returns:
        List of (Document, score) tuples.
    """

    db = load_vector_database()
    results = db.similarity_search_with_score(query, k=k)

    print(f"\nQ: {query!r}")
    print(f"Top {k} retrieved chunks:")

    for i, (doc, score) in enumerate(results, start=1):
        source = doc.metadata.get("source", "unknown")
        preview = doc.page_content.replace("\n", " ")[:250]

        print(f"\n[{i}] score={score:.4f}")
        print(f"Source: {source}")
        print(f"Content: {preview}...")

    return results


if __name__ == "__main__":
    smoke_tests = [
        "What is the price for a full ceramic crown?",
        "Which material is best for a bruxism patient?",
        "How long does production take?",
        "My order has not arrived — what should I do?",
        "The shade does not match what we ordered.",
    ]

    for question in smoke_tests:
        test_retrieval(question, k=4)