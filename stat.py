import asyncio
from early_detector.db import get_pool
from datetime import datetime, timedelta

async def get_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        active_tokens = await conn.fetchval("SELECT COUNT(*) FROM tokens")
        old_tokens = await conn.fetchval("SELECT COUNT(*) FROM tokens WHERE created_at < $1", datetime.utcnow() - timedelta(days=1))
        signals = await conn.fetchval("SELECT COUNT(*) FROM signals")
        wallets = await conn.fetchval("SELECT COUNT(*) FROM wallet_performance")
        print(f"Active Tokens: {active_tokens} (Older than 1 day: {old_tokens})")
        print(f"Total Signals: {signals}")
        print(f"Total Wallets: {wallets}")

asyncio.run(get_stats())
