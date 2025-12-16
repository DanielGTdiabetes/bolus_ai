
import asyncio
import logging
from app.services.nightscout_client import NightscoutClient, NightscoutError

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATUS_URL = "https://site--cronica--6cblbs2czn95.code.run"
TOKEN = "app-7f120a3c663f5c7"

async def verify_nightscout_client():
    print("Initializing NightscoutClient with Access Token...")
    client = NightscoutClient(base_url=STATUS_URL, token=TOKEN)
    
    # DEBUG: Remove Accept header
    print("Removing Accept header...")
    if "Accept" in client.client.headers:
        del client.client.headers["Accept"]
    
    try:
        # Check internal state
        print(f"Client Params: {client.client.params}")
        
        print("\n--- Testing get_recent_treatments ---")
        try:
            treatments = await client.get_recent_treatments(hours=24, limit=10)
            print(f"Successfully fetched {len(treatments)} treatments.")
            if treatments:
                print(f"First treatment: {treatments[0]}")
        except NightscoutError as e:
            print(f"Treatment fetch failed: {e}")

    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(verify_nightscout_client())
