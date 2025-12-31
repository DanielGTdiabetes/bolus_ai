import asyncio
import os
import sys
from dotenv import load_dotenv

# Load env from backend/.env
# Assuming CWD is project root
load_dotenv("backend/.env")

sys.path.append(os.getcwd())

from app.core.db import get_engine, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.services.settings_service import get_user_settings_service

async def verify():
    # Force init to pick up env vars
    init_db()
    engine = get_engine()
    
    if not engine:
        print("Still no Engine after load_dotenv!")
        # Try finding the file manually
        print(f"Env file exists? {os.path.exists('backend/.env')}")
        return

    print(f"Engine detected: {engine.url}")

    async with AsyncSession(engine) as session:
        print("--- All Users in DB ---")
        stmt = text("SELECT user_id, settings, updated_at FROM user_settings")
        rows = (await session.execute(stmt)).fetchall()
        
        for r in rows:
            uid = r.user_id
            s = r.settings
            targets = s.get("targets", {})
            print(f"User: {uid}")
            print(f"  UpdatedAt: {r.updated_at}")
            print(f"  Targets: {targets}")
            print(f"  Mid OK? {targets.get('mid') == 110}")
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(verify())
