
import asyncio
import os
from app.core.db import init_db, SessionLocal
from sqlalchemy import text

async def check():
    os.environ["JWT_SECRET"] = "dummy_secret_for_settings_load"
    init_db()
    async with SessionLocal() as session:
        res = await session.execute(text("SELECT user_id FROM user_settings"))
        rows = res.fetchall()
        print("Existing users in user_settings:")
        for row in rows:
            print(f"- {row[0]}")
            
        res = await session.execute(text("SELECT user_id, count(*) FROM ml_training_data GROUP BY user_id"))
        rows = res.fetchall()
        print("\nML training data counts:")
        for row in rows:
            print(f"- User: {row[0]}, Count: {row[1]}")

if __name__ == "__main__":
    asyncio.run(check())
