import asyncio
from early_detector.db import get_pool

async def main():
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT s.timestamp, t.symbol, t.address, s.ai_summary 
        FROM signals s 
        JOIN tokens t ON s.token_id = t.id 
        WHERE s.ai_summary LIKE '%SNIPER%' 
        ORDER BY s.timestamp DESC 
        LIMIT 10
    """)
    print("--- RECENT SNIPER SIGNALS RECORDED ---")
    for r in rows:
        print(f"{r['timestamp']} | {r['symbol']} | {r['address'][:10]}... | {r['ai_summary']}")
    print("---------------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
