import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def check():
    load_dotenv()
    # just create a new connection for each to avoid pgbouncer issue
    for sym in ['AlxEats', 'Centaur', '3/3']:
        conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
        rows = await conn.fetch(f"SELECT m.timestamp, m.bonding_pct, m.marketcap, m.liquidity, m.liquidity_is_virtual " 
                                f"FROM token_metrics_timeseries m JOIN tokens t ON t.id = m.token_id " 
                                f"WHERE t.symbol = '{sym}' ORDER BY m.timestamp DESC LIMIT 3")
        for r in rows:
            print(f"{sym}: Time={str(r['timestamp'])[:19]} MCap={r['marketcap']:.0f} Liq={r['liquidity']:.0f} "
                  f"Virtual={r['liquidity_is_virtual']} Pct={r['bonding_pct']}")
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
