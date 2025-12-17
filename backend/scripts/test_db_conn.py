import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from sqlalchemy.engine import make_url

url = "postgresql+asyncpg://neondb_owner:npg_exC4YhAql3pu@ep-polished-rain-agw1bcl2-pooler.c-2.eu-central-1.aws.neon.tech/neondb?sslmode=require"

async def test_conn():
    print(f"Parsing {url}...")
    try:
        u = make_url(url)
        connect_args = {}
        if "sslmode" in u.query:
            q = dict(u.query)
            mode = q.pop("sslmode")
            if mode == "require":
                connect_args["ssl"] = "require"
            u = u._replace(query=q)
            
        print(f"Connecting to {u} with args {connect_args}...")
        engine = create_async_engine(u, connect_args=connect_args, echo=True)
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT 1"))
            print(f"Result: {res.scalar()}")
        print("Connection successful")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_conn())
