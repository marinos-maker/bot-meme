
import asyncio
import asyncpg
import os
from dotenv import load_dotenv
import pandas as pd

load_dotenv()
url = os.getenv("SUPABASE_DB_URL")

async def check():
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        rows = await conn.fetch("""
            SELECT t.symbol, tr.amount_sol, tr.price_entry, tr.amount_token, tr.tx_hash_buy, tr.created_at 
            FROM trades tr 
            JOIN tokens t ON tr.token_id = t.id 
            ORDER BY tr.created_at DESC 
            LIMIT 10
        """)
        df = pd.DataFrame(rows, columns=['symbol', 'sol', 'price', 'tokens', 'hash', 'at'])
        print(df.to_string())
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
