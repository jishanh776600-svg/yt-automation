import os
import json
import urllib.request
from urllib.error import HTTPError
from core.gemini_client import GeminiClient

groq_key = os.getenv("GROQ_API_KEY", "")
openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

groq_detected = "YES" if bool(groq_key) else "NO"
openrouter_detected = "YES" if bool(openrouter_key) else "NO"

print(f"CHECK: GROQ_API_KEY detected: {groq_detected}")
print(f"CHECK: OPENROUTER_API_KEY detected: {openrouter_detected}")

headers = {
    "Authorization": f"Bearer {groq_key}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 1. First discover available models
req = urllib.request.Request("https://api.groq.com/openai/v1/models", headers=headers)
available_models = []
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        available_models = [m["id"] for m in data.get("data", [])]
        print("LIVE_GROQ_MODELS:", sorted(available_models))
except HTTPError as e:
    err_body = e.read().decode("utf-8", errors="ignore")
    print(f"MODELS_ENDPOINT_ERROR: {e.code} - {err_body}")

# 2. Select model and test request
selected_model = None
for candidate in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b", "deepseek-r1-distill-llama-70b"]:
    if candidate in available_models:
        selected_model = candidate
        break

if not selected_model and available_models:
    # Pick first chat model
    chat_models = [m for m in available_models if "whisper" not in m and "guard" not in m and "embedding" not in m]
    selected_model = chat_models[0] if chat_models else available_models[0]

if not selected_model:
    selected_model = "llama-3.3-70b-versatile"

print(f"TESTING_WITH_MODEL: {selected_model}")

client = GeminiClient(api_key="", secondary_api_key="", groq_api_key=groq_key, groq_model=selected_model)
try:
    res = client._execute_groq_request(api_key=groq_key, model=selected_model, contents="Reply with exactly: GROQ_OK")
    print("GROQ_CALL: PASS")
    if hasattr(res, "text") and res.text:
        print("GROQ_PARSING: PASS")
        print("GROQ_RESPONSE:", res.text.strip())
    else:
        print("GROQ_PARSING: FAIL (empty response)")
except Exception as e:
    print(f"GROQ_CALL: FAIL ({e})")
    print("GROQ_PARSING: FAIL")

print("OPENROUTER_CALL: NOT_IMPLEMENTED")
print("OPENROUTER_PARSING: NOT_IMPLEMENTED")
