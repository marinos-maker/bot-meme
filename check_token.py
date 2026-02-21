
import asyncio
from early_detector.db import get_pool

async def check():
    pool = await get_pool()
    rows = await pool.fetch("SELECT address, symbol, name FROM tokens WHERE symbol ILIKE '%BLACKMAC%'")
    for r in rows:
        print(f"Address: {r['address']}, Symbol: {r['symbol']}, Name: {r['name']}")

if __name__ == "__main__":
    asyncio.run(check())
