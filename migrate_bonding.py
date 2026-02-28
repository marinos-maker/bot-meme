import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def migrate():
    load_dotenv()
    url = os.getenv("SUPABASE_DB_URL")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("ALTER TABLE token_metrics_timeseries ADD COLUMN IF NOT EXISTS bonding_is_complete BOOLEAN DEFAULT FALSE")
        print("Column bonding_is_complete added successfully.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
