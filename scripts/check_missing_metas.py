
import asyncio
from early_detector.db import get_pool

async def check_tokens():
    pool = await get_pool()
    try:
        rows = await pool.fetch("SELECT address, name, symbol FROM tokens WHERE symbol IS NULL OR symbol = '???' LIMIT 20")
        print(f"Found {len(rows)} tokens with missing/bad symbols:")
        for r in rows:
            print(f"Addr: {r['address']} | Name: {r['name']} | Sym: {r['symbol']}")
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(check_tokens())
