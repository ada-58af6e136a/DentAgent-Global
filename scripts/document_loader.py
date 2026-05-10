"""
document_loader.py

Loads plain-text knowledge base files and splits them into retrievable chunks.

This script is used before building the vector database. Its main purpose is
to inspect whether the knowledge base documents are loaded correctly and
whether FAQ Q:/A: pairs remain intact inside the same chunk.
"""

from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"


def load_and_chunk(chunk_size: int = 900, chunk_overlap: int = 100):
    """
    Load all .txt files from knowledge_base/ and split them into chunks.

    Args:
        chunk_size: Maximum character length of each chunk.
        chunk_overlap: Number of overlapping characters between chunks.

    Returns:
        List of LangChain Document chunks.
    """

    loader = DirectoryLoader(
        str(KNOWLEDGE_BASE_DIR),
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
    )

    docs = loader.load()

    print(f"Loaded {len(docs)} documents:")
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        print(f"  {source} — {len(doc.page_content)} chars")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = splitter.split_documents(docs)

    print(f"\nTotal chunks: {len(chunks)}")
    return chunks


def inspect_chunks(chunks, limit: int = 10):
    """
    Print the first chunks for visual inspection.
    """

    print(f"\n--- First {min(limit, len(chunks))} chunks for inspection ---")

    for i, chunk in enumerate(chunks[:limit], start=1):
        source = chunk.metadata.get("source", "unknown")
        content = chunk.page_content.replace("\n", " ")

        print(f"\n[{i}] Source: {source}")
        print(f"Length: {len(chunk.page_content)} chars")
        print(f"Content: {content[:250]}")


def inspect_faq_chunks(chunks):
    """
    Print only faq.txt chunks to check whether Q:/A: pairs remain together.
    """

    print("\n--- FAQ chunks for Q:/A: inspection ---")

    faq_chunks = [
        chunk for chunk in chunks
        if "faq.txt" in chunk.metadata.get("source", "")
    ]

    if not faq_chunks:
        print("No faq.txt chunks found.")
        return

    for i, chunk in enumerate(faq_chunks, start=1):
        print(f"\n[FAQ chunk {i}]")
        print(f"Length: {len(chunk.page_content)} chars")
        print(chunk.page_content)


if __name__ == "__main__":
    chunks = load_and_chunk()
    inspect_chunks(chunks, limit=10)
    inspect_faq_chunks(chunks)