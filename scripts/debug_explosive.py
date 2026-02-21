
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def check_explosive_tokens():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    try:
        print("--- Investigating Explosive Volume Tokens (Last 4h) ---")
        # Query tokens that have high volume shift or are in the top turnover list
        # Based on the user's report, we want to see why they didn't trigger signals.
        
        # First, let's find the addresses for some of the partial matches if possible, 
        # or just look at the top instability/volume tokens.
        
        rows = await conn.fetch("""
            SELECT t.address, t.symbol, m.instability_index, m.liquidity, m.marketcap, 
                   m.volume_5m, m.volume_1h, m.timestamp
            FROM token_metrics_timeseries m
            JOIN tokens t ON t.id = m.token_id
            WHERE m.timestamp > NOW() - INTERVAL '4 hours'
            ORDER BY m.volume_5m DESC
            LIMIT 20
        """)
        
        for r in rows:
            print(f"Token: {r['symbol']} ({r['address'][:10]}...)")
            print(f"  Vol 5m: ${r['volume_5m']:,.2f} | Vol 1h: ${r['volume_1h']:,.2f}")
            print(f"  II: {r['instability_index']:.4f} | Liq: ${r['liquidity']:,.0f} | Mcap: ${r['marketcap']:,.0f}")
            
            # Check if it would pass trigger
            # (threshold is dynamic, let's assume ~1.5 - 2.0 based on previous checks)
            low_liq = r['liquidity'] < 40000 if r['liquidity'] is not None else True
            high_mcap = r['marketcap'] > 10000000 if r['marketcap'] is not None else False
            
            rejection_reasons = []
            if low_liq: rejection_reasons.append("Low Liquidity (<40k)")
            if high_mcap: rejection_reasons.append("High MarketCap (>10M)")
            if r['instability_index'] < 0.1: rejection_reasons.append("Low Instability Index")
            
            if rejection_reasons:
                print(f"  Status: REJECTED by Signal Engine - Reasons: {', '.join(rejection_reasons)}")
            else:
                print(f"  Status: POTENTIAL SIGNAL (Check momentum/vol_shift)")
            print("-" * 30)

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_explosive_tokens())
