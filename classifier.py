import os
import json

from dotenv import load_dotenv
from langdetect import detect, LangDetectException
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

INTENT_CATEGORIES = [
    "PRICING", "MATERIAL", "PROGRESS",
    "TECHNICAL", "REWORK", "BILLING", "OTHER"
]


def detect_language(text: str) -> str:
    """Returns ISO language code: en, fr, de, nl, es, zh, etc."""
    try:
        return detect(text)
    except LangDetectException:
        return "en"


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

    response = client.models.generate_content(
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
