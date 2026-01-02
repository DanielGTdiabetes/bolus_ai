
import asyncio
import google.generativeai as genai
from app.core import config
import os

async def main():
    print("--- Verifying Gemini Config ---")
    api_key = config.get_google_api_key()
    if not api_key:
        print("ERROR: No API Key found.")
        return

    print(f"API Key found (length {len(api_key)})")
    genai.configure(api_key=api_key)

    print("\n--- Listing Available Models ---")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f" - {m.name} ({m.display_name})")
    except Exception as e:
        print(f"Error listing models: {e}")

    configured_model = config.get_gemini_model()
    print(f"\n--- Testing Configured Model: {configured_model} ---")
    
    try:
        model = genai.GenerativeModel(configured_model)
        # Simple test
        response = await model.generate_content_async("Hello, are you working?")
        print(f"Success! Response: {response.text}")
    except Exception as e:
        print(f"FAILURE with {configured_model}: {e}")

        # Fallback test
        fallback = "gemini-2.0-flash-exp"
        print(f"\n--- Testing Fallback: {fallback} ---")
        try:
            model = genai.GenerativeModel(fallback)
            response = await model.generate_content_async("Hello?")
            print(f"Success with fallback! Response: {response.text}")
        except Exception as ex:
            print(f"FAILURE with fallback: {ex}")

if __name__ == "__main__":
    asyncio.run(main())
