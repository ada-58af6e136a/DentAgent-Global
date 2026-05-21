import os
from dotenv import load_dotenv
from anthropic import Anthropic
from openai import OpenAI

load_dotenv()

anthropic_key = os.getenv("ANTHROPIC_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")

if not anthropic_key:
    raise ValueError("Missing ANTHROPIC_API_KEY in .env")

if not openai_key:
    raise ValueError("Missing OPENAI_API_KEY in .env")

# Test 1: Claude API
anthropic_client = Anthropic(api_key=anthropic_key)

message = anthropic_client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=20,
    messages=[
        {"role": "user", "content": "Say hello in one short sentence."}
    ],
)

print("Claude:", message.content[0].text)

# Test 2: OpenAI Embeddings API
openai_client = OpenAI(api_key=openai_key)

embedding_response = openai_client.embeddings.create(
    input="test",
    model="text-embedding-3-large",
)

print("Embedding dims:", len(embedding_response.data[0].embedding))