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
├── pages/                   # Streamlit multipage app (alongside app.py)
│   ├── 1_📊_Ops_Dashboard.py # Volume, latency, cost, health, auto-send audit
│   └── 2_🧪_Live_Demo.py     # Real pipeline run on visitor-pasted email text
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
#   DEEPSEEK_API_KEY — primary text-generation provider, get one at platform.deepseek.com
#   GEMINI_API_KEY   — required too (retrieval embeddings + text-generation fallback)
#                      get one free at aistudio.google.com
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

**DeepSeek (`deepseek-v4-flash`, non-thinking mode) is the primary provider**
for text generation — classification and reply generation both go through it
first. Every call (`agent/api_client.py:generate_content_tracked()`) fails
over to Gemini if DeepSeek returns a transient error — rate limit, timeout,
or connection failure (checked via typed OpenAI-SDK exceptions, not just
string matching, so connection-level failures are caught precisely, not just
429s/timeouts). Automatic only: there's no manual provider switch. A
non-transient error (bad request, auth) raises immediately without failover,
since rerouting won't fix a config bug.

Gemini can't be removed from this project even though it's now the fallback
for text generation — `agent/rag_chain.py`'s retrieval step depends on
Gemini's embeddings API (`models/gemini-embedding-001`), which DeepSeek has
no equivalent for. Both `DEEPSEEK_API_KEY` and `GEMINI_API_KEY` are required.

Per-email token cost is tracked using whichever provider actually served
each call, and `data/drafts.db.used_fallback` records which emails needed
Gemini to cover for DeepSeek — visible as a metric on the Ops Dashboard.

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

Two pages, two different jobs:

- **Review Dashboard (`app.py`) + Ops Dashboard** — browse a realistic
  historical backlog (synthetic seed data, `scripts/seed_demo_data.py`,
  original content not derived from real interactions). `DEMO_MODE=true`
  makes `app.py` skip importing `agent.email_handler` entirely — that's what
  pulls in `chromadb`/`sentence-transformers`/`torch`/`langchain_*` — and
  Approve/Edit&Approve update status locally without calling real SMTP.
  `data/` is gitignored, so `app.py` self-seeds the synthetic data
  automatically the first time it boots against an empty table — nothing to
  run by hand for a deploy.
- **Live Demo (`pages/2_🧪_Live_Demo.py`)** — paste any email, get a real
  `classify_intent()` + `generate_reply()` run against the actual pipeline
  (DeepSeek primary, Gemini fallback, real `chroma_db` retrieval). This is
  what actually demonstrates translation/generation quality, not just the UI.
  Rate-limited two ways so a public unauthenticated page can't run up your
  API bill: `LIVE_DEMO_SESSION_MAX` per browser session, and
  `LIVE_DEMO_MAX_PER_HOUR` as a global cap across all visitors
  (`agent/db.py:count_recent_live_demo_runs()`).

Because the Live Demo page exists, the deploy needs the **full**
`requirements.txt` — there's no way to run the real pipeline without
`chromadb`/`sentence-transformers`/`torch`/`langchain_*`, so the earlier
slim `requirements-demo.txt` build-speed optimization no longer applies.
Slower cold start than the frontend-only version, but the demo is now
actually demonstrating the product instead of a static mockup of it.

**Deploy to [Streamlit Community Cloud](https://streamlit.io/cloud)** (free):

1. Push this repo to GitHub (already set up: `ada-58af6e136a/DentAgent-Global`)
2. On share.streamlit.io: **New app** → pick this repo/branch
3. Main file path: `app.py`
4. Advanced settings → **Secrets**: add `DEMO_MODE = "true"`,
   `DEEPSEEK_API_KEY`, and `GEMINI_API_KEY` (both required — see "LLM
   failover" above for why Gemini can't be dropped even though DeepSeek is
   primary)
5. Deploy

### Stage 2: the real backend (private — do not share this link)

Streamlit Community Cloud (above) runs a single app process — it has no
facility for also running `run_handler.py` (the IMAP polling loop) as a
second, always-on worker. This section covers actually running the full
pipeline live, on [Railway](https://railway.com), which does support that.

**This is a completely separate deployment from the public demo above, and
it is not meant to be shared publicly.** The demo deployment uses
`DEMO_MODE=true` and synthetic data specifically so a public link is safe to
hand to anyone. This deployment processes real inbound email into real
drafts — sharing its link would expose real correspondence to anyone who
opens it. Keep the two deployments mentally (and literally) separate.

**Why Railway, and why one service, not two:** Railway services get exactly
one persistent volume each — there's no way for two separate services (say,
a "web" service and a "worker" service) to share the same SQLite file and
chroma_db on this platform without a real networked database instead of
local disk. Rather than migrate to Postgres for this first pass, both
`app.py` and `run_handler.py` run in **one** service, as two processes
sharing that service's one volume (`start.sh` backgrounds `run_handler.py`
and runs `streamlit` in the foreground — Railway's `railway.json` points the
service at it). `agent/paths.py` is what makes this possible: every module
that used to hardcode its own path under the project root now derives
`DATA_DIR`/`CHROMA_DIR` from one `PERSISTENT_DATA_DIR` env var instead —
unset (local dev, the public demo) it's identical to before; set it to the
volume's mount path and everything that needs to persist lands together.

**Setup:**

1. On [railway.com](https://railway.com): **New Project** → **Deploy from GitHub repo** → this repo/branch
2. Add a **Volume** to the service (Settings → Volumes), note its mount path
3. Environment variables (Settings → Variables):
   - `PERSISTENT_DATA_DIR` = the volume's mount path from step 2
   - `DEEPSEEK_API_KEY`, `GEMINI_API_KEY` — both required, see "LLM failover" above
   - `GMAIL_EMAIL`, `GMAIL_PASSWORD` — **use a test/dedicated Gmail account for the initial run, not the real production inbox** (your call on when to switch)
   - `AUTO_SEND_ENABLED=false` — explicit, don't rely on the default. This phase is about accumulating real shadow-mode calibration data (see "Auto-send" above), not sending anything automatically
   - `DEMO_MODE` — leave unset (this is the real app, not the demo)
4. Deploy. Railway auto-detects the Python build; `railway.json` sets the start command to `bash start.sh`
5. This gives you two things running in one place: `run_handler.py` polling the test inbox into real drafts, and the same review-dashboard UI as the demo (but showing real drafts, `DEMO_MODE` off — Approve really sends via that test account's SMTP)
6. Once you trust it, run `python -m agent.analytics` against this deployment's data to see real shadow-mode calibration numbers accumulate — that's the actual prerequisite for ever considering `AUTO_SEND_ENABLED=true`, not a fixed number of test emails

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
