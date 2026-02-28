import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def check_token(symbol):
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    row = await conn.fetchrow("""
        SELECT t.symbol, m.* 
        FROM tokens t 
        JOIN token_metrics_timeseries m ON m.token_id = t.id 
        WHERE t.symbol ILIKE $1 
        ORDER BY m.timestamp DESC 
        LIMIT 1
    """, symbol)
    if row:
        d = dict(row)
        for k, v in d.items():
            print(f"{k}: {v}")
    else:
        print("Token not found.")
    await conn.close()

if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "IranTroll"
    asyncio.run(check_token(symbol))
