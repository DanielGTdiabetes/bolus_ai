
import asyncio
import hashlib
import logging
import httpx
import uuid
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATUS_URL = "https://site--cronica--6cblbs2czn95.code.run"
# The token provided by the user
TOKEN = "app-7f120a3c663f5c7"

async def test_nightscout_query_param():
    print(f"Testing URL: {STATUS_URL}")
    print(f"Token: {TOKEN}")

    headers = {}
    
    # Try just query param first, no headers
    
    print(f"Headers: {headers}")
    print("Using query param 'token'")

    async with httpx.AsyncClient(base_url=STATUS_URL, headers=headers, timeout=10.0) as client:
        try:
            params = {
                "count": 10,
                "sort[created_at]": -1,
                "token": TOKEN
            }
            response = await client.get("/api/v1/treatments.json", params=params)
            print(f"Status Code: {response.status_code}")
            if response.status_code == 200:
                print("Success! Body length:", len(response.content))
                try:
                    data = response.json()
                    print(f"Generic items: {len(data)}")
                except:
                    print("Could not parse JSON")
            else:
                print("Failed.")
                print("Body:", response.text[:200])
                
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_nightscout_query_param())
