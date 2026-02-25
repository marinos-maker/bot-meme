
import asyncio
from early_detector.db import get_pool

async def find_mcap():
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT t.address, t.name, t.symbol, m.marketcap 
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE m.marketcap > 30000 AND m.marketcap < 45000
        ORDER BY m.timestamp DESC
        LIMIT 10
    """)
    for r in rows:
        print(f"Addr: {r['address']}, Name: {r['name']}, MCap: ${float(r['marketcap'] or 0):,.2f}")

if __name__ == "__main__":
    asyncio.run(find_mcap())
