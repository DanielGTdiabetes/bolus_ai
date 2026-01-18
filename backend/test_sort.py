
import asyncio
import logging
import httpx

# Setup logging
logging.basicConfig(level=logging.INFO)

__test__ = False

STATUS_URL = "https://site--cronica--6cblbs2czn95.code.run"
TOKEN = "app-7f120a3c663f5c7"

async def test_sort_param():
    params = {
        "count": 100,
        "token": TOKEN,
        "sort[created_at]": -1
    }
    
    print(f"Testing with params: {params}")
    
    async with httpx.AsyncClient(base_url=STATUS_URL) as client:
        resp = await client.get("/api/v1/treatments", params=params)
        print(f"Status: {resp.status_code}")
        print(f"Body length: {len(resp.content)}")
        print(f"Body: {resp.text[:100]}")

if __name__ == "__main__":
    asyncio.run(test_sort_param())
