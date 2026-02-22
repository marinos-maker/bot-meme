
import asyncio
from early_detector.db import get_pool, close_pool
from loguru import logger

async def check_stats():
    pool = await get_pool()
    try:
        row = await pool.fetchrow("SELECT COUNT(*), MAX(last_active) FROM wallet_performance")
        print(f"COUNT: {row[0]}")
        print(f"MAX_ACTIVE: {row[1]}")
        
        # Check current time
        now = await pool.fetchval("SELECT NOW()")
        print(f"🕒 DB Now: {now}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(check_stats())
