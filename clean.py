import asyncio
from early_detector.db import get_pool
from datetime import datetime, timedelta

async def clean_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            # Delete old tokens
            old_t = await conn.execute("DELETE FROM tokens WHERE created_at < $1", datetime.utcnow() - timedelta(days=2))
            
            w_0 = await conn.execute("DELETE FROM wallet_performance WHERE avg_roi <= 1.0 AND total_trades <= 3")
            
            # Let's delete signals that are older than 3 days
            old_s = await conn.execute("DELETE FROM signals WHERE timestamp < $1", datetime.utcnow() - timedelta(days=3))
            
            print(f"Old Tokens Deleted: {old_t}")
            print(f"Useless Wallets Deleted: {w_0}")
            print(f"Old Signals Deleted: {old_s}")

            # Execute vacuum mapping if you want
            
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(clean_db())
