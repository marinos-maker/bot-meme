import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def migrate():
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    try:
        print("Adding columns to token_metrics_timeseries...")
        await conn.execute("ALTER TABLE token_metrics_timeseries ADD COLUMN IF NOT EXISTS mint_authority TEXT")
        await conn.execute("ALTER TABLE token_metrics_timeseries ADD COLUMN IF NOT EXISTS freeze_authority TEXT")
        
        print("Adding columns to tokens...")
        await conn.execute("ALTER TABLE tokens ADD COLUMN IF NOT EXISTS mint_authority TEXT")
        await conn.execute("ALTER TABLE tokens ADD COLUMN IF NOT EXISTS freeze_authority TEXT")
        
        print("Adding columns to signals...")
        await conn.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS mint_authority TEXT")
        await conn.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS freeze_authority TEXT")
        
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        await conn.close()

asyncio.run(migrate())
