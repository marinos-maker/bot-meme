
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("SUPABASE_DB_URL")

async def check():
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        sig_count = await conn.fetchval("SELECT COUNT(*) FROM signals WHERE timestamp > NOW() - INTERVAL '1 hour'")
        token_count = await conn.fetchval("SELECT COUNT(*) FROM tokens WHERE created_at > NOW() - INTERVAL '1 hour'")
        metrics_count = await conn.fetchval("SELECT COUNT(*) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '1 hour'")
        
        print(f"Signals (1h): {sig_count}")
        print(f"New Tokens (1h): {token_count}")
        print(f"Metrics Recorded (1h): {metrics_count}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
