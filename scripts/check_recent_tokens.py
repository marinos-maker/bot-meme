
import asyncio
import sys
import os
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from early_detector.db import get_pool, close_pool

async def check_recent_tokens():
    pool = await get_pool()
    print(f"Current Time (UTC): {datetime.now(timezone.utc)}")
    
    print("\n--- 10 Most Recent Tokens ---")
    rows = await pool.fetch("SELECT address, name, symbol, created_at FROM tokens ORDER BY created_at DESC LIMIT 10")
    for r in rows:
        print(f"{r['created_at']} | {r['address']} | {r['symbol']} | {r['name']}")

    print("\n--- Tokens without metrics in last 2 hours ---")
    rows = await pool.fetch("""
        SELECT t.address, t.created_at, MAX(m.timestamp) as last_metric
        FROM tokens t
        LEFT JOIN token_metrics_timeseries m ON m.token_id = t.id
        GROUP BY t.address, t.created_at
        ORDER BY t.created_at DESC
        LIMIT 5
    """)
    for r in rows:
        print(f"Created: {r['created_at']} | Last Metric: {r['last_metric']} | {r['address']}")

    await close_pool()

if __name__ == "__main__":
    asyncio.run(check_recent_tokens())
