import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def check():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    symbols = ['MARCH', 'AIMAXXING', 'PEACEMAN', 'Shiro']
    print(f"Checking symbols: {symbols}")
    rows = await conn.fetch("SELECT address, symbol, name, created_at FROM tokens WHERE symbol = ANY($1)", symbols)
    for r in rows:
        print(f"{r['symbol']:<10} | {r['address']:<44} | {r['created_at']}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
