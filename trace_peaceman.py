import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def check():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    rows = await conn.fetch("SELECT address, symbol, name, created_at FROM tokens WHERE symbol ILIKE '%PEACEMAN%'")
    for r in rows:
        print(f"Address: {r['address']}, Symbol: {r['symbol']}, Name: {r['name']}, Created: {r['created_at']}")
        
        # Check metrics for this address
        m = await conn.fetchrow("SELECT m.* FROM token_metrics_timeseries m JOIN tokens t ON t.id = m.token_id WHERE t.address = $1 ORDER BY m.timestamp DESC LIMIT 1", r['address'])
        if m:
            print(f"  Latest Metrics: Mcap: {m['marketcap']}, Liq: {m['liquidity']}, II: {m['instability_index']}, Time: {m['timestamp']}")
        else:
            print("  No metrics found.")
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
