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
│   ├── run_validation.py    # Run 28-question validation suite
│   ├── archive_old_drafts.py # Move old terminal-state drafts to drafts_archive
│   └── seed_demo_data.py    # Populate data/drafts.db with synthetic demo drafts
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
#   AUTO_SEND_*      — optional; off by default (AUTO_SEND_ENABLED=false).
#                      See "Auto-send" below before turning it on.

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
Includes an "Ops Dashboard" page (volume, latency, token cost, IMAP/SMTP
health, auto-send audit trail) alongside the review queue.

```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser. Press `Ctrl+C` to stop.

### Accuracy report
After accumulating interactions, run the analytics report (human approval
rates per intent, plus shadow-mode calibration — see "Auto-send" below):

```bash
python -m agent.analytics
```

Must be run as a module (`-m`), not `python agent/analytics.py` directly —
the file uses package-relative imports (`from .db import ...`).

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
     eligible for auto-send? (see "Auto-send" below)
       │                              │
       │ no                           │ yes
       ▼                              ▼
  data/drafts.db (SQLite)      send_reply() immediately,
  status=pending_review        logged as status=auto_sent
       │
       ▼
   app.py (Streamlit)
   ├── ✅ Approve → send_reply() via Gmail SMTP
   ├── ✏️  Edit & Approve → edit then send
   └── 🚨 Escalate → log for human handling
```

### Auto-send

Off by default (`AUTO_SEND_ENABLED=false` in `.env`). When enabled, a reply
is sent immediately without human review only if **all** of these hold:

- Intent is on the allow-list (`AUTO_SEND_INTENTS`, default `PRICING,MATERIAL,PROGRESS`)
- The email wasn't flagged `escalate` by the classifier
- Classifier confidence ≥ `AUTO_SEND_CONFIDENCE_THRESHOLD` (default `0.9`)
- Retrieval score ≥ `AUTO_SEND_RETRIEVAL_THRESHOLD` (default `0.5`)
- Sender isn't on `AUTO_SEND_EXCLUDED_CLIENTS` (emails or bare domains, e.g.
  `@vipclinic.com` — always human-handled regardless of how confident the
  model is)

Every auto-sent reply is still written to `data/drafts.db` with
`status='auto_sent'` and visible in the Ops Dashboard's audit table, so
enabling it doesn't remove visibility — it removes the review *gate*.
`agent/analytics.py` reports `auto_sent` as its own bucket, separate from
human `approved`, so approval-rate numbers aren't inflated by unreviewed sends.

**Shadow mode** is always on, no flag needed: `_meets_auto_send_criteria()` in
`agent/email_handler.py` is evaluated for *every* email regardless of
`AUTO_SEND_ENABLED`, and the result is persisted as `drafts.would_auto_send`.
Since every human-reviewed draft already has a real outcome, this quietly
builds up calibration data (would-qualify vs. what the human actually did)
before the feature is ever turned on. Visible on the Ops Dashboard as
"would qualify today," and as a full per-intent breakdown via
`python -m agent.analytics` (`get_shadow_mode_calibration_report()`) — run
that and check the would-be accuracy rate against
`AUTO_SEND_CONFIDENCE_THRESHOLD`/`AUTO_SEND_RETRIEVAL_THRESHOLD` before ever
setting `AUTO_SEND_ENABLED=true`.

**Circuit breaker**: `AUTO_SEND_MAX_PER_HOUR` (default `20`) caps real
auto-sends per rolling hour, checked right before each send — a scoring bug
that made confidence spike incorrectly can't cause an unbounded send burst.
Tripping it falls back to `pending_review`, same as any other auto-send
failure. Visible on the Ops Dashboard as "circuit breaker: X/Y this hour."

### LLM failover

Every Gemini call (`agent/api_client.py:generate_content_tracked()`) fails
over to DeepSeek (`deepseek-v4-flash`, non-thinking mode) if Gemini returns a
transient error — quota exhausted, 503, or timeout. Automatic only: there's no
manual provider switch, and if `DEEPSEEK_API_KEY` isn't set the code behaves
exactly as if this feature didn't exist (the original Gemini error just
propagates, same as before). Per-email token cost is tracked using whichever
provider actually served each call, and `data/drafts.db.used_fallback` records
which emails needed it — visible as a metric on the Ops Dashboard.

Cost is priced per call, not a single flat rate applied to a total afterward.
DeepSeek's automatic context caching means input tokens are billed at one of
two rates depending on cache hit/miss — the response reports the real split
(`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`), so
`agent/api_client.py:_estimate_deepseek_cost_usd()` uses the actual split
rather than assuming every token is the more expensive cache-miss rate.
Falls back to all-cache-miss only if a response is ever missing that field.

### Alerting

Optional Slack notifications (`agent/alerts.py`) for IMAP/SMTP outages and
auto-send circuit breaker trips — set `SLACK_WEBHOOK_URL` in `.env` (a Slack
[Incoming Webhook](https://api.slack.com/messaging/webhooks) URL) to enable;
leave it unset and alerting is a no-op, nothing else depends on it. A plain
HTTPS POST, deliberately not routed through Gmail SMTP — an SMTP outage is
exactly the kind of thing you need to be alerted about, so the alert channel
can't share that failure domain. Edge-triggered: one message when a problem
*starts*, one when it *clears* — not one per poll cycle for the duration of
an outage. A failed Slack POST is logged and swallowed, never raised — this
must not be able to break the pipeline it's monitoring.

### Data retention

`data/drafts.db` grows without bound as emails are processed. Run
`python scripts/archive_old_drafts.py` periodically (by hand or via cron) to
move terminal-state drafts (`approved`/`edited`/`escalated`/`auto_sent`)
older than `DRAFTS_ARCHIVE_AFTER_DAYS` (default `90`) into `drafts_archive` —
same schema, same file, just out of the table the Ops Dashboard and hot-path
queries hit. `pending_review` drafts are never archived regardless of age;
they're still-actionable work, not history. Not run automatically — archival
isn't latency-sensitive, so it doesn't belong in `email_handler.run_loop()`.

---

## Deployment

### Demo deployment (frontend only, no live email polling)

A live demo (Review Dashboard + Ops Dashboard, using synthetic sample data)
can run with **zero real secrets** and **none of the heavy ML dependencies**
— `DEMO_MODE=true` makes `app.py` skip importing `agent.email_handler`
entirely, which is what pulls in `chromadb` / `sentence-transformers` (and
`torch`) / `langchain_*` in the first place. Approve/Edit&Approve still
update draft status; they just don't call real SMTP.

`data/` is gitignored, so a fresh deploy has no `drafts.db` at all — `app.py`
self-seeds synthetic data (`scripts/seed_demo_data.py`, original content, not
derived from real interactions) automatically the first time it boots against
an empty table. Nothing to run by hand for a deploy; the script is still
there if you want to seed a local DB manually for testing.

**Deploy to [Streamlit Community Cloud](https://streamlit.io/cloud)** (free):

1. Push this repo to GitHub (already set up: `ada-58af6e136a/DentAgent-Global`)
2. On share.streamlit.io: **New app** → pick this repo/branch
3. Main file path: `app.py`
4. Advanced settings → **Python dependencies file**: `requirements-demo.txt`
   (not `requirements.txt` — the slim file skips the ML stack the demo
   doesn't use)
5. Advanced settings → **Secrets**: add `DEMO_MODE = "true"`
6. Deploy

That's the only configuration the demo needs — no `GEMINI_API_KEY`, no
Gmail credentials, nothing else.

### Known limitation: this doesn't cover the live backend

Streamlit Community Cloud runs a single app process — it has no facility for
also running `run_handler.py` (the IMAP polling loop) as a second, always-on
worker. Running the full pipeline live (not just the dashboard demo) will
need a platform that supports multi-service deploys (e.g. Railway, Render,
Fly.io) with a real shared database instead of local SQLite. Not covered
here — this section is deliberately scoped to the demo-only deployment.

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

**Version 1**

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Requirements analysis, knowledge base creation, tech selection | ✅ Complete |
| 2 | ChromaDB vector store, embedding pipeline, validation | ✅ Complete |
| 3 | Core agent — classifier, RAG chain, Streamlit demo | ✅ Complete |
| 4 | Live email inbox, SMTP sending, human review dashboard, analytics | ✅ Complete |
| 5 | Reliability hardening — SQLite queue, structured logging, connection pooling, graceful shutdown, KB hot-reload | ✅ Complete |
| 6 | Confidence-driven auto-send, token/latency/cost tracking, Ops Dashboard | ✅ Complete |

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
