import asyncio
from loguru import logger
from early_detector.db import get_pool, close_pool

async def check_labels_full():
    pool = await get_pool()
    rows = await pool.fetch("SELECT DISTINCT cluster_label FROM wallet_performance")
    logger.warning("All cluster labels:")
    for r in rows:
        logger.warning(f"- {r['cluster_label']}")
    
    # Check if there are any wallets with keyword "scam" or "bad" or something
    rows = await pool.fetch("SELECT wallet, cluster_label FROM wallet_performance WHERE cluster_label ILIKE '%scam%' OR cluster_label ILIKE '%bad%' OR cluster_label ILIKE '%sus%' LIMIT 10")
    if rows:
        logger.warning("Suspicious wallets found:")
        for r in rows:
            logger.warning(f"- Wallet: {r['wallet']}, Label: {r['cluster_label']}")
    else:
        logger.warning("No labels matching scam/bad/sus found.")
        
    await close_pool()

if __name__ == "__main__":
    asyncio.run(check_labels_full())
