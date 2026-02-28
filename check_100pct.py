import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def run():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    for symbol in ["AlxEats", "3/3", "Monitoring", "Centaur"]:
        rows = await conn.fetch(
            f"SELECT m.bonding_is_complete, m.bonding_pct, m.marketcap, m.liquidity, m.liquidity_is_virtual "
            f"FROM token_metrics_timeseries m JOIN tokens t ON t.id = m.token_id "
            f"WHERE t.symbol = '{symbol}' ORDER BY m.timestamp DESC LIMIT 1"
        )
        if rows:
            print(f"{symbol}: {dict(rows[0])}")
        else:
            print(f"{symbol}: None")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
