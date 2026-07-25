"""
pages/2_Live_Demo.py

Paste a client email, click Run, see the REAL pipeline output — genuine
classify_intent() + generate_reply() calls (DeepSeek primary / Gemini
fallback, real chroma_db retrieval), not pre-seeded static data. This is
what app_demo.py was trying to be before it went stale (wrong import paths
from before the agent/ package restructuring); this page replaces it,
properly integrated into the deployed multipage app.

Unlike app.py's DEMO_MODE, this page necessarily imports the full
classify/rag stack (chromadb/sentence-transformers/torch/langchain_*) —
there's no way to run the real pipeline without them. It never calls
send_reply(), so it doesn't touch the "don't send real email from a public
demo" concern app.py's DEMO_MODE exists for.

Rate limiting: a public, unauthenticated page that triggers real paid API
calls needs a cost/abuse ceiling. Two layers:
  1. st.session_state counter — cheap, catches casual over-clicking within
     one browser session without a DB round-trip.
  2. count_recent_live_demo_runs() — a global rolling-hour cap across ALL
     visitors combined (agent/db.py), so opening a new incognito window
     can't bypass the limit the way a session-only counter could.
"""

import os
import threading
import time

import streamlit as st

from agent.classifier import classify_intent
from agent.rag_chain import generate_reply
from agent.auto_send_rules import meets_auto_send_criteria
from agent.db import record_live_demo_run, count_recent_live_demo_runs

SESSION_MAX_RUNS = int(os.getenv("LIVE_DEMO_SESSION_MAX", "5"))
GLOBAL_MAX_PER_HOUR = int(os.getenv("LIVE_DEMO_MAX_PER_HOUR", "30"))

st.set_page_config(page_title="Live Demo — Dental CS Agent", layout="wide")
st.title("Live Demo")
st.caption(
    "Paste a real client-style email and click Run — this calls the actual "
    "classification + RAG pipeline (DeepSeek, with Gemini as fallback), not "
    "canned data. A real call can take anywhere from a few seconds to "
    "significantly longer depending on provider load."
)

# Pre-warm chroma_db in the background as soon as this page loads, instead
# of waiting for the first Run click. On a freshly-woken container, chroma_db
# doesn't exist yet (see agent/rag_chain.py's auto-build) — building it takes
# ~80s+ (Gemini embedding, rate-limited in batches). Stacking that on top of
# the actual classify+retrieve+generate calls in a single click can run long
# enough to trip a proxy/websocket timeout, which silently resets the page
# with no visible error. Starting the build the moment the page loads means
# it's likely already warm by the time a visitor finishes typing and clicks
# Run. Safe under concurrent visitors: _ensure_initialized() already
# serializes on a lock and no-ops once done (agent/rag_chain.py), so multiple
# sessions landing here around the same time just wait on the same build.
if "kb_prewarm_started" not in st.session_state:
    st.session_state.kb_prewarm_started = True

    def _prewarm_kb() -> None:
        try:
            from agent.rag_chain import _ensure_initialized
            _ensure_initialized()
        except Exception:
            pass  # a real failure here surfaces normally on the actual Run click

    threading.Thread(target=_prewarm_kb, daemon=True).start()

if "live_demo_run_count" not in st.session_state:
    st.session_state.live_demo_run_count = 0

session_remaining = SESSION_MAX_RUNS - st.session_state.live_demo_run_count
st.caption(f"{max(session_remaining, 0)} of {SESSION_MAX_RUNS} runs left this session.")

email_input = st.text_area(
    "Client email",
    height=220,
    placeholder="Paste email text here — any supported language (en/fr/de/nl/es/zh)...",
)
run = st.button("Run", type="primary", disabled=session_remaining <= 0)

if session_remaining <= 0:
    st.warning("You've used all your runs for this session — refresh the page to reset.")

if run and email_input.strip():
    recent = count_recent_live_demo_runs(60)
    if recent >= GLOBAL_MAX_PER_HOUR:
        st.error(
            f"This demo has hit its shared hourly limit ({GLOBAL_MAX_PER_HOUR} "
            f"runs/hour across all visitors) — please try again later."
        )
    else:
        st.session_state.live_demo_run_count += 1
        record_live_demo_run()

        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("**Input**")
            st.text(email_input)

        with col2:
            st.markdown("**Pipeline output**")
            t0 = time.perf_counter()
            with st.spinner("Classifying..."):
                classification = classify_intent(email_input)

            language = classification.get("language", "en")
            intent = classification.get("intent", "OTHER")
            escalate = classification.get("escalate", False)
            confidence = classification.get("confidence", 0.0)
            reason = classification.get("reason", "")

            st.markdown(f"**Language:** `{language}` &nbsp; **Intent:** `{intent}` &nbsp; "
                        f"**Confidence:** `{confidence:.2f}`")
            st.caption(reason)

            retrieval_score = 0.0
            if escalate:
                st.warning("Flagged for escalation — a human would handle this one, "
                           "not an auto-generated reply.")
            else:
                with st.spinner("Retrieving from knowledge base and generating reply..."):
                    result = generate_reply(email_input, language, intent)
                retrieval_score = result.get("retrieval_score", 0.0)

                if result.get("kb_miss"):
                    st.warning(f"Knowledge-base miss (score={retrieval_score:.3f}) — "
                               "would be escalated rather than guessed at.")
                else:
                    st.text_area("Generated reply", value=result["reply"], height=260)
                    with st.expander("Knowledge base sources retrieved"):
                        for source in result["sources"]:
                            st.caption(source)

            would_send = meets_auto_send_criteria(
                intent, confidence, retrieval_score, escalate, "demo-visitor@example.com"
            )
            elapsed = time.perf_counter() - t0
            st.caption(
                f"Would auto-send under current thresholds: `{would_send}` "
                f"&nbsp; (ran in {elapsed:.1f}s)"
            )
elif run:
    st.warning("Please paste an email before clicking Run.")
