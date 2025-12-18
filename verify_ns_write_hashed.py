import asyncio
import logging
import sys
import os
import hashlib
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("write_test_hashed")

async def test_write():
    url = "https://TU_SITIO_NIGHTSCOUT.com" # removed trailing slash
    token = "TU_TOKEN_NIGHTSCOUT"
    
    logger.info(f"Testing WRITE permission to: {url}")
    
    # Payload
    from datetime import datetime
    payload = [{
        "eventType": "Note",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "notes": "Test Write HASHED from BolusAI Agent",
        "enteredBy": "BolusAI_Agent"
    }]
    
    # 1. Try as Hashed API-SECRET
    hashed = hashlib.sha1(token.encode("utf-8")).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "API-SECRET": hashed
    }
    
    logger.info(f"Attempt 1: Sending hashed API-SECRET header: {hashed}")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{url}/api/v1/treatments", json=payload, headers=headers)
        logger.info(f"Response: {resp.status_code} {resp.text}")
        
        if resp.status_code == 200 or resp.status_code == 201:
            logger.info("SUCCESS with Hash!")
            return

    # 2. Try as Plain Header (sometimes needed?)
    logger.info("Attempt 2: Sending plain API-SECRET header (rare but possible)")
    headers = {
        "Content-Type": "application/json",
        "API-SECRET": token
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{url}/api/v1/treatments", json=payload, headers=headers)
        logger.info(f"Response: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    asyncio.run(test_write())
