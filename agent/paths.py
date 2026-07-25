"""
agent/paths.py

Single source of truth for the two directories that need to persist across
restarts: the SQLite/log data directory and the chroma_db vector store.

Previously each of agent/db.py, agent/logger.py, agent/analytics.py,
agent/rag_chain.py, and scripts/build_kb.py computed its own path
independently, all relative to the project root. That's fine on a platform
with one filesystem (local dev, or a single Streamlit Cloud container where
nothing needs to survive a redeploy anyway) — but Railway (and similar
platforms) attach a persistent volume at exactly ONE mount path per service.
To keep both the database and the vector store on that one volume, both
need to derive from the same configurable root instead of five independent
hardcoded ones.

PERSISTENT_DATA_DIR unset (the default: local dev, the existing public demo
deployment) → identical behavior to before this file existed, everything
lives under the actual project directory. Set it (e.g. to a Railway volume's
mount path) and both DATA_DIR and CHROMA_DIR move there together.

PROJECT_ROOT is unchanged in meaning — it's still the source code location,
used for things that should NEVER move (knowledge_base/, .env, this repo's
own files), as opposed to DATA_DIR/CHROMA_DIR which are generated/runtime
state that may live somewhere else entirely.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_persistent_root = Path(os.getenv("PERSISTENT_DATA_DIR", str(PROJECT_ROOT)))

DATA_DIR = _persistent_root / "data"
CHROMA_DIR = _persistent_root / "chroma_db"
