
import asyncio
from early_detector.db import get_pool
from datetime import datetime

async def check():
    pool = await get_pool()
    val = await pool.fetchval("SELECT MAX(last_active) FROM wallet_performance")
    now = await pool.fetchval("SELECT NOW()")
    print(f"Current DB Time: {now}")
    print(f"Max Last Active in DB: {val}")
    
    # Check count of wallets updated today (2026-02-20)
    count_today = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance WHERE last_active >= '2026-02-20'")
    print(f"Wallets updated today: {count_today}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check())
