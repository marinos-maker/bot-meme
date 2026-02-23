import asyncio
from early_detector.db import get_pool, close_pool

async def main():
    pool = await get_pool()
    # Pulisco TUTTA la tabella signals in modo da resettare completamente la dashboard 
    # e far apparire solo quelli nuovi generati ORA dalla nuova Intelligenza Artificiale.
    await pool.execute("TRUNCATE TABLE signals")
    print("Database signals riavviato da zero!")
    await close_pool()

asyncio.run(main())
