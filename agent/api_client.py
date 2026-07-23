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

import contextvars
import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger(__name__)

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


# ── DeepSeek failover client ──────────────────────────────────────────────────
# Only ever constructed if Gemini has a transient failure — see
# generate_content_tracked(). No DEEPSEEK_API_KEY + Gemini never fails = this
# is never touched.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# deepseek-chat is deprecated 2026-07-24 and maps to deepseek-v4-flash's
# non-thinking mode — target that model directly instead of the alias.
DEEPSEEK_MODEL = "deepseek-v4-flash"

_deepseek_lock = threading.Lock()
_deepseek_client: OpenAI | None = None


def get_deepseek_client() -> OpenAI:
    """Return the shared DeepSeek client (OpenAI-compatible), lazy + thread-safe."""
    global _deepseek_client
    if _deepseek_client is not None:
        return _deepseek_client
    with _deepseek_lock:
        if _deepseek_client is not None:
            return _deepseek_client
        _deepseek_client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=DEEPSEEK_BASE_URL,
            timeout=60,
        )
    return _deepseek_client


def _is_transient(exc: BaseException) -> bool:
    """
    True for rate-limit / quota / availability / timeout errors — the class of
    failure that's worth retrying or failing over for, as opposed to a config
    or request-shape bug that a retry/failover won't fix.

    Single copy shared by classifier.py, rag_chain.py (their @retry decorators)
    and generate_content_tracked() (the Gemini→DeepSeek failover decision below).
    """
    msg = str(exc)
    return (
        "503" in msg or "UNAVAILABLE" in msg
        or "429" in msg or "quota" in msg.lower()
        or "ReadTimeout" in type(exc).__name__
        or "Timeout" in type(exc).__name__
    )


def _extract_text(contents) -> str:
    """
    Normalize the two content shapes used in this codebase down to plain text
    for DeepSeek's OpenAI-style messages=[...] format.

    classifier.py passes a plain string; rag_chain.py passes Gemini's
    [{"role": "user", "parts": [{"text": ...}]}] structure.
    """
    if isinstance(contents, str):
        return contents
    parts = contents[0].get("parts", [])
    return "".join(p.get("text", "") for p in parts)


class _TextResponse:
    """Minimal stand-in for a Gemini response — every caller only reads .text."""
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


# ── Token usage + cost tracking ────────────────────────────────────────────────
# Prices — verify current rates before trusting estimated_cost_usd for anything
# beyond rough tracking; both providers update pricing independently.
GEMINI_INPUT_PRICE_PER_1M = 0.30      # ai.google.dev/pricing (gemini-2.5-flash)
GEMINI_OUTPUT_PRICE_PER_1M = 2.50
# DeepSeek prices input per-token by automatic context-cache status — see
# api-docs.deepseek.com/quick_start/pricing and .../guides/kv_cache. The
# response's usage object reports the real split (prompt_cache_hit_tokens /
# prompt_cache_miss_tokens), so this is priced precisely per call rather than
# assuming every token is a cache miss (the conservative-but-wrong default
# this project used before checking whether the split was available).
DEEPSEEK_CACHE_HIT_PRICE_PER_1M = 0.0028
DEEPSEEK_CACHE_MISS_PRICE_PER_1M = 0.14
DEEPSEEK_OUTPUT_PRICE_PER_1M = 0.28

# ContextVar (not a plain module global) so each ThreadPoolExecutor worker in
# email_handler.run_loop() accumulates its own email's usage without workers
# clobbering each other's totals.
_usage_totals: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "usage_totals", default=None
)


def start_usage_tracking() -> None:
    """Reset the current context's counters. Call once per email."""
    _usage_totals.set({
        "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "cost_usd": 0.0, "fallback_calls": 0,
    })


def get_usage_totals() -> dict:
    """Return this context's accumulated usage/cost/fallback counters."""
    totals = _usage_totals.get()
    if totals:
        return dict(totals)
    return {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "cost_usd": 0.0, "fallback_calls": 0}


def _estimate_gemini_cost_usd(prompt_tokens: int, output_tokens: int) -> float:
    return round(
        prompt_tokens / 1_000_000 * GEMINI_INPUT_PRICE_PER_1M
        + output_tokens / 1_000_000 * GEMINI_OUTPUT_PRICE_PER_1M,
        6,
    )


def _estimate_deepseek_cost_usd(cache_hit_tokens: int, cache_miss_tokens: int,
                                 output_tokens: int) -> float:
    return round(
        cache_hit_tokens / 1_000_000 * DEEPSEEK_CACHE_HIT_PRICE_PER_1M
        + cache_miss_tokens / 1_000_000 * DEEPSEEK_CACHE_MISS_PRICE_PER_1M
        + output_tokens / 1_000_000 * DEEPSEEK_OUTPUT_PRICE_PER_1M,
        6,
    )


def _track_usage(provider: str, prompt_tokens: int, output_tokens: int, total_tokens: int,
                  cost_usd: float, fallback: bool = False) -> None:
    totals = _usage_totals.get()
    if totals is None:
        return
    totals["prompt_tokens"] += prompt_tokens
    totals["output_tokens"] += output_tokens
    totals["total_tokens"] += total_tokens
    totals["cost_usd"] += cost_usd
    if fallback:
        totals["fallback_calls"] += 1


def _call_deepseek(contents) -> "_TextResponse":
    """Send the same prompt to DeepSeek (non-thinking mode) and track its usage."""
    text = _extract_text(contents)
    response = get_deepseek_client().chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": text}],
        extra_body={"thinking": {"type": "disabled"}},
    )

    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
    total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + output_tokens) if usage else 0
    cache_hit_tokens = getattr(usage, "prompt_cache_hit_tokens", 0) or 0 if usage else 0
    cache_miss_tokens = getattr(usage, "prompt_cache_miss_tokens", 0) or 0 if usage else 0
    # If the SDK/response doesn't carry the cache split (older field name, or
    # usage missing entirely), fall back to treating all of it as a cache
    # miss — the conservative default this project used before the split was
    # confirmed available, not a silent underestimate.
    if cache_hit_tokens == 0 and cache_miss_tokens == 0 and prompt_tokens > 0:
        cache_miss_tokens = prompt_tokens

    cost = _estimate_deepseek_cost_usd(cache_hit_tokens, cache_miss_tokens, output_tokens)
    _track_usage("deepseek", prompt_tokens, output_tokens, total_tokens, cost, fallback=True)

    reply_text = response.choices[0].message.content or ""
    return _TextResponse(reply_text)


def generate_content_tracked(model: str, contents):
    """
    Call Gemini and track token usage/cost into the current context's totals
    (see start_usage_tracking/get_usage_totals). On a transient Gemini failure
    (quota/availability/timeout — see _is_transient), fails over to DeepSeek
    once; a non-transient error (e.g. bad request, auth) raises immediately
    without failover, since rerouting won't fix a config bug.

    If DeepSeek also fails, the ORIGINAL Gemini exception is re-raised — same
    failure shape as before this feature existed, so the existing @retry
    decorators on classify_intent/generate_reply keep working unchanged.
    """
    try:
        response = get_client().models.generate_content(model=model, contents=contents)
    except Exception as gemini_exc:
        if not _is_transient(gemini_exc):
            raise
        log.warning("Gemini transient error (%s) — failing over to DeepSeek", gemini_exc)
        try:
            return _call_deepseek(contents)
        except Exception as deepseek_exc:
            log.error("DeepSeek failover also failed: %s", deepseek_exc)
            raise gemini_exc from None

    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        total_tokens = getattr(usage, "total_token_count", 0) or (prompt_tokens + output_tokens)
        cost = _estimate_gemini_cost_usd(prompt_tokens, output_tokens)
        _track_usage("gemini", prompt_tokens, output_tokens, total_tokens, cost)

    return response
