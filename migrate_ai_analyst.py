
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
dsn = os.getenv("SUPABASE_DB_URL")

async def migrate():
    print("Connecting to DB...")
    conn = await asyncpg.connect(dsn)
    try:
        print("Adding columns to signals table...")
        await conn.execute("""
            ALTER TABLE signals ADD COLUMN IF NOT EXISTS degen_score INTEGER;
            ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_summary TEXT;
            ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_analysis JSONB;
        """)
        print("Migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
