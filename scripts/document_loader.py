"""
document_loader.py

Content-aware chunking for the knowledge base:
  - faq.txt        → one Document per Q/A pair
  - pricing.txt    → one Document per product paragraph (within --- sections)
  - other .txt/.md → RecursiveCharacterTextSplitter (1200 chars / 100 overlap)

Near-duplicate chunks (Jaccard word-bag similarity >= 0.45) are removed.
When a FAQ pricing Q/A overlaps with a pricing.txt paragraph, the pricing.txt
version is kept as the authoritative source.
"""

import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"

_GENERIC_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1200,
    chunk_overlap=100,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def chunk_faq(text: str, source: str) -> list:
    """Split on Q: boundaries — each Q/A pair becomes one Document."""
    pairs = re.split(r"\n(?=Q:)", text.strip())
    return [
        Document(page_content=p.strip(), metadata={"source": source, "type": "faq"})
        for p in pairs
        if p.strip().startswith("Q:")
    ]


def chunk_pricing(text: str, source: str) -> list:
    """
    Split by --- section boundaries, then by blank lines within each section.
    Each product paragraph becomes one Document.
    Section-header lines (< 80 chars, no price data) are dropped.
    """
    sections = re.split(r"\n-{3,}\n", text)
    chunks = []
    for section in sections:
        for para in section.split("\n\n"):
            para = para.strip()
            if len(para) < 80:
                continue
            chunks.append(
                Document(
                    page_content=para,
                    metadata={"source": source, "type": "pricing"},
                )
            )
    return chunks


def chunk_generic(text: str, source: str) -> list:
    return _GENERIC_SPLITTER.split_documents(
        [Document(page_content=text, metadata={"source": source})]
    )


def _word_bag(text: str) -> set:
    """Significant words (length >= 4) used for Jaccard dedup."""
    return set(re.findall(r"\b[a-zA-Z0-9]{4,}\b", text.lower()))


def deduplicate_chunks(chunks: list, threshold: float = 0.45) -> list:
    """
    Remove near-duplicates using Jaccard similarity on word bags.
    When a FAQ chunk and a pricing.txt chunk overlap, pricing.txt wins.

    threshold=0.45 catches FAQ pricing Q/As that restate pricing.txt paragraphs
    while keeping distinct Q/As that don't overlap (materials, process, etc.).
    """
    unique: list = []
    bags: list = []

    for chunk in chunks:
        bag = _word_bag(chunk.page_content)
        dup_idx = -1
        for i, existing_bag in enumerate(bags):
            union = existing_bag | bag
            if union and len(existing_bag & bag) / len(union) >= threshold:
                dup_idx = i
                break

        if dup_idx == -1:
            unique.append(chunk)
            bags.append(bag)
        elif "pricing.txt" in chunk.metadata.get("source", ""):
            unique[dup_idx] = chunk
            bags[dup_idx] = bag

    removed = len(chunks) - len(unique)
    print(f"  Dedup: {len(chunks)} → {len(unique)} chunks (removed {removed} near-duplicates)")
    return unique


def load_and_chunk() -> list:
    """Load all KB files with content-aware chunking, then deduplicate."""
    all_chunks: list = []

    for fp in sorted(KNOWLEDGE_BASE_DIR.glob("**/*.txt")):
        text = fp.read_text(encoding="utf-8")
        if fp.name == "faq.txt":
            chunks = chunk_faq(text, str(fp))
        elif fp.name == "pricing.txt":
            chunks = chunk_pricing(text, str(fp))
        else:
            chunks = chunk_generic(text, str(fp))
        print(f"  {fp.name}: {len(chunks)} chunks")
        all_chunks.extend(chunks)

    for fp in sorted(KNOWLEDGE_BASE_DIR.glob("**/*.md")):
        text = fp.read_text(encoding="utf-8")
        chunks = chunk_generic(text, str(fp))
        print(f"  {fp.name}: {len(chunks)} chunks")
        all_chunks.extend(chunks)

    all_chunks = deduplicate_chunks(all_chunks)
    print(f"  Total after dedup: {len(all_chunks)} chunks")
    return all_chunks


def inspect_chunks(chunks: list, limit: int = 10):
    print(f"\n--- First {min(limit, len(chunks))} chunks ---")
    for i, chunk in enumerate(chunks[:limit], start=1):
        src = Path(chunk.metadata.get("source", "unknown")).name
        ctype = chunk.metadata.get("type", "generic")
        preview = chunk.page_content[:250].replace("\n", " ")
        print(f"\n[{i}] {src} ({ctype}) — {len(chunk.page_content)} chars")
        print(preview)


def inspect_faq_chunks(chunks: list):
    print("\n--- FAQ chunks ---")
    faq = [c for c in chunks if "faq.txt" in c.metadata.get("source", "")]
    for i, chunk in enumerate(faq, start=1):
        print(f"\n[FAQ {i}] {len(chunk.page_content)} chars")
        print(chunk.page_content[:200])


if __name__ == "__main__":
    chunks = load_and_chunk()
    inspect_chunks(chunks, limit=5)
    inspect_faq_chunks(chunks)
