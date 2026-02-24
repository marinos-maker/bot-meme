
import asyncio
from early_detector.db import get_pool, close_pool

async def clear_adhd():
    pool = await get_pool()
    addr = "ByPRjYBLsk"
    print(f"Clearing signals for {addr}...")
    res = await pool.execute(
        "DELETE FROM signals WHERE token_id IN (SELECT id FROM tokens WHERE address LIKE $1)",
        f"{addr}%"
    )
    print(f"Result: {res}")
    
    # Also delete metrics from the last 5 minutes to force a re-scan if needed? 
    # No, just let the next cycle handle it.
    
    await close_pool()

if __name__ == "__main__":
    asyncio.run(clear_adhd())
