
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("SUPABASE_DB_URL")

async def cleanup():
    print(f"Connecting to DB...")
    try:
        conn = await asyncpg.connect(url, statement_cache_size=0)
        print("Connected.")
        
        # Check current count
        total = await conn.fetchval("SELECT COUNT(*) FROM trades")
        print(f"Total trades in DB: {total}")
        
        # Delete trades with entry price 0 or no token amount
        res = await conn.execute("DELETE FROM trades WHERE price_entry = 0 OR amount_token = 0 OR status = 'OPEN'")
        print(f"Cleanup result: {res}")
        
        new_total = await conn.fetchval("SELECT COUNT(*) FROM trades")
        print(f"Total trades remaining: {new_total}")
        
        await conn.close()
    except Exception as e:
        print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    asyncio.run(cleanup())
