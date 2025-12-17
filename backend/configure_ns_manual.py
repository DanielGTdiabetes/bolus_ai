
import asyncio
import os
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session_factory
from app.services.nightscout_secrets_service import upsert_ns_config

# Ensure APP_SECRET_KEY is set for this script if not already
if not os.environ.get("APP_SECRET_KEY"):
    from cryptography.fernet import Fernet
    # Use a fixed key for this script run if needed, OR generate one but then it won't be decryptable by server if server key differs.
    # Assuming server shares same env or we are setting it up fresh.
    # The user should ensure the server has this key if persistence matters.
    # For now, we assume the environment has it or we are setting it up locally to test "Status: Enabled".
    print("WARNING: APP_SECRET_KEY not set. Generating temporary one.")
    os.environ["APP_SECRET_KEY"] = Fernet.generate_key().decode()

from app.core.db import init_db, create_tables

async def configure_admin():
    # Ensure DB is initialized
    init_db()
    await create_tables()

    # Need to access factory from module global
    from app.core import db
    session_factory = db._async_session_factory

    async with session_factory() as session:
        user_id = "admin" # The default user
        url = "https://site--cronica--6cblbs2czn95.code.run"
        api_secret = "app-7f120a3c663f5c7c"
        
        print(f"Upserting configuration for user '{user_id}'...")
        await upsert_ns_config(session, user_id, url, api_secret, enabled=True)
        print("✅ Configuration Saved to Database (Encrypted).")

if __name__ == "__main__":
    asyncio.run(configure_admin())
