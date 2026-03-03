import asyncio
from early_detector.db import get_pool, close_pool

async def check_labels():
    pool = await get_pool()
    rows = await pool.fetch("SELECT cluster_label, COUNT(*) as count FROM wallet_performance GROUP BY cluster_label")
    for r in rows:
        print(f"Label: {r['cluster_label']}, Count: {r['count']}")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(check_labels())
