"""
build_kb.py

Builds a local Chroma vector database from the text files in knowledge_base/.

This script:
1. Loads and chunks the knowledge base using document_loader.py
2. Embeds the chunks with a local embedding model (agent/embeddings.py)
3. Stores the embedded chunks in a local ChromaDB directory

Important:
- Re-run this script whenever any .txt file in knowledge_base/ changes.
- Do not commit the generated chroma_db/ directory.
"""

from pathlib import Path
import shutil
import sys
import time

from dotenv import load_dotenv
from langchain_chroma import Chroma

# Fix M: explicit sys.path so document_loader is importable regardless of CWD.
# Python adds the script's own directory to sys.path[0] when run directly, but
# not when build_kb is imported as a module from another script.
sys.path.insert(0, str(Path(__file__).parent))
from document_loader import load_and_chunk

# Also need the project root importable for `from agent.paths import ...` below
# — present automatically when this module is imported from within the app
# (e.g. agent/rag_chain.py's auto-build), but not when run standalone via
# `python scripts/build_kb.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.paths import PROJECT_ROOT, CHROMA_DIR
from agent.embeddings import get_embeddings, EMBEDDING_MODEL_NAME


def build_knowledge_base(reset: bool = False):
    """
    Build the Chroma vector database from knowledge base chunks.

    Args:
        reset: If True, delete the existing ChromaDB directory before rebuilding.

    Returns:
        Chroma vector database instance.
    """

    load_dotenv(PROJECT_ROOT / ".env")

    if reset and CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
        print("Cleared existing database.")

    chunks = load_and_chunk()

    print(f"\nEmbedding {len(chunks)} chunks locally with {EMBEDDING_MODEL_NAME}...")

    # Local model — no API rate limit, so unlike the old Gemini-embeddings
    # path this doesn't need batching with rate-limit sleep pauses between
    # calls. One shot for the whole corpus.
    db = Chroma.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        persist_directory=str(CHROMA_DIR),
    )

    # Fix L: write a build timestamp so rag_chain.py can detect when the KB
    # has been rebuilt and trigger a hot reload without a process restart.
    ts_file = CHROMA_DIR / ".build_timestamp"
    ts_file.write_text(str(time.time()))

    # Records which embedding model produced these vectors, so rag_chain.py
    # can detect a stale chroma_db built with a different (e.g. old Gemini)
    # embedding model — same dimensionality/space mismatch either way — and
    # force a rebuild instead of loading incompatible vectors.
    model_file = CHROMA_DIR / ".embedding_model"
    model_file.write_text(EMBEDDING_MODEL_NAME)

    print(f"Done. {len(chunks)} chunks stored in {CHROMA_DIR}/")

    return db


if __name__ == "__main__":
    build_knowledge_base(reset=True)