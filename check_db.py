
import asyncio
from app.core.db import get_engine, AsyncSession
from sqlalchemy import text
import json

async def check():
    engine = get_engine()
    if not engine:
        print("No engine")
        return
    async with AsyncSession(engine) as session:
        res = await session.execute(text("SELECT user_id, settings FROM user_settings"))
        rows = res.fetchall()
        for row in rows:
            print(f"USER: {row[0]}")
            print(json.dumps(row[1], indent=2))

if __name__ == "__main__":
    asyncio.run(check())
