import asyncio
import os
import sys
import json
from dotenv import load_dotenv

load_dotenv("backend/.env")
sys.path.append(os.getcwd())

from app.core.db import get_engine, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def update_targets_raw():
    init_db()
    engine = get_engine()
    if not engine:
        print("No engine.")
        return

    async with AsyncSession(engine) as session:
        username = "admin"
        print(f"Fetching settings (RAW) for {username}...")
        
        # Raw Select
        stmt = text("SELECT settings, version FROM user_settings WHERE user_id = :uid")
        result = await session.execute(stmt, {"uid": username})
        row = result.fetchone()
        
        if not row:
            print("No data found for admin.")
            return

        current_settings = row.settings
        current_version = row.version
        
        print(f"Current Targets: {current_settings.get('targets')}")
        
        # Modify
        if "targets" not in current_settings:
            current_settings["targets"] = {}
        
        current_settings["targets"]["mid"] = 110
        if "low" not in current_settings["targets"]: current_settings["targets"]["low"] = 100
        if "high" not in current_settings["targets"]: current_settings["targets"]["high"] = 180
            
        print(f"New Targets: {current_settings['targets']}")
        
        # Update Raw
        # We need to increment version too ideally
        update_stmt = text("UPDATE user_settings SET settings = :s, version = :v WHERE user_id = :uid")
        
        # We need to pass the dict as a parameter, SQLAlchemy handles JSONB serialization usually
        # but let's be careful. The engine is asyncpg.
        
        await session.execute(update_stmt, {
            "s": json.dumps(current_settings), # Usually raw SQL with asyncpg wants json string or dict depending on driver mapping?
                                               # SQLAlchemy with JSON type usually handles dict. 
                                               # IF the column is JSON/JSONB.
                                               # If I pass a dict, SQLAlchemy should adapt.
                                               # Let's try passing dict first. 
                                               # But wait, using `text` bypasses types sometimes.
                                               # Let's rely on standard binding.
            "v": current_version + 1,
            "uid": username
        })
        
        await session.commit()
        print("Database updated successfully (RAW).")

if __name__ == "__main__":
    asyncio.run(update_targets_raw())
