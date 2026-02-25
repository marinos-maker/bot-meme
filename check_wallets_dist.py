import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_wallets():
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM wallet_performance")
        with_trades = await conn.fetchval("SELECT COUNT(*) FROM wallet_performance WHERE total_trades > 0")
        
        # Test different thresholds
        thresholds = [
            (1.1, 1, 0.25),
            (1.1, 2, 0.25),
            (1.2, 2, 0.30),
            (1.3, 2, 0.35),
            (1.5, 3, 0.40)
        ]
        
        print(f"Total wallets in DB: {total}")
        print(f"Wallets with trades > 0: {with_trades}")
        print("-" * 30)
        
        for roi, trades, wr in thresholds:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM wallet_performance WHERE (avg_roi > $1 AND total_trades >= $2 AND win_rate > $3) OR (avg_roi > 10.0 AND total_trades >= 3)",
                roi, trades, wr
            )
            print(f"Threshold (ROI > {roi}, Trades >= {trades}, WR > {wr}) + OR(10x,3t): {count}")
            
        # Check ROI distribution
        roi_dist = await conn.fetch("SELECT floor(avg_roi) as bucket, COUNT(*) FROM wallet_performance WHERE total_trades > 0 GROUP BY bucket ORDER BY bucket")
        print("\nROI Distribution (buckets):")
        for r in roi_dist:
            print(f"  ROI {float(r['bucket']):.1f}x - {float(r['bucket'])+1.0:.1f}x: {r['count']}")
            
        # Check Win Rate distribution
        wr_dist = await conn.fetch("SELECT (floor(win_rate * 10) / 10.0) as bucket, COUNT(*) FROM wallet_performance WHERE total_trades > 0 GROUP BY bucket ORDER BY bucket")
        print("\nWin Rate Distribution (buckets):")
        for r in wr_dist:
            bucket_val = float(r['bucket']) if r['bucket'] is not None else 0.0
            print(f"  WR {bucket_val:.1f} - {bucket_val+0.1:.1f}: {r['count']}")

        # Top 10 wallets by ROI
        top_wallets = await conn.fetch("SELECT wallet, avg_roi, total_trades, win_rate FROM wallet_performance WHERE total_trades >= 2 ORDER BY avg_roi DESC LIMIT 10")
        print("\nTop 10 Wallets (Trades >= 2):")
        for r in top_wallets:
            print(f"  {r['wallet']}: ROI={r['avg_roi']:.2f}, Trades={r['total_trades']}, WR={r['win_rate']:.2f}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_wallets())
