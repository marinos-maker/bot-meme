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
        print("Adding creator_address to tokens table...")
        await conn.execute("ALTER TABLE tokens ADD COLUMN IF NOT EXISTS creator_address TEXT;")
        
        print("Creating creator_performance table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS creator_performance (
                creator_address TEXT PRIMARY KEY,
                rug_ratio FLOAT DEFAULT 0.0,
                avg_lifespan FLOAT DEFAULT 0.0,
                total_tokens INTEGER DEFAULT 1,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("Migration complete!")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
