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
from openai import (
    APIConnectionError, APITimeoutError, InternalServerError, RateLimitError,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger(__name__)

_lock = threading.Lock()
_client: genai.Client | None = None


def get_client() -> genai.Client:
    """
    Return the shared genai.Client, creating it on first call (thread-safe).

    Gemini is the fallback provider for text generation (see
    generate_content_tracked()) — that's its only remaining role. Retrieval
    embeddings moved to a local model (agent/embeddings.py), so unlike
    before, GEMINI_API_KEY being unset only degrades failover behavior on a
    DeepSeek outage, it no longer breaks retrieval.
    """
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


# ── DeepSeek: primary text-generation provider ────────────────────────────────
# Gemini covers for it on a transient failure — see generate_content_tracked().
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
    or request-shape bug that a retry/failover won't fix (e.g. a missing
    DEEPSEEK_API_KEY raises an auth error here — stays non-transient, fails
    loud instead of silently rerouting to Gemini and masking the config bug).

    Checks typed OpenAI-SDK exceptions first (DeepSeek is OpenAI-compatible)
    — more precise than string matching for connection-level failures that
    don't necessarily mention "429"/"timeout" in their message. Falls back to
    Gemini's string-based error shapes, which don't have typed exceptions
    exposed the same way.

    Single copy shared by classifier.py, rag_chain.py (their @retry decorators)
    and generate_content_tracked() (the DeepSeek→Gemini failover decision below).
    """
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)):
        return True
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
        "cache_hit_tokens": 0, "cache_miss_tokens": 0,
    })


def get_usage_totals() -> dict:
    """Return this context's accumulated usage/cost/fallback counters."""
    totals = _usage_totals.get()
    if totals:
        return dict(totals)
    return {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "cost_usd": 0.0, "fallback_calls": 0,
            "cache_hit_tokens": 0, "cache_miss_tokens": 0}


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
                  cost_usd: float, fallback: bool = False,
                  cache_hit_tokens: int = 0, cache_miss_tokens: int = 0) -> None:
    totals = _usage_totals.get()
    if totals is None:
        return
    totals["prompt_tokens"] += prompt_tokens
    totals["output_tokens"] += output_tokens
    totals["total_tokens"] += total_tokens
    totals["cost_usd"] += cost_usd
    totals["cache_hit_tokens"] += cache_hit_tokens
    totals["cache_miss_tokens"] += cache_miss_tokens
    if fallback:
        totals["fallback_calls"] += 1


def _call_deepseek(contents, fallback: bool = False, json_mode: bool = False,
                    max_output_tokens: int | None = None) -> "_TextResponse":
    """
    Send the prompt to DeepSeek (non-thinking mode) and track its usage.

    fallback marks whether this call is itself covering for a Gemini failure
    — ordinarily False, since DeepSeek is the primary provider. Kept as a
    parameter (not hardcoded) so the primary/fallback roles stay a one-line
    swap in generate_content_tracked() rather than requiring changes here.

    json_mode requests DeepSeek's native JSON-object response format instead
    of relying on prompt instructions alone — classify_intent()'s output is
    parsed with json.loads(), and a malformed response there isn't caught by
    the transient-error @retry (a JSONDecodeError isn't transient), so it
    crashes the whole email and forces a full reprocess next poll cycle.

    max_output_tokens is a safety cap, not a target — callers size it above
    what a normal reply/classification actually needs, purely to bound the
    cost of a pathological/runaway generation.
    """
    text = _extract_text(contents)
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_output_tokens is not None:
        kwargs["max_tokens"] = max_output_tokens
    response = get_deepseek_client().chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": text}],
        extra_body={"thinking": {"type": "disabled"}},
        **kwargs,
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
    _track_usage("deepseek", prompt_tokens, output_tokens, total_tokens, cost, fallback=fallback,
                 cache_hit_tokens=cache_hit_tokens, cache_miss_tokens=cache_miss_tokens)

    reply_text = response.choices[0].message.content or ""
    return _TextResponse(reply_text)


def _call_gemini(model: str, contents, fallback: bool = False, json_mode: bool = False,
                  max_output_tokens: int | None = None):
    """
    Call Gemini and track its usage. fallback marks whether this call is
    covering for a DeepSeek failure — ordinarily True, since Gemini is now
    the fallback provider for text generation (see module-level notes on
    get_client() for why Gemini can't be removed entirely: embeddings).

    json_mode mirrors the DeepSeek json_object request via Gemini's
    response_mime_type config, so a failover mid-call doesn't silently drop
    back to unstructured text parsing. max_output_tokens mirrors DeepSeek's
    safety cap the same way.
    """
    config_kwargs = {}
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
    response = get_client().models.generate_content(
        model=model, contents=contents,
        **({"config": config} if config else {}),
    )

    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        total_tokens = getattr(usage, "total_token_count", 0) or (prompt_tokens + output_tokens)
        cost = _estimate_gemini_cost_usd(prompt_tokens, output_tokens)
        # No explicit context caching configured for the Gemini fallback path
        # (see rag_chain/classifier prompt construction) — every prompt token
        # is a cache miss here, unlike DeepSeek's automatic KV cache.
        _track_usage("gemini", prompt_tokens, output_tokens, total_tokens, cost, fallback=fallback,
                     cache_hit_tokens=0, cache_miss_tokens=prompt_tokens)

    return response


def generate_content_tracked(model: str, contents, json_mode: bool = False,
                              max_output_tokens: int | None = None):
    """
    DeepSeek-primary, Gemini-fallback for text generation. `model` names the
    Gemini model to use only if/when falling back to it (e.g. "gemini-2.5-flash").

    On a transient DeepSeek failure (quota/availability/timeout/connection —
    see _is_transient), fails over to Gemini once; a non-transient error
    (e.g. bad request, missing DEEPSEEK_API_KEY) raises immediately without
    failover, since rerouting won't fix a config bug.

    If Gemini also fails, the ORIGINAL DeepSeek exception is re-raised — same
    failure shape regardless of whether failover exists at all, so the
    existing @retry decorators on classify_intent/generate_reply keep
    working unchanged.

    json_mode requests a native JSON-object response from whichever provider
    ends up serving the call (see _call_deepseek / _call_gemini).
    max_output_tokens is a cost/runaway-output safety cap, forwarded as-is.
    """
    try:
        return _call_deepseek(contents, fallback=False, json_mode=json_mode,
                               max_output_tokens=max_output_tokens)
    except Exception as deepseek_exc:
        if not _is_transient(deepseek_exc):
            raise
        log.warning("DeepSeek transient error (%s) — failing over to Gemini", deepseek_exc)
        try:
            return _call_gemini(model, contents, fallback=True, json_mode=json_mode,
                                 max_output_tokens=max_output_tokens)
        except Exception as gemini_exc:
            log.error("Gemini failover also failed: %s", gemini_exc)
            raise deepseek_exc from None
