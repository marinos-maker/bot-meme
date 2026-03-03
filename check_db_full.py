import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from early_detector.db import get_pool, close_pool

async def list_all_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Query for all tables in the public schema
        rows = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        print("Tables in database:")
        for row in rows:
            print(f"- {row['table_name']}")
            
            # For each table, get column names
            columns = await conn.fetch(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{row['table_name']}'
            """)
            print(f"  Columns: {[c['column_name'] for c in columns]}")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(list_all_tables())
