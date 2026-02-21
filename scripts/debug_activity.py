
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def check_activity():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    try:
        t_count = await conn.fetchval("SELECT COUNT(*) FROM tokens")
        t_new_5h = await conn.fetchval("SELECT COUNT(*) FROM tokens WHERE created_at > NOW() - INTERVAL '5 hours'")
        m_count_5h = await conn.fetchval("SELECT COUNT(*) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '5 hours'")
        s_count_5h = await conn.fetchval("SELECT COUNT(*) FROM signals WHERE timestamp > NOW() - INTERVAL '5 hours'")
        
        print(f"--- Bot Activity (Last 5 hours) ---")
        print(f"Total tokens in DB: {t_count}")
        print(f"New tokens discovered (5h): {t_new_5h}")
        print(f"Metric entries collected (5h): {m_count_5h}")
        print(f"Signals generated (5h): {s_count_5h}")
        
        if m_count_5h > 0:
            avg_ii = await conn.fetchval("SELECT AVG(instability_index) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '5 hours'")
            max_ii = await conn.fetchval("SELECT MAX(instability_index) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '5 hours'")
            print(f"Avg Instability Index: {avg_ii}")
            print(f"Max Instability Index: {max_ii}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_activity())
