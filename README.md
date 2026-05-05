# DentAgent-Global

A multilingual AI customer service agent for international dental prosthetics manufacturing. Handles 24/7 email inquiries from clinics across six countries by reading incoming emails, classifying intent, querying a knowledge base, and drafting professional replies in the client's language.

---

## Overview

**Problem:** International dental clinics send inquiries at all hours across time zones. Manual CS coverage is expensive, inconsistent, and vulnerable to staff turnover.

**Solution:** RAG + LLM pipeline that automates the full loop — email in → language detection → intent classification → knowledge base retrieval → multilingual reply draft.

**Languages supported:** English, French, German, Dutch, Spanish, Chinese

**Intent categories:** Pricing query / Order progress / Material recommendation / Complaint / Other

---

## Project Structure

```
DentAgent-Global/
├── knowledge_base/          # Plain-text source documents for RAG
│   ├── pricing.txt          # Product pricing by material and type
│   ├── materials.txt        # Material specs, use cases, comparisons
│   ├── order_process.txt    # Production stages, lead times, delays
│   └── faq.txt              # 15–20 Q&A pairs covering common inquiries
├── src/                     # Agent source code
├── scripts/                 # Utility scripts (e.g. build_kb.py to vectorise KB)
├── tests/
│   └── test_emails/         # Simulated client emails for demo validation
├── chroma_db/               # ChromaDB vector store (generated, not committed)
├── .env.example             # API key template
├── requirements.txt
└── plan/                    # Project planning documents
```

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/ada-58af6e136a/DentAgent-Global.git
cd DentAgent-Global

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

---

## Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Requirements analysis & technology selection | In progress |
| 2 | Knowledge base & RAG setup (ChromaDB) | Not started |
| 3 | Core agent development (prompt, email integration, business logic) | Not started |
| 4 | Testing & iterative optimisation | Not started |
| 5 | Deployment & ongoing operations | Not started |

---

## Knowledge Base

The knowledge base is composed of four plain-text files in `knowledge_base/`. Each file is written in self-contained paragraph form so the LLM can quote entries directly in replies without additional context.

All numbers (prices, lead times) must be verified by CS staff or management before the files are committed for production use.

Once the `.txt` files are ready, run `scripts/build_kb.py` to chunk and vectorise them into ChromaDB using the `text-embedding-3-large` multilingual embedding model.

---

## Tech Stack

- **LLM:** Claude API (Anthropic)
- **Framework:** LangChain
- **Vector store:** ChromaDB
- **Embeddings:** text-embedding-3-large
- **Email integration:** Gmail API / imaplib
