import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

gemini_key = os.getenv("GEMINI_API_KEY")

if not gemini_key:
    raise ValueError("Missing GEMINI_API_KEY in .env")

client = genai.Client(api_key=gemini_key)

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="Say hello in one short sentence.",
)

print("Gemini:", response.text)