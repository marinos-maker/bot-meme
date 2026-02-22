
import asyncio
from early_detector.db import get_pool, close_pool

async def check_stats():
    pool = await get_pool()
    try:
        row = await pool.fetchrow("SELECT COUNT(*), MAX(last_active) FROM wallet_performance")
        with open("stats_output.txt", "w") as f:
            f.write(f"COUNT: {row[0]}\n")
            f.write(f"MAX_ACTIVE: {row[1]}\n")
            now = await pool.fetchval("SELECT NOW()")
            f.write(f"NOW: {now}\n")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(check_stats())
