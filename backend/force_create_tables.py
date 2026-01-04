import asyncio
import sys
import os

# Put backend in path
sys.path.append(os.getcwd())

from app.core.db import init_db, get_engine, Base
# Import ALL models to ensure metadata is populated
from app.models.user_data import SupplyItem, FavoriteFood
from app.models import treatment # etc

async def create():
    print("Initializing DB...")
    init_db()
    engine = get_engine()
    
    print("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(create())
    except Exception as e:
        print(f"Error: {e}")
