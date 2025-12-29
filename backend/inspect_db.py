import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.getcwd())

from sqlalchemy import text
from app.core.db import get_engine, init_db

async def inspect():
    print("--- Inspecting DB ---")
    
    # Force init if needed (though usually done by main)
    init_db()
    engine = get_engine()
    
    if not engine:
        print("!! No DB Engine (In-Memory or Config Missing) !!")
        return

    from app.core.db import get_db_session
    
    # We can't use get_db_session normally since it relies on factory which init_db sets up
    # But init_db sets the global _async_engine.
    
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as session:
        print("Connected. Querying user_settings...")
        try:
            stmt = text("SELECT user_id, settings, updated_at FROM user_settings")
            result = await session.execute(stmt)
            rows = result.fetchall()
            
            print(f"Found {len(rows)} rows.")
            for r in rows:
                print(f"\nUser: {r.user_id}")
                print(f"Updated: {r.updated_at}")
                s = r.settings
                if not s:
                    print("Settings: None/Empty")
                    continue
                    
                ns = s.get("nightscout", {})
                print(f"Nightscout Key Found: {bool(ns)}")
                print(f"URL: '{ns.get('url')}'")
                print(f"Enabled: {ns.get('enabled')}")
                
                # Check for legacy keys just in case
                if "base_url" in s: print(f"Legacy base_url: {s['base_url']}")
                
        except Exception as e:
            print(f"Query failed: {e}")
            # Check if table exists
            try:
                await session.execute(text("SELECT 1 FROM user_settings LIMIT 1"))
            except Exception as e2:
                 print(f"Table user_settings might not exist: {e2}")

if __name__ == "__main__":
    asyncio.run(inspect())
