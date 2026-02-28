import asyncio
import asyncpg
import os
import math
from dotenv import load_dotenv

async def check_heatmap_data():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    
    # Get latest metrics for 20 tokens
    rows = await conn.fetch("""
        WITH recent_metrics AS (
            SELECT t.address, t.symbol, t.name,
                   m.price, m.marketcap, m.liquidity, 
                   m.volume_5m, m.instability_index, m.timestamp, m.bonding_pct, m.bonding_is_complete,
                   ROW_NUMBER() OVER(PARTITION BY t.address ORDER BY m.timestamp DESC) as rn
            FROM tokens t
            JOIN token_metrics_timeseries m ON m.token_id = t.id
            WHERE m.timestamp > NOW() - INTERVAL '1 hour'
        )
        SELECT * FROM recent_metrics 
        WHERE rn = 1 AND instability_index IS NOT NULL
        ORDER BY instability_index DESC
        LIMIT 20
    """)
    
    print(f"{'Symbol':<10} | {'II':<8} | {'Velocity':<10} | {'Mcap':<10} | {'Bonding':<8}")
    print("-" * 55)
    
    for r in rows:
        liq = float(r["liquidity"] or 0)
        vol = float(r["volume_5m"] or 0)
        velocity = (vol / (liq + 1)) * 100 # No liq > 0 check anymore
        instability = float(r["instability_index"] or 0)
        mcap = float(r["marketcap"] or 0)
        
        # Bonding calc
        if r.get("bonding_is_complete"):
            bonding = 100.0
        elif r.get("bonding_pct") is not None and float(r.get("bonding_pct")) > 0:
            bonding = float(r.get("bonding_pct"))
        else:
            bonding = min((mcap / 65000) * 100, 100) if r["address"].endswith("pump") else 100
            
        print(f"{r['symbol'][:10]:<10} | {instability:<8.2f} | {velocity:<10.1f}% | ${mcap:<9,.0f} | {bonding:<7.1f}%")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_heatmap_data())
