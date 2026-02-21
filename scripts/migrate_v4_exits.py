import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

async def migrate():
    print(f"Connecting to {SUPABASE_DB_URL}...")
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    try:
        print("Adding exit level columns to signals table...")
        await conn.execute("""
            ALTER TABLE signals 
            ADD COLUMN IF NOT EXISTS hard_stop FLOAT,
            ADD COLUMN IF NOT EXISTS tp_1 FLOAT;
        """)
        print("Migration complete!")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
