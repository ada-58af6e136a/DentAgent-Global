import json

from dotenv import load_dotenv
from langdetect import detect, LangDetectException
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

from .api_client import generate_content_tracked, _is_transient

load_dotenv()

INTENT_CATEGORIES = [
    "PRICING", "MATERIAL", "PROGRESS",
    "TECHNICAL", "REWORK", "BILLING", "OTHER"
]


def detect_language(text: str) -> str:
    """Returns ISO language code. Falls back to 'en' on failure."""
    if not text or not text.strip():
        return "en"
    # CJK Unicode block: fast path avoids langdetect unreliability on short CJK text
    cjk_chars = sum(1 for c in text if "一" <= c <= "鿿")
    if cjk_chars / max(len(text), 1) > 0.1:
        return "zh"
    try:
        return detect(text)
    except LangDetectException:
        return "en"


@retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def classify_intent(email_body: str) -> dict:
    """
    Returns {intent, language, escalate, confidence, reason,
    rewritten_query, hypothesis}.
    escalate is True for REWORK, BILLING, complaints, legal threats,
    manager requests, or anything outside the knowledge base.

    rewritten_query/hypothesis piggyback on this same call so that
    rag_chain.retrieve_for_email() doesn't need its own query-rewrite and
    HyDE LLM calls for the common case — one call in, three things out,
    instead of three separate calls each re-reading the same email. Callers
    that don't have a classify_intent() result (e.g. standalone retrieval
    validation scripts) still get those via rag_chain's own fallback.
    """
    language = detect_language(email_body)

    prompt = f"""Analyze this dental clinic email and return one JSON object
covering three tasks:

1. Classify into exactly one category: {', '.join(INTENT_CATEGORIES)}.
   ESCALATE = true for: REWORK, BILLING (disputes), OTHER,
   or any email containing complaint / legal threat /
   patient adverse event / manager request / custom pricing negotiation.
2. Extract the single core question or request as one concise sentence,
   stripped of greeting/signature noise (used for keyword search).
3. Write a 2-3 sentence hypothetical knowledge-base-style answer using
   formal product terminology (product names, materials, prices, lead
   times) — it does not need to be factually correct, it only needs to
   sit close to real KB chunks in embedding space for semantic search. If
   the inquiry asks broadly about a category (e.g. "what dentures do you
   offer") rather than one specific product, briefly name each relevant
   product type in that category rather than answering as if only one was
   asked about.

Return JSON only, no other text, matching this shape exactly:
{{"intent": "CATEGORY", "escalate": true/false, "confidence": 0.0-1.0, "reason": "one sentence", "rewritten_query": "...", "hypothesis": "..."}}

Email:
{email_body[:1000]}"""

    response = generate_content_tracked(
        model="gemini-2.5-flash",
        contents=prompt,
        json_mode=True,
        max_output_tokens=500,  # safety cap: JSON reason + rewritten_query + hypothesis
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    result = json.loads(raw)
    result["language"] = language
    return result


if __name__ == "__main__":
    test_emails = [
        "What is the price for a full ceramic crown?",
        "The crown does not fit — we need it redone.",
        "Quelle est la durée de production pour une couronne?",
        "全瓷冠的价格是多少？",
    ]

    for email in test_emails:
        print(f"\nEmail: {email[:60]}")
        print(classify_intent(email))
