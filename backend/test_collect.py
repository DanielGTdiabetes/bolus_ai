
import asyncio
import os
from app.core.db import init_db
from app.bot.service import _collect_ml_data

__test__ = False

async def test():
    os.environ["JWT_SECRET"] = "dummy"
    init_db()
    print("Starting manual collection...")
    await _collect_ml_data()
    print("Done. Check ml_debug.log")

if __name__ == "__main__":
    asyncio.run(test())
