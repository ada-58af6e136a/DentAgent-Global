# DentAgent-Global

A multilingual AI customer service agent for international dental prosthetics manufacturing. Handles email inquiries from clinics across six countries by classifying intent, querying a knowledge base, and drafting professional replies in the client's language.

---

## Overview

**Problem:** International dental clinics send inquiries at all hours across time zones. Manual CS coverage is expensive, inconsistent, and vulnerable to staff turnover.

**Solution:** RAG + LLM pipeline that automates the full loop — email in → language detection → intent classification → knowledge base retrieval → multilingual reply draft.

**Languages supported:** English, French, German, Dutch, Spanish, Chinese

**Intent categories:** PRICING / MATERIAL / PROGRESS / TECHNICAL / REWORK / BILLING / OTHER

---

## Project Structure

```
DentAgent-Global/
├── knowledge_base/          # Plain-text source documents for RAG
│   ├── pricing.txt          # Product pricing by material and type
│   ├── materials.txt        # Material specs, use cases, comparisons
│   ├── order_process.txt    # Production stages, lead times, delays
│   ├── faq.txt              # Q&A pairs covering common inquiries
│   └── tech_selection.md    # Technology decision rationale
├── scripts/                 # Phase 2 utility scripts
│   ├── document_loader.py   # Load and chunk knowledge base files
│   ├── build_kb.py          # Build ChromaDB vector database
│   ├── test_retrieval.py    # Debug retrieval without LLM
│   └── run_validation.py    # Run 28-question validation suite
├── docs/                    # Project documentation
│   ├── scenario_map.md      # CS scenario types and escalation rules
│   └── email_system_audit.md
├── tests/
│   └── test_emails/         # Sample client emails for testing
├── system_prompt.py         # Agent rulebook (SYSTEM_PROMPT constant)
├── classifier.py            # Language detection + intent classification
├── rag_chain.py             # ChromaDB retrieval + reply generation
├── app.py                   # Streamlit demo UI
├── chroma_db/               # ChromaDB vector store (generated, not committed)
├── .env.example             # API key template
└── requirements.txt
```

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/ada-58af6e136a/DentAgent-Global.git
cd DentAgent-Global

# 2. Activate your environment (conda recommended)
conda activate mpm2025

# 3. Install dependencies
pip install -r requirements.txt
pip install streamlit langdetect langchain langchain-text-splitters

# 4. Configure API keys
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY (get one free at aistudio.google.com)

# 5. Build the ChromaDB vector database
python scripts/build_kb.py
```

---

## Running the Demo

```bash
conda activate mpm2025
cd DentAgent-Global
streamlit run app.py
```

Then open **http://localhost:8501** in your browser. Paste a client email and click Run.

To stop the server press `Ctrl+C` in the terminal.

---

## Validation Results

28-question test suite across English, French, and Chinese:

| Category | Score |
|----------|-------|
| English (20Q) | 16/20 — 80% |
| Multilingual (8Q) | 7/8 — 87.5% |
| Overall | 23/28 — 82.1% |

Results in `Validation_Results_V1_28Q.csv`.

---

## Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Requirements analysis, knowledge base creation, tech selection | ✅ Complete |
| 2 | ChromaDB vector store, embedding pipeline, validation | ✅ Complete |
| 3 | Core agent — classifier, RAG chain, Streamlit demo | ✅ Complete |
| 4 | Connect real email inbox, logging, monitoring | Not started |
| 5 | Auto-send for standard intents, analytics dashboard | Not started |

---

## Tech Stack

- **LLM:** Gemini 2.5 Flash (Google AI)
- **Embeddings:** gemini-embedding-001
- **Vector store:** ChromaDB
- **Framework:** LangChain
- **UI:** Streamlit
- **Language detection:** langdetect
