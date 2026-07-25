#!/bin/bash
# start.sh — Railway entrypoint for the Stage 2 (real backend) deployment.
#
# Runs both processes this deployment needs in one service, since a single
# Railway service can only have one persistent volume — see agent/paths.py
# and the "Stage 2" section of README.md for why that constraint is what
# shapes this whole file.
#
# run_handler.py (IMAP polling) backgrounds; `streamlit run` stays in the
# foreground as the process Railway actually monitors/restarts. Not
# engineering perfect SIGTERM forwarding to the backgrounded handler here —
# it already tolerates an abrupt kill safely (mark-Seen only after a
# successful queue write; already-queued messages are skipped idempotently
# on next boot), so a hard container stop mid-cycle just means that email
# gets reprocessed on restart, not lost or duplicated.
set -e

python run_handler.py &
HANDLER_PID=$!

streamlit run app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0

kill "$HANDLER_PID" 2>/dev/null || true
