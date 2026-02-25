import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check():
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    try:
        tables = ['tokens', 'token_metrics_timeseries', 'signals', 'trades']
        for table in tables:
            print(f"\nTable: {table}")
            columns = await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1",
                table
            )
            for col in columns:
                print(f"  {col['column_name']} ({col['data_type']})")
    finally:
        await conn.close()

asyncio.run(check())
