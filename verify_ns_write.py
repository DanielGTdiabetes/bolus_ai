import asyncio
import logging
import sys
import os

# Ensure backend directory is in python path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.services.nightscout_client import NightscoutClient, NightscoutError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("write_test")

async def test_write():
    url = "https://TU_SITIO_NIGHTSCOUT.com/"
    token = "TU_TOKEN_NIGHTSCOUT"
    
    logger.info(f"Testing WRITE permission to: {url}")
    
    client = NightscoutClient(base_url=url, token=token)
    
    # Create a test treatment (Note)
    from datetime import datetime
    
    payload = {
        "eventType": "Note",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "notes": "Test Write from BolusAI Agent - Please ignore",
        "enteredBy": "BolusAI_Agent"
    }
    
    try:
        logger.info("Attempting to upload note...")
        result = await client.upload_treatments([payload])
        logger.info(f"SUCCESS! Write response: {result}")
    except NightscoutError as e:
        logger.error(f"FAILURE: Write failed. NightscoutError: {e}")
    except Exception as e:
        logger.error(f"FAILURE: Write failed. Exception: {e}")
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(test_write())
