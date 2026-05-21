# DentAgent-Global

A multilingual AI customer service agent for international dental prosthetics manufacturing. Handles email inquiries from clinics across six countries by classifying intent, querying a knowledge base, drafting professional replies in the client's language, and sending approved replies via Gmail.

---

## Overview

**Problem:** International dental clinics send inquiries at all hours across time zones. Manual CS coverage is expensive, inconsistent, and vulnerable to staff turnover.

**Solution:** RAG + LLM pipeline that automates the full loop — email in → language detection → intent classification → knowledge base retrieval → multilingual reply draft → human review → send.

**Languages supported:** English, French, German, Dutch, Spanish, Chinese

**Intent categories:** PRICING / MATERIAL / PROGRESS / TECHNICAL / REWORK / BILLING / OTHER

---

## Project Structure

```
DentAgent-Global/
├── agent/                   # Core pipeline package
│   ├── __init__.py
│   ├── classifier.py        # Language detection + intent classification
│   ├── email_handler.py     # IMAP polling, body decoding, SMTP sending
│   ├── rag_chain.py         # ChromaDB retrieval + reply generation
│   ├── system_prompt.py     # Agent rulebook (SYSTEM_PROMPT constant)
│   └── analytics.py         # Interaction logging and accuracy reporting
│
├── knowledge_base/          # Plain-text source documents for RAG
│   ├── pricing.txt
│   ├── materials.txt
│   ├── order_process.txt
│   ├── faq.txt
│   └── tech_selection.md
│
├── scripts/                 # Utility scripts
│   ├── document_loader.py   # Load and chunk knowledge base files
│   ├── build_kb.py          # Build ChromaDB vector database
│   ├── test_retrieval.py    # Debug retrieval without LLM
│   └── run_validation.py    # Run 28-question validation suite
│
├── tests/                   # Test scripts
│   ├── test_imap.py         # Verify Gmail IMAP connection
│   ├── test_gemini.py       # Verify Gemini API connection
│   ├── test_api.py          # Verify Anthropic/OpenAI API connections
│   └── test_emails/         # Sample client emails
│
├── docs/                    # Project documentation
│   ├── scenario_map.md      # CS scenario types and escalation rules
│   └── email_system_audit.md
│
├── validation/              # Validation results
│   ├── Validation_Results_V0_28Q.csv
│   └── Validation_Results_V1_28Q.csv
│
├── data/                    # Runtime data — gitignored, never commit
│   ├── draft_queue.jsonl    # Pending drafts awaiting human review
│   ├── processed_queue.jsonl
│   └── interaction_log.jsonl
│
├── chroma_db/               # ChromaDB vector store (generated, gitignored)
├── app.py                   # Streamlit review dashboard
├── run_handler.py           # Entry point for email polling loop
├── .env.example             # API key template
└── requirements.txt
```

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/ada-58af6e136a/DentAgent-Global.git
cd DentAgent-Global

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env
# Edit .env and fill in:
#   GEMINI_API_KEY   — get one free at aistudio.google.com
#   GMAIL_EMAIL      — the Gmail account used to send/receive
#   GMAIL_PASSWORD   — Gmail App Password (not your login password)
#                      Generate at: myaccount.google.com/apppasswords

# 5. Build the ChromaDB vector database
python scripts/build_kb.py
```

---

## Running

### Email polling loop
Polls the Gmail inbox every 60 seconds, classifies each email, and saves a draft reply to `data/draft_queue.jsonl`.

```bash
python run_handler.py
```

### Review dashboard
Streamlit UI where CS staff can read drafts, edit, and approve sending.

```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser. Press `Ctrl+C` to stop.

### Accuracy report
After accumulating interactions, run the analytics report:

```bash
python agent/analytics.py
```

---

## How It Works

```
Incoming email (IMAP)
       │
       ▼
  email_handler.py
  ├── decode_str()      — handles encoded headers (UTF-8, GB2312, etc.)
  ├── extract_body()    — charset-aware body decoding for CJK emails
  └── process_email()
        │
        ├── classifier.py → intent + language + escalate flag
        │   ├── CJK fast-path for Chinese detection
        │   └── Gemini 2.5 Flash for intent classification
        │
        └── rag_chain.py (if not escalated)
            ├── ChromaDB retrieval (top-4 chunks, multilingual embeddings)
            └── Gemini 2.5 Flash reply generation in client's language
                │
                ▼
         draft_queue.jsonl
                │
                ▼
           app.py (Streamlit)
           ├── ✅ Approve → send_reply() via Gmail SMTP
           ├── ✏️  Edit & Approve → edit then send
           └── 🚨 Escalate → log for human handling
```

---

## Validation Results

28-question test suite across English, French, and Chinese:

| Category | Score |
|----------|-------|
| English (20Q) | 16/20 — 80% |
| Multilingual (8Q) | 7/8 — 87.5% |
| Overall | 23/28 — 82.1% |

Full results in `validation/Validation_Results_V1_28Q.csv`.

---

## Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Requirements analysis, knowledge base creation, tech selection | ✅ Complete |
| 2 | ChromaDB vector store, embedding pipeline, validation | ✅ Complete |
| 3 | Core agent — classifier, RAG chain, Streamlit demo | ✅ Complete |
| 4 | Live email inbox, SMTP sending, human review dashboard, analytics | ✅ Complete |
| 5 | Auto-send for standard intents, analytics dashboard | Not started |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM | Gemini 2.5 Flash (Google AI) |
| Embeddings | gemini-embedding-001 (multilingual) |
| Vector store | ChromaDB |
| Framework | LangChain |
| UI | Streamlit |
| Email | imaplib (IMAP) + smtplib (SMTP) via Gmail |
| Language detection | langdetect + CJK heuristic |
| Retry logic | tenacity (exponential backoff for 503/429) |
