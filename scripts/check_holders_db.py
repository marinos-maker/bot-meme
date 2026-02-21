
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def check_holders():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    count = await conn.fetchval('SELECT COUNT(*) FROM token_metrics_timeseries WHERE holders IS NOT NULL AND holders > 0')
    print(f"Total rows with holders > 0: {count}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_holders())
