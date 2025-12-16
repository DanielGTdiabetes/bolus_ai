
import asyncio
import logging
import httpx
import json

# Setup logging
logging.basicConfig(level=logging.INFO)

STATUS_URL = "https://site--cronica--6cblbs2czn95.code.run"
TOKEN = "app-7f120a3c663f5c7"

async def test_default_sort():
    params = {
        "count": 5,
        "token": TOKEN
    }
    
    print(f"Testing with params: {params}")
    
    async with httpx.AsyncClient(base_url=STATUS_URL) as client:
        resp = await client.get("/api/v1/treatments", params=params)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            try:
                data = resp.json()
                print(f"Items: {len(data)}")
                if data:
                    print("Dates:")
                    for item in data:
                        print(f" - {item.get('created_at')}")
            except Exception as e:
                print(f"Error parsing json: {e}")

if __name__ == "__main__":
    asyncio.run(test_default_sort())
