import asyncio
import os
import sys

sys.path.append(os.getcwd())

from app.core.db import get_engine, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def check():
    init_db()
    engine = get_engine()
    if not engine:
        print("No DB engine")
        return

    async with AsyncSession(engine) as session:
        stmt = text("SELECT user_id, settings FROM user_settings")
        result = await session.execute(stmt)
        rows = result.fetchall()
        for r in rows:
            print(f"User: {r.user_id}")
            targets = r.settings.get("targets", {})
            print(f"Targets: {targets}")
            
if __name__ == "__main__":
    asyncio.run(check())
