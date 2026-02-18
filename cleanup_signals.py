
import asyncio
from early_detector.db import get_pool

async def cleanup():
    pool = await get_pool()
    print("Cleaning up duplicate signals...")
    
    # Identify duplicates: same token_id, within 60 mins of a previous one.
    # Actually, simpler: Key by (token_id, date_trunc('hour', timestamp)) or similar.
    # Or just keep the first one in every 60m window.
    
    # We will delete signals where there exists an OLDER signal for same token within 59 minutes
    query = """
        DELETE FROM signals s1
        WHERE EXISTS (
            SELECT 1 FROM signals s2
            WHERE s2.token_id = s1.token_id
              AND s2.timestamp < s1.timestamp
              AND s2.timestamp > s1.timestamp - INTERVAL '60 minutes'
        )
    """
    result = await pool.execute(query)
    print(f"Deleted duplicates: {result}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(cleanup())
