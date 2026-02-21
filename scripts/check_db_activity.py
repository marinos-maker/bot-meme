
import asyncio
from early_detector.db import get_pool

async def check():
    pool = await get_pool()
    # Check tokens created today
    tokens = await pool.fetch("SELECT address, name, symbol, created_at FROM tokens WHERE created_at > NOW() - INTERVAL '1 hour' LIMIT 5")
    print(f"Tokens created in last hour: {len(tokens)}")
    for t in tokens:
        print(f"  {t['address'][:8]} | {t['name']} | {t['symbol']} | {t['created_at']}")
        
    # Check metrics created today
    metrics = await pool.fetchval("SELECT COUNT(*) FROM token_metrics_timeseries WHERE timestamp > NOW() - INTERVAL '1 hour'")
    print(f"Metrics rows in last hour: {metrics}")
    
    # Check wallet performance table size
    wallets = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance")
    print(f"Total wallets in DB: {wallets}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check())
