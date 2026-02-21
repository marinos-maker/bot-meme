
import asyncio
import asyncpg
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("SUPABASE_DB_URL")

async def check():
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        rows = await conn.fetch("""
            SELECT tm.token_id, t.symbol, tm.timestamp, tm.instability_index, tm.liquidity, tm.marketcap, tm.volume_5m
            FROM token_metrics_timeseries tm
            JOIN tokens t ON tm.token_id = t.id
            WHERE tm.timestamp > NOW() - INTERVAL '30 minutes'
            AND tm.instability_index != 0
            ORDER BY tm.timestamp DESC
            LIMIT 50
        """)
        
        if not rows:
            print("No non-zero II metrics found in the last 30 minutes.")
            return

        df = pd.DataFrame(rows, columns=['id', 'symbol', 'ts', 'ii', 'liq', 'mcap', 'vol_5m'])
        print(f"Latest 50 active metrics (last 30m):\n{df.to_string()}")
        
        avg_ii = await conn.fetchval("SELECT AVG(instability_index) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '1 hour'")
        print(f"\nGlobal Average II (1h): {avg_ii}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
