
import asyncio
from early_detector.db import get_pool, close_pool

async def clear_signals():
    print("Cleaning up signals table...")
    pool = await get_pool()
    try:
        count = await pool.fetchval("SELECT COUNT(*) FROM signals")
        await pool.execute("DELETE FROM signals")
        print(f"Deleted {count} signals.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(clear_signals())
