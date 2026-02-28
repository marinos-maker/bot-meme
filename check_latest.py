import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def check():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    rows = await conn.fetch("SELECT address, symbol, name, created_at FROM tokens ORDER BY created_at DESC LIMIT 20")
    print(f"{'Address':<44} | {'Symbol':<10} | {'Created':<20}")
    print("-" * 80)
    for r in rows:
        print(f"{r['address']:<44} | {str(r['symbol'])[:10]:<10} | {str(r['created_at'])[:19]}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
