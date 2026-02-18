
import asyncio
from early_detector.db import get_pool

async def migrate():
    pool = await get_pool()
    print("Migrating Supabase schema for Sync Pro...")
    
    # 1. Update tokens table
    print("- Updating 'tokens' table...")
    await pool.execute("""
        ALTER TABLE tokens 
        ADD COLUMN IF NOT EXISTS narrative VARCHAR(50);
    """)
    
    # 2. Update token_metrics_timeseries table
    print("- Updating 'token_metrics_timeseries' table...")
    await pool.execute("""
        ALTER TABLE token_metrics_timeseries 
        ADD COLUMN IF NOT EXISTS insider_psi FLOAT DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS creator_risk_score FLOAT DEFAULT 0.0;
    """)
    
    # 3. Update signals table
    print("- Updating 'signals' table...")
    await pool.execute("""
        ALTER TABLE signals 
        ADD COLUMN IF NOT EXISTS insider_psi FLOAT DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS creator_risk FLOAT DEFAULT 0.0;
    """)
    
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
