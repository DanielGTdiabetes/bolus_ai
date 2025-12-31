import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv("backend/.env")
sys.path.append(os.getcwd())

from app.core.db import get_engine, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.services.settings_service import get_user_settings_service, update_user_settings_service

async def update_targets():
    init_db()
    engine = get_engine()
    if not engine:
        print("No engine.")
        return

    async with AsyncSession(engine) as session:
        username = "admin"
        print(f"Fetching settings for {username}...")
        data = await get_user_settings_service(username, session)
        
        if not data:
            print("No data found for admin.")
            return

        current_settings = data["settings"]
        current_version = data["version"]
        
        print(f"Current Targets: {current_settings.get('targets')}")
        
        # Ensure targets dict exists
        if "targets" not in current_settings:
            current_settings["targets"] = {}
            
        # Update mid to 110
        current_settings["targets"]["mid"] = 110
        # Ensure others exist just in case to avoid empty low/high if they were missing
        if "low" not in current_settings["targets"]: current_settings["targets"]["low"] = 100
        if "high" not in current_settings["targets"]: current_settings["targets"]["high"] = 180
            
        print(f"New Targets: {current_settings['targets']}")
        
        await update_user_settings_service(username, current_settings, current_version, session)
        print("Database updated successfully.")

if __name__ == "__main__":
    asyncio.run(update_targets())
