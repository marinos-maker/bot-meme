import asyncio
from early_detector.db import get_pool

async def check_counts():
    pool = await get_pool()
    
    token_count = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    metrics_count = await pool.fetchval("SELECT COUNT(*) FROM token_metrics_timeseries")
    signals_count = await pool.fetchval("SELECT COUNT(*) FROM signals")
    wallets_count = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance")
    trades_count = await pool.fetchval("SELECT COUNT(*) FROM trades")
    smart_wallets = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance WHERE cluster_label IN ('smart', 'insider')")

    orphaned = await pool.fetchval("SELECT COUNT(*) FROM tokens WHERE id NOT IN (SELECT DISTINCT token_id FROM token_metrics_timeseries)")
    active_tokens = await pool.fetchval("SELECT COUNT(DISTINCT token_id) FROM token_metrics_timeseries")
    
    print(f"--- DATABASE STATUS ---")
    print(f"Total Tokens in DB: {token_count}")
    print(f"Tokens with metrics: {active_tokens}")
    print(f"Orphaned tokens: {orphaned}")
    print(f"Wallets Profiled: {wallets_count}")
    print(f"-----------------------")

if __name__ == "__main__":
    asyncio.run(check_counts())
