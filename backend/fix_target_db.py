import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import text
from app.core.db import get_engine, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.settings_service import get_user_settings_service, update_user_settings_service

async def fix():
    init_db()
    engine = get_engine()
    if not engine:
        print("No DB engine")
        return

    async with AsyncSession(engine) as session:
        # Update admin
        print("Checking admin...")
        data = await get_user_settings_service("admin", session)
        if data and data.get("settings"):
            s = data["settings"]
            current = s.get("targets", {}).get("mid")
            print(f"Current Admin Target: {current}")
            if current != 110:
                print("Updating to 110...")
                if "targets" not in s: s["targets"] = {}
                s["targets"]["mid"] = 110
                await update_user_settings_service("admin", s, data["version"], session)
                print("Updated.")
        else:
            print("Admin settings not found in DB.")

        # Update any other user just in case (Single Tenant Logic)
        stmt = text("SELECT user_id, settings, version FROM user_settings")
        rows = (await session.execute(stmt)).fetchall()
        for r in rows:
            if r.user_id == "admin": continue
            print(f"Checking user {r.user_id}...")
            s = r.settings
            current = s.get("targets", {}).get("mid")
            print(f"  Current: {current}")
            if current != 110:
                print(f"  Updating {r.user_id} to 110...")
                if "targets" not in s: s["targets"] = {}
                s["targets"]["mid"] = 110
                await update_user_settings_service(r.user_id, s, r.version, session)
                print("  Updated.")

if __name__ == "__main__":
    asyncio.run(fix())
