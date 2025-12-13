
import os
import google.generativeai as genai

# Mimic config loading
api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

print(f"DEBUG: Checking Gemini Models...")
print(f"DEBUG: API Key present? {'Yes' if api_key else 'No'}")

if not api_key:
    print("ERROR: No API Key found in environment variables GOOGLE_API_KEY or GEMINI_API_KEY")
    exit(1)

genai.configure(api_key=api_key)

try:
    print("Listing available models invoked with list_models():")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f" - {m.name}")
except Exception as e:
    print(f"ERROR listing models: {e}")

print("\nDEBUG: Configured GEMINI_MODEL env var:", os.environ.get("GEMINI_MODEL"))
