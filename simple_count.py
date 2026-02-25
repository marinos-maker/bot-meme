import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check():
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    try:
        # Option A: ROI > 1.1, Trades >= 1, WR > 0.25
        # Plus the OR condition for high ROI whales
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM wallet_performance "
            "WHERE (avg_roi > 1.1 AND total_trades >= 1 AND win_rate > 0.25) "
            "OR (avg_roi > 10.0 AND total_trades >= 3)"
        )
        print(f"Option A Smart Wallets: {count}")
        
        # Current DB total
        total = await conn.fetchval("SELECT COUNT(*) FROM wallet_performance")
        print(f"Total Wallets: {total}")
        
    finally:
        await conn.close()

asyncio.run(check())
