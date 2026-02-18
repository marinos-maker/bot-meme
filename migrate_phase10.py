
import asyncio
from early_detector.db import get_pool

async def migrate():
    pool = await get_pool()
    print("Migrating 'signals' table...")
    await pool.execute("""
        ALTER TABLE signals 
        ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 0.5,
        ADD COLUMN IF NOT EXISTS kelly_size FLOAT DEFAULT 0.0;
    """)
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
