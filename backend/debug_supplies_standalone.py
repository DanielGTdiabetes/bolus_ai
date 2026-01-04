import asyncio
import logging
import sys
import os

# Ensure backend in path
sys.path.append(os.getcwd())

from app.core.db import init_db, create_tables
from app.bot.tools import check_supplies_stock
from app.models import user_data # Ensure models loaded

# Setup logging
logging.basicConfig(level=logging.INFO)

async def run():
    print("Initializing DB...")
    init_db()
    
    # We might need to ensure tables exist if using in-memory or new DB
    try:
        await create_tables()
    except Exception as e:
        print(f"Create tables warning: {e}")

    print("Checking supplies...")
    result = await check_supplies_stock({})
    print("Result:", result)
    
    if hasattr(result, 'message'):
        print("Error Message:", result.message)

if __name__ == "__main__":
    asyncio.run(run())
