
import asyncio
from early_detector.db import get_pool

async def find_turtle():
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT address, name, symbol FROM tokens WHERE name ILIKE '%Turtle%' OR symbol ILIKE '%Turtle%'
    """)
    for r in rows:
        print(f"Address: {r['address']}, Name: {r['name']}, Symbol: {r['symbol']}")

if __name__ == "__main__":
    asyncio.run(find_turtle())
