
import asyncio
from early_detector.db import get_pool

async def count_tracked():
    pool = await get_pool()
    count = await pool.fetchval("""
        SELECT COUNT(DISTINCT token_id)
        FROM token_metrics_timeseries
        WHERE timestamp > NOW() - INTERVAL '4 hours'
    """)
    print(f"Tokens active in last 4h: {count}")

if __name__ == "__main__":
    asyncio.run(count_tracked())
