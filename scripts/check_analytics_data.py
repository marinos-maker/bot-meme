
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from early_detector.db import get_pool, close_pool

async def check_data():
    pool = await get_pool()
    
    print("\n--- Checking Data for Analytics ---")

    # 1. Total Tokens
    tokens_count = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    print(f"Total Tokens: {tokens_count}")

    # 2. Total Metrics
    metrics_count = await pool.fetchval("SELECT COUNT(*) FROM token_metrics_timeseries")
    print(f"Total Metrics Rows: {metrics_count}")

    # 3. Recent Metrics (Last 30 mins)
    recent_metrics_count = await pool.fetchval(
        "SELECT COUNT(*) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '30 minutes'"
    )
    print(f"Metrics in last 30 mins: {recent_metrics_count}")

    if recent_metrics_count == 0:
        # Check the latest metric timestamp
        last_metric = await pool.fetchrow("SELECT timestamp FROM token_metrics_timeseries ORDER BY timestamp DESC LIMIT 1")
        if last_metric:
            print(f"Latest metric was at: {last_metric['timestamp']}")
        else:
            print("No metrics found at all.")
    else:
        # Check if liquidity and volume are populated
        sample = await pool.fetchrow(
            """
            SELECT liquidity, volume_5m, instability_index 
            FROM token_metrics_timeseries 
            WHERE timestamp > NOW() - INTERVAL '30 minutes' 
            LIMIT 1
            """
        )
        print(f"Sample recent metric: {sample}")

    await close_pool()

if __name__ == "__main__":
    asyncio.run(check_data())
