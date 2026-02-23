import asyncio
from early_detector.db import get_pool, close_pool

async def main():
    pool = await get_pool()
    
    print("🗑️ Deleting old metrics (keeping only the last 1 hour)...")
    res1 = await pool.execute("DELETE FROM token_metrics_timeseries WHERE timestamp < NOW() - INTERVAL '1 hour'")
    print(res1)
    
    print("🗑️ Deleting orphaned tokens (no recent metrics, no trades, no signals)...")
    res2 = await pool.execute("""
        DELETE FROM tokens 
        WHERE id NOT IN (SELECT DISTINCT token_id FROM token_metrics_timeseries)
        AND id NOT IN (SELECT DISTINCT token_id FROM trades)
        AND id NOT IN (SELECT DISTINCT token_id FROM signals)
    """)
    print(res2)
    
    print("✅ Cleanup complete!")
    await close_pool()

asyncio.run(main())
