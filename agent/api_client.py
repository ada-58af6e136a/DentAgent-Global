"""
agent/api_client.py

Single shared genai.Client for the entire agent package.

Sharing one instance means:
  • One HTTP connection pool — no per-module TLS overhead.
  • Coordinated backoff — classifier and rag_chain both see the same
    retry state, so concurrent 429s don't trigger N independent
    exponential-backoff storms.
  • One place to change timeout / API key configuration.
"""

import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_lock = threading.Lock()
_client: genai.Client | None = None


def get_client() -> genai.Client:
    """Return the shared genai.Client, creating it on first call (thread-safe)."""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        _client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=60),
        )
    return _client
