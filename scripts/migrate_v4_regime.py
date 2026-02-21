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
        print("Creating market_regime table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_regime (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_volume_5m FLOAT,
                regime_label TEXT
            );
        """)
        print("Migration complete!")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
