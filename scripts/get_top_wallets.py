
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def get_wallets():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    rows = await conn.fetch('SELECT wallet FROM wallet_performance WHERE total_trades >= 3 ORDER BY avg_roi DESC LIMIT 5')
    for r in rows:
        print(r['wallet'])
    await conn.close()

if __name__ == "__main__":
    asyncio.run(get_wallets())
