
import asyncio
import os
from early_detector.db import get_pool

async def main():
    pool = await get_pool()
    query = """
        SELECT s.token_id, t.symbol, s.timestamp, s.instability_index 
        FROM signals s
        JOIN tokens t ON t.id = s.token_id
        ORDER BY s.timestamp DESC LIMIT 10
    """
    try:
        rows = await pool.fetch(query)
        print("Last 10 signals:")
        for r in rows:
            print(f"{r['symbol']} ({r['token_id']}): {r['timestamp']} - II={r['instability_index']}")
        
        if rows:
            latest_id = str(rows[0]['token_id'])
            print(f"\nChecking duplicates for {latest_id}...")
            
            # Replicate the logic in db.py
            check_query = """
                SELECT 1 FROM signals 
                WHERE token_id = $1 
                AND timestamp > NOW() - INTERVAL '60 minutes'
                LIMIT 1
            """
            result = await pool.fetchval(check_query, latest_id)
            print(f"Is recent (direct query)? {result}")
            
            # Count how many in last hour
            count_query = """
                SELECT COUNT(*) FROM signals 
                WHERE token_id = $1 
                AND timestamp > NOW() - INTERVAL '60 minutes'
            """
            count = await pool.fetchval(count_query, latest_id)
            print(f"Count in last hour: {count}")
            
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
