import json

from dotenv import load_dotenv
from langdetect import detect, LangDetectException
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

from .api_client import get_client

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


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc)
    return (
        "503" in msg or "UNAVAILABLE" in msg
        or "429" in msg or "quota" in msg.lower()
        or "ReadTimeout" in type(exc).__name__
        or "Timeout" in type(exc).__name__
    )


@retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def classify_intent(email_body: str) -> dict:
    """
    Returns {intent, language, escalate, confidence, reason}.
    escalate is True for REWORK, BILLING, complaints, legal threats,
    manager requests, or anything outside the knowledge base.
    """
    language = detect_language(email_body)

    prompt = f"""Classify this dental clinic email into exactly one category.
Categories: {', '.join(INTENT_CATEGORIES)}

ESCALATE = true for: REWORK, BILLING (disputes), OTHER,
or any email containing complaint / legal threat /
patient adverse event / manager request / custom pricing negotiation.

Return JSON only, no other text:
{{"intent": "CATEGORY", "escalate": true/false, "confidence": 0.0-1.0, "reason": "one sentence"}}

Email:
{email_body[:800]}"""

    response = get_client().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
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
