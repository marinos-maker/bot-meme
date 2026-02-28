import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def check_address(symbol):
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    row = await conn.fetchrow("SELECT address FROM tokens WHERE symbol ILIKE $1", symbol)
    if row:
        print(row['address'])
    else:
        print("Not found")
    await conn.close()

if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "IranTroll"
    asyncio.run(check_address(symbol))
