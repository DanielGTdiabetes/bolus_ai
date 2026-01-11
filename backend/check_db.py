
import asyncio
from app.core.db import init_db, SessionLocal
from sqlalchemy import text

async def check():
    init_db()
    async with SessionLocal() as session:
        res = await session.execute(text("SELECT user_id, count(*) FROM ml_training_data GROUP BY user_id"))
        rows = res.fetchall()
        if not rows:
            print("No data in ml_training_data table.")
        for row in rows:
            print(f"User: {row[0]}, Count: {row[1]}")
            
        res2 = await session.execute(text("SELECT count(*) FROM entries"))
        print(f"Entries count: {res2.scalar()}")

if __name__ == "__main__":
    asyncio.run(check())
