
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def debug_thresholds():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    try:
        print("--- Debugging Top 10 tokens by Instability (Last 5h) ---")
        rows = await conn.fetch("""
            SELECT t.address, t.symbol, m.instability_index, m.liquidity, m.marketcap, m.timestamp
            FROM token_metrics_timeseries m
            JOIN tokens t ON t.id = m.token_id
            WHERE m.timestamp > NOW() - INTERVAL '5 hours'
            ORDER BY m.instability_index DESC
            LIMIT 10
        """)
        
        for r in rows:
            print(f"Token: {r['symbol']} ({r['address'][:8]}...) | II: {r['instability_index']:.4f} | Liq: {r['liquidity']:,.0f} | Mcap: {r['marketcap']:,.0f}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(debug_thresholds())
