import asyncio
from app.core.db import get_engine, AsyncSession
from sqlalchemy import text
from app.models.settings import UserSettings

async def inspect_db():
    print("Connecting to DB...")
    engine = get_engine()
    if not engine:
        print("No DB Engine!")
        return

    async with AsyncSession(engine) as session:
        print("Querying user_settings...")
        stmt = text("SELECT user_id, settings, version FROM user_settings")
        rows = (await session.execute(stmt)).fetchall()
        
        print(f"Found {len(rows)} users.")
        for row in rows:
            uid = row.user_id
            settings_json = row.settings
            ver = row.version
            print(f"--- User: {uid} (v{ver}) ---")
            
            # Check Nightscout URL
            ns = settings_json.get("nightscout", {})
            print(f"Nightscout URL: '{ns.get('url')}'")
            
            # Check CR/ISF
            cr = settings_json.get("cr", {})
            cf = settings_json.get("cf", {})
            print(f"CR: {cr}")
            print(f"CF: {cf}")
            
            # Check Rounding
            step = settings_json.get("round_step_u")
            print(f"Rounding Step: {step}")

            # Validate Model Migration
            try:
                migrated = UserSettings.migrate(settings_json)
                print(f"Migration Status: OK (Computed Step: {migrated.round_step_u})")
            except Exception as e:
                print(f"Migration Failed: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_db())
