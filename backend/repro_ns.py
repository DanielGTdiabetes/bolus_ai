import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path so we can import app
sys.path.append(str(Path(__file__).parent))

from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.models.settings import UserSettings

# Configure logging to stdout
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("repro_ns")

async def main():
    # Data dir is relative to where we expect the app to run.
    # We are in backend/, so let's point to ./data
    data_dir = Path("data")
    if not data_dir.exists():
        logger.error(f"Data dir not found at {data_dir.absolute()}")
        return

    store = DataStore(data_dir)
    settings = store.load_settings()
    ns = settings.nightscout

    if not ns.enabled or not ns.url:
        logger.error("Nightscout not enabled or URL missing in settings.json")
        return

    logger.info(f"Connecting to Nightscout: {ns.url}")
    
    client = NightscoutClient(base_url=ns.url, token=ns.token, timeout_seconds=30)
    try:
        # Try fetching treatments
        treatments = await client.get_recent_treatments(hours=48, limit=10)
        print(f"\n--- Fetched {len(treatments)} treatments ---")
        for t in treatments:
            print(t.model_dump_json())
    except Exception as e:
        logger.exception("Failed to fetch treatments")
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
