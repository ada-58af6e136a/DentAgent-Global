"""
build_kb.py

Builds a local Chroma vector database from the text files in knowledge_base/.

This script:
1. Loads and chunks the knowledge base using document_loader.py
2. Embeds the chunks with Gemini embeddings
3. Stores the embedded chunks in a local ChromaDB directory

Important:
- Re-run this script whenever any .txt file in knowledge_base/ changes.
- Do not commit the generated chroma_db/ directory.
"""

from pathlib import Path
import os
import shutil
import time

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from document_loader import load_and_chunk


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = PROJECT_ROOT / "chroma_db"


def build_knowledge_base(reset: bool = False):
    """
    Build the Chroma vector database from knowledge base chunks.

    Args:
        reset: If True, delete the existing ChromaDB directory before rebuilding.

    Returns:
        Chroma vector database instance.
    """

    load_dotenv(PROJECT_ROOT / ".env")

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY was not found. "
            "Add it to your local .env file before running this script."
        )

    if reset and CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
        print("Cleared existing database.")

    chunks = load_and_chunk()

    print(f"\nEmbedding {len(chunks)} chunks with Gemini embeddings...")

    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=gemini_api_key,
    )

    # Free tier: 100 requests/min. Embed in batches of 80 with a 65s pause
    # between batches so the per-minute quota resets before the next batch.
    BATCH_SIZE = 80
    SLEEP_SECONDS = 65

    first_batch = chunks[:BATCH_SIZE]
    db = Chroma.from_documents(
        documents=first_batch,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    print(f"  Batch 1/{-(-len(chunks)//BATCH_SIZE)}: {len(first_batch)} chunks embedded.")

    for batch_num, start in enumerate(range(BATCH_SIZE, len(chunks), BATCH_SIZE), start=2):
        batch = chunks[start : start + BATCH_SIZE]
        print(f"  Rate-limit pause ({SLEEP_SECONDS}s)...")
        time.sleep(SLEEP_SECONDS)
        db.add_documents(batch)
        print(f"  Batch {batch_num}/{-(-len(chunks)//BATCH_SIZE)}: {len(batch)} chunks embedded.")

    print(f"Done. {len(chunks)} chunks stored in {CHROMA_DIR}/")

    return db


if __name__ == "__main__":
    build_knowledge_base(reset=True)