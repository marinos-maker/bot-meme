import asyncio
from early_detector.db import get_pool, close_pool

async def job():
    pool = await get_pool()
    with open("labels_debug.txt", "w") as f:
        rows = await pool.fetch("SELECT DISTINCT cluster_label FROM wallet_performance")
        f.write("All cluster labels:\n")
        for r in rows:
            f.write(f"- {r['cluster_label']}\n")
            
        rows = await pool.fetch("SELECT wallet, cluster_label FROM wallet_performance WHERE cluster_label IS NOT NULL AND (cluster_label ILIKE '%scam%' OR cluster_label ILIKE '%bad%' OR cluster_label ILIKE '%sus%') LIMIT 10")
        if rows:
            f.write("\nSuspicious:\n")
            for r in rows:
                f.write(f"- {r['wallet']}: {r['cluster_label']}\n")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(job())
