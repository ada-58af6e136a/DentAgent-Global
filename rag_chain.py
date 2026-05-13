import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from google import genai

from system_prompt import SYSTEM_PROMPT

PROJECT_ROOT = Path(__file__).resolve().parent
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

load_dotenv(PROJECT_ROOT / ".env")

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=os.getenv("GEMINI_API_KEY"),
)

_db = Chroma(
    persist_directory=str(CHROMA_DIR),
    embedding_function=_embeddings,
)

_retriever = _db.as_retriever(search_kwargs={"k": 4})


def generate_reply(email_body: str, language: str) -> dict:
    """
    Retrieves top-4 knowledge base chunks and generates a reply.

    Returns:
        {"reply": str, "sources": list[str]}
    """
    chunks = _retriever.invoke(email_body)
    context = "\n\n---\n\n".join(c.page_content for c in chunks)
    sources = [Path(c.metadata.get("source", "unknown")).name for c in chunks]

    user_message = f"""Reply language: {language}

Knowledge base context (use this to answer — do not invent information):
{context}

Client email:
{email_body}"""

    response = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_message}]}
        ],
    )

    return {
        "reply": response.text.strip(),
        "sources": sources,
    }


if __name__ == "__main__":
    import time

    test_cases = [
        ("What is the price for a full ceramic crown?", "en"),
        ("Quel est le délai de production pour une couronne?", "fr"),
        ("全瓷冠的价格是多少？", "zh"),
    ]

    for i, (email, lang) in enumerate(test_cases):
        if i > 0:
            time.sleep(15)
        print(f"\n{'='*50}")
        print(f"Email ({lang}): {email}")
        result = generate_reply(email, lang)
        print(f"\nReply:\n{result['reply']}")
        print(f"\nSources: {result['sources']}")
