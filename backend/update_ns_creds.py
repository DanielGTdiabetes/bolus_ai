import asyncio
import sys
import logging
from app.core.db import init_db
import app.core.db
from app.models.nightscout_secrets import NightscoutSecrets
from app.services.nightscout_client import NightscoutClient
from sqlalchemy import select

# Configure simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("config_updater")

async def update_and_test():
    url = "https://TU_SITIO_NIGHTSCOUT.com/"
    token = "TU_TOKEN_NIGHTSCOUT"
    user_id = "admin"

    logger.info("Initializing DB...")
    init_db()
    
    session_factory = app.core.db._async_session_factory
    if not session_factory:
        logger.error("No database configured (session factory is None). Check .env")
        return

    logger.info(f"Updating configuration for user: {user_id}")
    async with session_factory() as session:
        # Check existing
        stmt = select(NightscoutSecrets).where(NightscoutSecrets.user_id == user_id)
        result = await session.execute(stmt)
        secrets = result.scalars().first()
        
        if not secrets:
            secrets = NightscoutSecrets(user_id=user_id)
            session.add(secrets)
            
        secrets.url = url
        secrets.api_secret = token # We store token in api_secret field
        secrets.enabled = True
        
        await session.commit()
        logger.info("Configuration updated in Database.")
        
    # Verify
    logger.info("Testing connection to Nightscout...")
    client = NightscoutClient(base_url=url, token=token)
    try:
        status = await client.get_status()
        logger.info(f"SUCCESS: Connected to Nightscout! Version: {status.version}")
        
        # Test Authorization (read profile or something requiring auth?)
        # get_status usually public. 
        # get_recent_treatments usually requires token.
        treatments = await client.get_recent_treatments(limit=1)
        logger.info(f"SUCCESS: Authorized! Fetched {len(treatments)} treatments.")
        
    except Exception as e:
        logger.error(f"FAILURE: Could not connect/authorize: {e}")
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(update_and_test())
