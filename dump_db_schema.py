import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from early_detector.db import get_pool, close_pool

async def list_all_tables():
    pool = await get_pool()
    output = []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        output.append("Tables in database:")
        for row in rows:
            output.append(f"- {row['table_name']}")
            columns = await conn.fetch(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{row['table_name']}'
            """)
            output.append(f"  Columns: {[c['column_name'] for c in columns]}")
    await close_pool()
    
    with open("db_tables_info.txt", "w") as f:
        f.write("\n".join(output))
    print("Information written to db_tables_info.txt")

if __name__ == "__main__":
    asyncio.run(list_all_tables())
